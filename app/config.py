import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_path: str = "abordajeux.db"
    programme_path: str = "programme.json"
    cors_origins: list[str] = field(default_factory=lambda: [])
    mail_api_key: str = ""
    mail_sender: str = ""
    mail_contact_email: str = ""
    mail_benevole_email: str = ""
    benevolus_org_link: str = ""
    benevolus_token: str = ""
    rate_limit_seconds: int = 30
    verify_base_url: str = "https://abordajeux.github.io/presque/verify"
    max_body_bytes: int = 65536


def load_settings() -> Settings:
    cors_raw = os.environ.get("CORS_ORIGINS", "")
    print("HELLO ")
    print(cors_raw)
    return Settings(
        database_path=os.environ.get("DATABASE_PATH", "abordajeux.db"),
        programme_path=os.environ.get("PROGRAMME_PATH", "programme.json"),
        cors_origins=[
            origin.strip() for origin in cors_raw.split(",") if origin.strip()
        ],
        mail_api_key=os.environ.get("MAIL_API_KEY", ""),
        mail_sender=os.environ.get("MAIL_SENDER", ""),
        mail_contact_email=os.environ.get("MAIL_CONTACT_EMAIL", ""),
        mail_benevole_email=os.environ.get("MAIL_BENEVOLE_EMAIL", ""),
        benevolus_org_link=os.environ.get("BENEVOLUS_ORG_LINK", ""),
        benevolus_token=os.environ.get("BENEVOLUS_TOKEN", ""),
        rate_limit_seconds=int(os.environ.get("RATE_LIMIT_SECONDS", "30")),
        verify_base_url=os.environ.get(
            "VERIFY_BASE_URL", "https://abordajeux.github.io/presque/verify"),
        max_body_bytes=int(os.environ.get("MAX_BODY_BYTES", "65536")),
    )
