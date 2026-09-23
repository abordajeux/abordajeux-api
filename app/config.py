import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_path: str = "abordajeux.db"
    cors_origins: list[str] = field(default_factory=lambda: [])
    mail_api_key: str = ""
    mail_sender: str = ""
    mail_contact_email: str = ""
    rate_limit_seconds: int = 30
    verify_base_url: str = "https://abordajeux.github.io/presque/verify"


def load_settings() -> Settings:
    cors_raw = os.environ.get("CORS_ORIGINS", "")
    return Settings(
        database_path=os.environ.get("DATABASE_PATH", "abordajeux.db"),
        cors_origins=[
            origin.strip() for origin in cors_raw.split(",") if origin.strip()
        ],
        mail_api_key=os.environ.get("MAIL_API_KEY", ""),
        mail_sender=os.environ.get("MAIL_SENDER", ""),
        mail_contact_email=os.environ.get("MAIL_CONTACT_EMAIL", ""),
        rate_limit_seconds=int(os.environ.get("RATE_LIMIT_SECONDS", "30")),
        verify_base_url=os.environ.get(
            "VERIFY_BASE_URL", "https://abordajeux.github.io/presque/verify"),
    )
