from pydantic import BaseModel, EmailStr, Field


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


class InvalidEmail(BaseModel):
    status: str = "invalid_email"
    message: str


class RateLimited(BaseModel):
    status: str = "rate_limited"
    message: str
