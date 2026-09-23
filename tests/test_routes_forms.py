from app import db as db_mod

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
