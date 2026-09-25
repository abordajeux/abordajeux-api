from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PAYLOAD_TOO_LARGE_MSG = (
    "Requête trop volumineuse. Veuillez réduire la taille de votre envoi.")


class _RequestTooLarge(Exception):
    pass


def _payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "status": "payload_too_large",
            "message": PAYLOAD_TOO_LARGE_MSG
        },
    )


class BodySizeLimitMiddleware:

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive,
                       send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        content_length = self._content_length(scope)
        if content_length is not None and content_length > self._max_body_bytes:
            await _payload_too_large_response()(scope, receive, send)
            return
        if content_length is not None:
            await self._app(scope, receive, send)
            return
        await self._handle_chunked(scope, receive, send)

    async def _handle_chunked(self, scope: Scope, receive: Receive,
                              send: Send) -> None:
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_body_bytes:
                    raise _RequestTooLarge()
            return message

        try:
            await self._app(scope, limited_receive, send)
        except _RequestTooLarge:
            await _payload_too_large_response()(scope, receive, send)

    def _content_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None
