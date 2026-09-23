import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from app import db as db_mod
from app import signups
from app.purge import main, purge_expired


def seed_activity(conn: sqlite3.Connection,
                  activity_id: str = "a1",
                  max_participants: int = 5) -> None:
    conn.execute(
        "INSERT INTO activities (id, title, starts_at, max_participants) VALUES (?, ?, ?, ?)",
        (activity_id, "Atelier de jeux", "2026-11-14 10:00:00",
         max_participants),
    )


def insert_signup(
    conn: sqlite3.Connection,
    activity_id: str,
    *,
    name: str,
    token: str,
    confirmed: bool = False,
    age: timedelta | None = None,
) -> None:
    now = datetime.now(UTC)
    created = (now - age).strftime(
        "%Y-%m-%d %H:%M:%S") if age is not None else now.strftime(
            "%Y-%m-%d %H:%M:%S")
    confirmed_at = now.strftime("%Y-%m-%d %H:%M:%S") if confirmed else None
    conn.execute(
        "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, activity_id, f"{name.lower()}@example.com", name,
         token, confirmed_at, created),
    )


def test_purge_deletes_only_expired_unconfirmed(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="AgedPending", token="t1",
                  age=timedelta(hours=25))
    insert_signup(db, "a1", name="FreshPending", token="t2")
    insert_signup(db, "a1", name="AgedConfirmed", token="t3", confirmed=True,
                  age=timedelta(hours=30))

    deleted = purge_expired(db)

    assert deleted == 1
    names = {
        row["participant_name"]
        for row in db.execute("SELECT participant_name FROM signups")
    }
    assert names == {"FreshPending", "AgedConfirmed"}
    state = signups.get_activity_signups(db, "a1")
    assert state is not None
    assert state.pending == 1


def test_purge_main_runs_end_to_end(tmp_path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "purge.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    conn = db_mod.connect(db_path)
    db_mod.init_schema(conn)
    seed_activity(conn)
    insert_signup(conn, "a1", name="AgedPending", token="t1",
                  age=timedelta(hours=25))
    conn.close()

    assert main() == 0

    out = capsys.readouterr().out
    assert "purged 1 expired signups" in out
    assert "promoted 0 waitlisted signups" in out
    conn = db_mod.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM signups").fetchone()[0]
    conn.close()
    assert count == 0
