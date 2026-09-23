import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MESSAGE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def sanitize_line(value: str) -> str:
    return _CONTROL_CHARS.sub("", value)


def sanitize_message(value: str) -> str:
    return _MESSAGE_CONTROL_CHARS.sub("", value)


class ParticipantIn(BaseModel):
    name: str = Field(max_length=50)


class SignupRequest(BaseModel):
    contact_email: EmailStr
    participants: list[ParticipantIn] = Field(min_length=1, max_length=10)


class ActivitySignups(BaseModel):
    id: str | None = None
    max: int
    confirmed: int
    pending: int
    waitlisted: int


class SignupOk(BaseModel):
    status: str = "ok"
    verification_required: bool = True
    waitlisted: bool = False
    message: str


class CapacityExceeded(BaseModel):
    status: str = "capacity_exceeded"
    max: int
    confirmed: int
    pending: int
    available: int
    requested: int
    message: str


class VerifyRequest(BaseModel):
    token: str


class VerifyConfirmed(BaseModel):
    status: str = "confirmed"
    activity_id: str
    waitlisted: bool = False


class VerifyInvalid(BaseModel):
    status: str = "invalid_token"


class VerifyExpired(BaseModel):
    status: str = "expired"


class ContactFormRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=200)
    sender_email: EmailStr
    message: str = Field(min_length=1, max_length=5000)

    @field_validator("subject")
    @classmethod
    def _clean_subject(cls, value: str) -> str:
        cleaned = sanitize_line(value)
        if not cleaned:
            raise ValueError("subject must not be empty after sanitization")
        return cleaned

    @field_validator("message")
    @classmethod
    def _clean_message(cls, value: str) -> str:
        return sanitize_message(value)


class FeedbackFormRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event: str = Field(min_length=1, max_length=100)
    sender_email: EmailStr
    message: str = Field(min_length=1, max_length=5000)
    planning_rating: int = Field(ge=0, le=5)
    welcome_rating: int = Field(ge=0, le=5)

    @field_validator("event")
    @classmethod
    def _clean_event(cls, value: str) -> str:
        cleaned = sanitize_line(value)
        if not cleaned:
            raise ValueError("event must not be empty after sanitization")
        return cleaned

    @field_validator("message")
    @classmethod
    def _clean_message(cls, value: str) -> str:
        return sanitize_message(value)


class FormOk(BaseModel):
    status: str = "ok"
    message: str


class InvalidEmail(BaseModel):
    status: str = "invalid_email"
    message: str


class RateLimited(BaseModel):
    status: str = "rate_limited"
    message: str
