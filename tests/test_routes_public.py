import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dns.exception import DNSException

from app import db as db_mod
from app import email

_VALID_BODY = {
    "contact_email": "player@example.com",
    "participants": [{
        "name": "Alice"
    }, {
        "name": "Bob"
    }],
}

_INDIVIDUAL_BODY = {
    "contact_email": "player@example.com",
    "participants": [{
        "name": "Solo"
    }],
}


def _seed(application,
          activity_id: str = "a1",
          max_participants: int = 5,
          *,
          title: str = "D&D — La Mine de Phandelver",
          starts_at: str = "2026-11-14 10:00:00") -> None:
    conn = db_mod.connect(application.state.settings.database_path)
    conn.execute(
        "INSERT INTO activities (id, title, starts_at, max_participants) VALUES (?, ?, ?, ?)",
        (activity_id, title, starts_at, max_participants))
    conn.close()


def _signup_row(application,
                *,
                token: str,
                age: timedelta | None = None) -> None:
    now = datetime.now(UTC)
    created = (now - age).strftime(
        "%Y-%m-%d %H:%M:%S") if age else now.strftime("%Y-%m-%d %H:%M:%S")
    conn = db_mod.connect(application.state.settings.database_path)
    conn.execute(
        "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, "a1", "p@example.com", "Pat", token, None, created),
    )
    conn.close()


def _extract_token(calls: list[tuple]) -> str:
    _, content = calls[-1]
    return content.text.split("?token=")[1].split()[0]


def test_health(api) -> None:
    _, client, _ = api
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_activities_empty(api) -> None:
    _, client, _ = api
    response = client.get("/activities")
    assert response.status_code == 200
    assert response.json() == {"activities": []}


def test_get_activities_seeded(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 5)
    _seed(application, "a2", 3)
    response = client.get("/activities")
    body = response.json()
    assert response.status_code == 200
    by_id = {a["id"]: a for a in body["activities"]}
    assert by_id["a1"] == {
        "id": "a1",
        "max": 5,
        "confirmed": 0,
        "pending": 0,
        "waitlisted": 0
    }
    assert by_id["a2"]["max"] == 3


def test_get_activity_found(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 5)
    response = client.get("/activities/a1")
    assert response.status_code == 200
    assert response.json() == {
        "id": "a1",
        "max": 5,
        "confirmed": 0,
        "pending": 0,
        "waitlisted": 0
    }


def test_get_activity_not_found(api) -> None:
    _, client, _ = api
    response = client.get("/activities/ghost")
    assert response.status_code == 404
    assert response.json() == {"status": "not_found"}


def test_signup_ok_sends_email_and_reserves(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 5)

    response = client.post("/activities/a1/signup", json=_VALID_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "player@example.com" in body["message"]

    assert len(stub.calls) == 1
    to_email, content = stub.calls[0]
    assert to_email == "player@example.com"
    assert content.subject == email.SUBJECT
    assert "D&D — La Mine de Phandelver" in content.text
    assert "?token=" in content.text

    conn = db_mod.connect(application.state.settings.database_path)
    pending = conn.execute(
        "SELECT COUNT(*) FROM signups WHERE activity_id='a1' AND confirmed_at IS NULL"
    ).fetchone()[0]
    conn.close()
    assert pending == 2


def test_signup_capacity_exceeded(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 1)
    _signup_row(application, token="existing")

    response = client.post("/activities/a1/signup", json=_VALID_BODY)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "capacity_exceeded"
    assert (body["max"], body["confirmed"], body["pending"], body["available"],
            body["requested"]) == (
                1,
                0,
                1,
                0,
                2,
            )
    assert "message" in body


def test_signup_unknown_activity(api) -> None:
    _, client, _ = api
    response = client.post("/activities/ghost/signup", json=_VALID_BODY)
    assert response.status_code == 404
    assert response.json() == {"status": "not_found"}


def test_signup_rejects_eleven_participants(api) -> None:
    _, client, _ = api
    body = {
        "contact_email": "player@example.com",
        "participants": [{
            "name": f"P{i}"
        } for i in range(11)],
    }
    response = client.post("/activities/a1/signup", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_signup_rejects_overlong_participant_name(api) -> None:
    _, client, _ = api
    body = {
        "contact_email": "player@example.com",
        "participants": [{
            "name": "x" * 51
        }],
    }
    response = client.post("/activities/a1/signup", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_signup_allows_ten_participants(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 10)
    body = {
        "contact_email": "player@example.com",
        "participants": [{
            "name": f"P{i}"
        } for i in range(10)],
    }
    response = client.post("/activities/a1/signup", json=body)

    assert response.status_code == 200
    conn = db_mod.connect(application.state.settings.database_path)
    pending = conn.execute(
        "SELECT COUNT(*) FROM signups WHERE activity_id='a1' AND confirmed_at IS NULL"
    ).fetchone()[0]
    conn.close()
    assert pending == 10


def test_signup_rejected_when_waitlist_full(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 1)
    _signup_row(application, token="seated")
    _signup_row(application, token="waitlisted")

    response = client.post("/activities/a1/signup", json=_INDIVIDUAL_BODY)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "capacity_exceeded"
    assert body["requested"] == 1


def test_signup_invalid_mx(api, monkeypatch: pytest.MonkeyPatch) -> None:
    application, client, stub = api
    _seed(application, "a1", 5)

    def _fail(*args: object, **kwargs: object) -> None:
        raise DNSException("no mx")

    monkeypatch.setattr(email._resolver, "resolve", _fail)

    response = client.post("/activities/a1/signup", json=_VALID_BODY)
    assert response.status_code == 422
    assert response.json()["status"] == "invalid_email"
    assert stub.calls == []


def test_verify_confirmed(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 5)
    client.post("/activities/a1/signup", json=_VALID_BODY)
    token = _extract_token(stub.calls)

    response = client.post("/verify", json={"token": token})

    assert response.status_code == 200
    assert response.json() == {
        "status": "confirmed",
        "activity_id": "a1",
        "waitlisted": False
    }

    conn = db_mod.connect(application.state.settings.database_path)
    unconfirmed = conn.execute(
        "SELECT COUNT(*) FROM signups WHERE verification_token=? AND confirmed_at IS NULL",
        (token, )).fetchone()[0]
    conn.close()
    assert unconfirmed == 0


def test_verify_invalid_token(api) -> None:
    _, client, _ = api
    response = client.post("/verify", json={"token": "nope"})
    assert response.status_code == 404
    assert response.json() == {"status": "invalid_token"}


def test_verify_missing_body(api) -> None:
    _, client, _ = api
    response = client.post("/verify")
    assert response.status_code == 422
    assert "detail" in response.json()


def test_verify_expired(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 5)
    _signup_row(application, token="aged", age=timedelta(hours=25))

    response = client.post("/verify", json={"token": "aged"})
    assert response.status_code == 410
    assert response.json() == {"status": "expired"}


def test_verify_get_method_not_allowed(api) -> None:
    _, client, _ = api
    response = client.get("/verify")
    assert response.status_code == 405


def test_rate_limit_blocks_second_signup(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 5)

    first = client.post("/activities/a1/signup", json=_VALID_BODY)
    second = client.post("/activities/a1/signup", json=_VALID_BODY)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["status"] == "rate_limited"
    assert len(stub.calls) == 1


def test_rate_limit_keys_on_cf_connecting_ip(api) -> None:
    application, client, _ = api
    _seed(application, "a1", 5)

    first = client.post("/activities/a1/signup",
                        json=_VALID_BODY,
                        headers={"CF-Connecting-IP": "203.0.113.7"})
    second = client.post("/activities/a1/signup",
                         json=_INDIVIDUAL_BODY,
                         headers={"CF-Connecting-IP": "203.0.113.7"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_rate_limit_distinguishes_cf_connecting_ips(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 5)

    first = client.post("/activities/a1/signup",
                        json=_VALID_BODY,
                        headers={"CF-Connecting-IP": "203.0.113.7"})
    second = client.post("/activities/a1/signup",
                         json=_INDIVIDUAL_BODY,
                         headers={"CF-Connecting-IP": "198.51.100.9"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(stub.calls) == 2


def test_signup_full_individual_joins_waitlist(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 1)
    _signup_row(application, token="existing")

    response = client.post("/activities/a1/signup", json=_INDIVIDUAL_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["waitlisted"] is True
    assert "liste d'attente" in body["message"]

    assert len(stub.calls) == 1
    to_email, content = stub.calls[0]
    assert to_email == "player@example.com"
    assert content.subject == email.WAITLIST_SUBJECT
    assert "liste d'attente" in content.text
    assert "D&D — La Mine de Phandelver" in content.text
    assert "?token=" in content.text

    activity = client.get("/activities/a1").json()
    assert (activity["confirmed"], activity["pending"],
            activity["waitlisted"]) == (0, 1, 1)


def test_verify_waitlisted_flag(api) -> None:
    application, client, stub = api
    _seed(application, "a1", 1)
    _signup_row(application, token="existing")

    client.post("/activities/a1/signup", json=_INDIVIDUAL_BODY)
    token = _extract_token(stub.calls)

    response = client.post("/verify", json={"token": token})

    assert response.status_code == 200
    assert response.json() == {
        "status": "confirmed",
        "activity_id": "a1",
        "waitlisted": True
    }
