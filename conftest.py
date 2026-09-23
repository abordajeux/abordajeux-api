import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db as db_mod
from app.config import Settings
from app.email import EmailContent
from app.main import create_app, get_mail_sender


@pytest.fixture()
def db() -> Iterator[sqlite3.Connection]:
    conn = db_mod.connect(":memory:")
    db_mod.init_schema(conn)
    yield conn
    conn.close()


class _StubSender:

    def __init__(self) -> None:
        self.calls: list[tuple[str, EmailContent]] = []

    def send(self, *, to_email: str, content: EmailContent) -> None:
        self.calls.append((to_email, content))


@pytest.fixture()
def api(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "t.db"),
        cors_origins=["https://test.local"],
        mail_api_key="key-123",
        mail_sender="noreply@test.local",
        mail_contact_email="contact@test.local",
        rate_limit_seconds=30,
        verify_base_url="https://test.local/verify",
    )
    application = create_app(settings)
    stub = _StubSender()
    application.dependency_overrides[get_mail_sender] = lambda: stub
    with TestClient(application) as client:
        yield application, client, stub
