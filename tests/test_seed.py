import json
import sqlite3
from pathlib import Path

import pytest

from app import db as db_mod
from app import signups
from app.seed import ActivitySeed, load_programme, main, seed_activities

_FIXTURE = (Path(__file__).resolve().parent.parent / "fixtures" /
            "presque-programme.example.json")


def test_load_programme_reads_fixture() -> None:
    seeds = load_programme(_FIXTURE)

    assert len(seeds) == 3
    first = seeds[0]
    assert first.id == "presque-dnd-001"
    assert first.title == "Donjons & Dragons — La Mine de Phandelver"
    assert first.starts_at == "2026-11-14T10:00:00+01:00"
    assert first.max_participants == 5


def test_seed_idempotent_rerun_no_dupes(db: sqlite3.Connection) -> None:
    seeds = load_programme(_FIXTURE)

    assert seed_activities(db, seeds) == 3
    assert seed_activities(db, seeds) == 3
    count = db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    assert count == 3


def test_seed_updates_max_without_losing_signups(
        db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO activities (id, title, starts_at, max_participants) "
        "VALUES ('presque-dnd-001', 'Old', '2026-11-14 10:00:00', 5)")
    signups.reserve_signups(db,
                            "presque-dnd-001",
                            "p@example.com", ["Alice"],
                            verification_token="t1")
    seeds = [
        ActivitySeed(id="presque-dnd-001",
                     title="Donjons & Dragons — La Mine de Phandelver",
                     starts_at="2026-11-14T10:00:00+01:00",
                     max_participants=8)
    ]

    seed_activities(db, seeds)

    row = db.execute(
        "SELECT title, max_participants FROM activities "
        "WHERE id = 'presque-dnd-001'").fetchone()
    assert row is not None
    assert row["title"] == "Donjons & Dragons — La Mine de Phandelver"
    assert row["max_participants"] == 8
    state = signups.get_activity_signups(db, "presque-dnd-001")
    assert state is not None
    assert state.pending == 1
    assert state.available == 7


def test_seed_tolerates_extra_fields(tmp_path) -> None:
    path = tmp_path / "programme.json"
    path.write_text(
        json.dumps({
            "activities": [{
                "id": "x",
                "title": "T",
                "start": "2026-11-14T10:00:00+01:00",
                "max_participants": 4,
                "room": "Scene",
                "description": "d",
            }]
        }),
        encoding="utf-8")

    seeds = load_programme(path)

    assert len(seeds) == 1
    assert seeds[0].id == "x"


def test_seed_missing_required_field_raises(tmp_path) -> None:
    path = tmp_path / "programme.json"
    path.write_text(json.dumps({"activities": [{
        "id": "x",
        "title": "T"
    }]}),
                    encoding="utf-8")

    with pytest.raises(ValueError):
        load_programme(path)


def test_seed_main_seeds_database(tmp_path, monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture) -> None:
    db_path = tmp_path / "seed.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    assert main(["app.seed", str(_FIXTURE)]) == 0

    assert "seeded 3 activities" in capsys.readouterr().out
    conn = db_mod.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    conn.close()
    assert count == 3


def test_seed_main_defaults_to_programme_path(
        tmp_path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    db_path = tmp_path / "seed.db"
    programme_path = tmp_path / "programme.json"
    programme_path.write_text(_FIXTURE.read_text(encoding="utf-8"),
                              encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("PROGRAMME_PATH", str(programme_path))

    assert main(["app.seed"]) == 0

    assert "seeded 3 activities" in capsys.readouterr().out
    conn = db_mod.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    conn.close()
    assert count == 3
