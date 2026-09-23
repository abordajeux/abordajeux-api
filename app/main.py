import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app import db as db_mod
from app import email
from app.config import Settings, load_settings
from app.email import MailSender
from app.schemas import (
    ActivitySignups,
    CapacityExceeded,
    SignupOk,
    SignupRequest,
    VerifyConfirmed,
    VerifyRequest,
)

from . import signups

CAPACITY_EXCEEDED_MSG = (
    "Il ne reste plus de places pour cette activité. "
    "Des places pourraient se libérer demain si certaines inscriptions ne sont pas confirmées."
)
INVALID_EMAIL_MSG = "Le domaine de votre adresse email semble invalide. Vérifiez votre saisie."
RATE_LIMITED_MSG = "Trop de tentatives. Veuillez patienter quelques secondes avant de réessayer."
WAITLISTED_MSG = (
    "Cette activité est complète : vous avez été ajouté·e à la liste d'attente. "
    "Un email de confirmation vous a été envoyé à {email}.")
SIGNUP_OK_MSG = "Un email de confirmation a été envoyé à {email}."


class APIError(Exception):

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db_mod.connect(request.app.state.settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_http_client(request: Request) -> httpx.Client:
    return request.app.state.http_client


def get_mail_sender(request: Request) -> MailSender:
    return request.app.state.mail_sender


def get_client_ip(request: Request) -> str:
    connecting_ip = request.headers.get("CF-Connecting-IP")
    if connecting_ip:
        return connecting_ip
    return get_remote_address(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    conn = db_mod.connect(settings.database_path)
    try:
        db_mod.init_schema(conn)
    finally:
        conn.close()
    http_client = httpx.Client(timeout=10.0)
    app.state.http_client = http_client
    app.state.mail_sender = email.BrevoSender(
        http_client,
        api_key=settings.mail_api_key,
        sender_email=settings.mail_sender,
        sender_name=email.SENDER_NAME,
    )
    try:
        yield
    finally:
        http_client.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    app = FastAPI(title="Abordajeux Subscription API", lifespan=lifespan)
    app.state.settings = settings

    limiter = Limiter(key_func=get_client_ip)
    app.state.limiter = limiter

    @app.exception_handler(APIError)
    async def handle_api_error(_request: Request,
                               exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.payload)

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit(_request: Request,
                                _exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429,
                            content={
                                "status": "rate_limited",
                                "message": RATE_LIMITED_MSG
                            })

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/activities")
    def list_activities(
            conn: Annotated[sqlite3.Connection,
                            Depends(get_db)]) -> dict:
        items = signups.get_all_activity_signups(conn)
        return {
            "activities": [
                ActivitySignups(id=c.id,
                                max=c.max,
                                confirmed=c.confirmed,
                                pending=c.pending,
                                waitlisted=c.waitlisted).model_dump()
                for c in items
            ]
        }

    @app.get("/activities/{activity_id}", response_model=ActivitySignups)
    def get_activity(
        activity_id: str, conn: Annotated[sqlite3.Connection,
                                          Depends(get_db)]) -> ActivitySignups:
        result = signups.get_activity_signups(conn, activity_id)
        if result is None:
            raise APIError(404, {"status": "not_found"})
        return ActivitySignups(id=result.id,
                               max=result.max,
                               confirmed=result.confirmed,
                               pending=result.pending,
                               waitlisted=result.waitlisted)

    signup_rate = f"1/{settings.rate_limit_seconds}seconds"

    @app.post("/activities/{activity_id}/signup", response_model=SignupOk)
    @limiter.limit(signup_rate)
    def signup(
        request: Request,
        activity_id: str,
        body: SignupRequest,
        conn: Annotated[sqlite3.Connection,
                        Depends(get_db)],
        sender: Annotated[MailSender, Depends(get_mail_sender)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> SignupOk:
        contact_email = str(body.contact_email)
        if not email.has_valid_mx(contact_email):
            raise APIError(422, {
                "status": "invalid_email",
                "message": INVALID_EMAIL_MSG
            })

        token = uuid.uuid4().hex
        try:
            result = signups.reserve_signups(
                conn,
                activity_id,
                contact_email,
                [participant.name for participant in body.participants],
                verification_token=token,
            )
        except signups.ActivityNotFound as exc:
            raise APIError(404, {"status": "not_found"}) from exc

        if not result.ok:
            state = result.signups
            raise APIError(
                422,
                CapacityExceeded(
                    max=state.max,
                    confirmed=state.confirmed,
                    pending=state.pending,
                    available=state.available,
                    requested=result.requested,
                    message=CAPACITY_EXCEEDED_MSG,
                ).model_dump(),
            )

        verify_link = f"{settings.verify_base_url}?token={token}"
        if result.waitlisted:
            content = email.build_waitlist_email(
                activity_title=result.activity_title,
                starts_at=result.activity_starts_at,
                verify_link=verify_link,
                contact_email=settings.mail_contact_email,
            )
            message = WAITLISTED_MSG.format(email=contact_email)
        else:
            content = email.build_verification_email(
                activity_title=result.activity_title,
                starts_at=result.activity_starts_at,
                verify_link=verify_link,
                contact_email=settings.mail_contact_email,
            )
            message = SIGNUP_OK_MSG.format(email=contact_email)
        sender.send(to_email=contact_email, content=content)
        return SignupOk(message=message, waitlisted=result.waitlisted)

    @app.post("/verify", response_model=VerifyConfirmed)
    def verify(
        body: VerifyRequest,
        conn: Annotated[sqlite3.Connection,
                        Depends(get_db)]) -> VerifyConfirmed:
        outcome = signups.confirm_by_token(conn, body.token)
        if outcome.status == "invalid_token":
            raise APIError(404, {"status": "invalid_token"})
        if outcome.status == "expired":
            raise APIError(410, {"status": "expired"})
        return VerifyConfirmed(activity_id=outcome.activity_id or "",
                               waitlisted=outcome.waitlisted)

    return app


app = create_app()
