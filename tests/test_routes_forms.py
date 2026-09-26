import pytest
from dns.exception import DNSException
from fastapi.testclient import TestClient

from app import db as db_mod
from app import email
from app.config import Settings
from app.email import EmailContent
from app.main import create_app, get_mail_sender

_CONTACT_BODY = {
    "subject": "Question sur les Presques 24h",
    "sender_email": "visitor@example.com",
    "message": "Bonjour,\nEst-ce que le programme est définitif ?",
}

_FEEDBACK_BODY = {
    "event": "Soirée jeu du mercredi",
    "sender_email": "visitor@example.com",
    "message": "Super soirée, merci !",
    "planning_rating": 4,
    "welcome_rating": 5,
}

_BENEVOLE_BODY = {
    "sender_email": "visitor@example.com",
}


def test_contact_form_ok_sends_to_association_with_reply_to(api) -> None:
    _, client, stub = api

    response = client.post("/forms/contact", json=_CONTACT_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "envoyé" in body["message"]

    assert len(stub.calls) == 1
    to_email, content, reply_to = stub.calls[0]
    assert to_email == "contact@test.local"
    assert reply_to == "visitor@example.com"
    assert content.subject == "Formulaire de contact — Question sur les Presques 24h"
    assert "Est-ce que le programme est définitif ?" in content.text


def test_feedback_form_ok_sends_to_association_with_reply_to(api) -> None:
    _, client, stub = api

    response = client.post("/forms/feedback", json=_FEEDBACK_BODY)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert len(stub.calls) == 1
    to_email, content, reply_to = stub.calls[0]
    assert to_email == "contact@test.local"
    assert reply_to == "visitor@example.com"
    assert content.subject == "Retour sur un événement — Soirée jeu du mercredi"
    assert "Accueil : 5/5" in content.text
    assert "Organisation : 4/5" in content.text


def test_contact_form_rejects_invalid_email(api) -> None:
    _, client, stub = api

    response = client.post(
        "/forms/contact",
        json={**_CONTACT_BODY, "sender_email": "not-an-email"})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert stub.calls == []


def test_contact_form_rejects_missing_fields(api) -> None:
    _, client, _ = api

    response = client.post("/forms/contact", json={"subject": "Bonjour"})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_contact_form_rejects_overlong_message(api) -> None:
    _, client, _ = api

    response = client.post(
        "/forms/contact",
        json={**_CONTACT_BODY, "message": "x" * 5001})

    assert response.status_code == 422


def test_feedback_form_rejects_out_of_range_rating(api) -> None:
    _, client, _ = api

    response = client.post(
        "/forms/feedback",
        json={**_FEEDBACK_BODY, "welcome_rating": 6})

    assert response.status_code == 422


def test_contact_form_neutralizes_header_injection(api) -> None:
    _, client, stub = api

    response = client.post(
        "/forms/contact",
        json={**_CONTACT_BODY, "subject": "Bonjour\r\nBcc: evil@example.com"})

    assert response.status_code == 200
    _, content, _ = stub.calls[0]
    assert "\r" not in content.subject
    assert "\n" not in content.subject
    assert "Bcc:" in content.subject


def test_rate_limit_blocks_second_contact_form(api) -> None:
    _, client, stub = api

    first = client.post("/forms/contact", json=_CONTACT_BODY)
    second = client.post("/forms/contact", json=_CONTACT_BODY)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["status"] == "rate_limited"
    assert len(stub.calls) == 1


def test_rate_limit_independent_per_form(api) -> None:
    _, client, stub = api

    contact = client.post("/forms/contact", json=_CONTACT_BODY)
    feedback = client.post("/forms/feedback", json=_FEEDBACK_BODY)

    assert contact.status_code == 200
    assert feedback.status_code == 200
    assert len(stub.calls) == 2


def test_signup_and_contact_rate_limits_independent(api) -> None:
    application, client, stub = api
    conn = db_mod.connect(application.state.settings.database_path)
    conn.execute(
        "INSERT INTO activities (id, title, starts_at, max_participants) "
        "VALUES ('a1', 'D&D', '2026-11-14 10:00:00', 5)")
    conn.close()

    signup = client.post(
        "/activities/a1/signup",
        json={
            "contact_email": "player@example.com",
            "participants": [{"name": "Solo"}],
        })
    contact = client.post("/forms/contact", json=_CONTACT_BODY)

    assert signup.status_code == 200
    assert contact.status_code == 200
    assert len(stub.calls) == 2


def test_benevole_form_ok_sends_welcome_and_notification(api) -> None:
    _, client, stub = api

    response = client.post("/forms/benevole", json=_BENEVOLE_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "visitor@example.com" in body["message"]

    assert len(stub.calls) == 2
    welcome_to, welcome_content, welcome_reply_to = stub.calls[0]
    assert welcome_to == "visitor@example.com"
    assert welcome_reply_to == "benevoles@test.local"
    assert welcome_content.subject == "Devenir bénévole — À L'Abordajeux"
    assert "TODO: MAIL CONTENT FOR JOINING PROCEDURE" in welcome_content.text
    assert "https://app.benevolus.ch/rejoindre/test-org" in welcome_content.text
    assert "tok-123" in welcome_content.text
    assert "https://app.benevolus.ch/rejoindre/test-org" in welcome_content.html
    assert "tok-123" in welcome_content.html

    notification_to, notification_content, notification_reply_to = stub.calls[1]
    assert notification_to == "benevoles@test.local"
    assert notification_reply_to == "visitor@example.com"
    assert notification_content.subject == (
        "Nouvelle proposition de bénévolat — visitor@example.com")
    assert "visitor@example.com" in notification_content.text


def test_benevole_form_rejects_invalid_email(api) -> None:
    _, client, stub = api

    response = client.post(
        "/forms/benevole",
        json={"sender_email": "not-an-email"})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert stub.calls == []


def test_benevole_form_rejects_missing_fields(api) -> None:
    _, client, stub = api

    response = client.post("/forms/benevole", json={})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert stub.calls == []


def test_benevole_form_rejects_invalid_mx(api, monkeypatch: pytest.MonkeyPatch) -> None:
    _, client, stub = api

    def _fail(*args: object, **kwargs: object) -> None:
        raise DNSException("no mx")

    monkeypatch.setattr(email._resolver, "resolve", _fail)

    response = client.post("/forms/benevole", json=_BENEVOLE_BODY)

    assert response.status_code == 422
    assert response.json()["status"] == "invalid_email"
    assert stub.calls == []


def test_rate_limit_blocks_second_benevole_form(api) -> None:
    _, client, stub = api

    first = client.post("/forms/benevole", json=_BENEVOLE_BODY)
    second = client.post("/forms/benevole", json=_BENEVOLE_BODY)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["status"] == "rate_limited"
    assert len(stub.calls) == 2


def test_benevole_and_contact_rate_limits_independent(api) -> None:
    _, client, stub = api

    benevole = client.post("/forms/benevole", json=_BENEVOLE_BODY)
    contact = client.post("/forms/contact", json=_CONTACT_BODY)

    assert benevole.status_code == 200
    assert contact.status_code == 200
    assert len(stub.calls) == 3


class _RecordingSender:

    def __init__(self) -> None:
        self.calls: list[tuple[str, EmailContent, str | None]] = []

    def send(self,
             *,
             to_email: str,
             content: EmailContent,
             reply_to: str | None = None) -> None:
        self.calls.append((to_email, content, reply_to))


def test_benevole_notification_falls_back_to_contact_email(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "t.db"),
        programme_path=str(tmp_path / "programme.json"),
        cors_origins=["https://test.local"],
        mail_api_key="key-123",
        mail_sender="noreply@test.local",
        mail_contact_email="contact@test.local",
    )
    application = create_app(settings)
    stub = _RecordingSender()
    application.dependency_overrides[get_mail_sender] = lambda: stub

    with TestClient(application) as client:
        response = client.post("/forms/benevole", json=_BENEVOLE_BODY)

    assert response.status_code == 200
    to_emails = [to_email for to_email, _, _ in stub.calls]
    assert to_emails == ["visitor@example.com", "contact@test.local"]
    assert stub.calls[0][2] == "contact@test.local"
    assert stub.calls[1][2] == "visitor@example.com"
