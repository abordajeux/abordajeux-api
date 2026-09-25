import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

_FIXTURE = (Path(__file__).resolve().parent.parent / "fixtures" /
            "presque-programme.example.json")

_PROGRAMME = {
    "activities": [{
        "id": "presque-dnd-001",
        "title": "Donjons & Dragons — La Mine de Phandelver",
        "room": "JDR Cheminee 1",
        "start": "2026-11-14T10:00:00+01:00",
        "end": "2026-11-14T14:00:00+01:00",
        "max_participants": 5,
    }],
    "rooms": ["JDR Cheminee 1"],
}


def _programme_file(application) -> Path:
    return Path(application.state.settings.programme_path)


def test_schedule_serves_file_verbatim(api) -> None:
    application, client, _ = api
    path = _programme_file(application)
    raw = json.dumps(_PROGRAMME, indent=2)
    path.write_text(raw, encoding="utf-8")

    response = client.get("/schedule")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.content == raw.encode("utf-8")
    body = response.json()
    assert body["activities"][0]["id"] == "presque-dnd-001"
    assert body["rooms"] == ["JDR Cheminee 1"]


def test_schedule_missing_file(api) -> None:
    _, client, _ = api

    response = client.get("/schedule")

    assert response.status_code == 404
    assert response.json() == {"status": "schedule_missing"}


def test_schedule_invalid_json(api) -> None:
    application, client, _ = api
    _programme_file(application).write_text("{not json",
                                            encoding="utf-8")

    response = client.get("/schedule")

    assert response.status_code == 500
    assert response.json() == {"status": "schedule_invalid"}


def _make_client(tmp_path: Path, *, programme_text: str) -> TestClient:
    programme_path = tmp_path / "programme.json"
    programme_path.write_text(programme_text, encoding="utf-8")
    settings = Settings(
        database_path=str(tmp_path / "t.db"),
        programme_path=str(programme_path),
        cors_origins=["https://test.local"],
        mail_api_key="key-123",
        mail_sender="noreply@test.local",
        mail_contact_email="contact@test.local",
    )
    application = create_app(settings)
    return TestClient(application)


def test_startup_seeds_from_programme_file(tmp_path: Path) -> None:
    fixture_text = _FIXTURE.read_text(encoding="utf-8")

    with _make_client(tmp_path, programme_text=fixture_text) as client:
        activities = client.get("/activities").json()["activities"]
        assert {a["id"] for a in activities} == {
            "presque-dnd-001",
            "presque-jds-002",
            "presque-tournoi-003",
        }
        assert client.get("/schedule").status_code == 200


def test_startup_malformed_programme_does_not_crash(
        tmp_path: Path) -> None:
    with _make_client(tmp_path, programme_text="{not json") as client:
        assert client.get("/health").status_code == 200

        response = client.get("/schedule")

        assert response.status_code == 500
        assert response.json() == {"status": "schedule_invalid"}
        assert client.get("/activities").json() == {"activities": []}
