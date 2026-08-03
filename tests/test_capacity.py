import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import capacity as cap


def seed_activity(conn: sqlite3.Connection, activity_id: str = "a1", max_participants: int = 5) -> None:
    conn.execute(
        "INSERT INTO activities (id, max_participants) VALUES (?, ?)",
        (activity_id, max_participants),
    )


def insert_signup(
    conn: sqlite3.Connection,
    activity_id: str,
    *,
    email: str = "p@example.com",
    name: str = "Pat",
    token: str = "tok",
    confirmed: bool = False,
    age: timedelta | None = None,
) -> None:
    now = datetime.now(UTC)
    created = (now - age).strftime("%Y-%m-%d %H:%M:%S") if age is not None else now.strftime("%Y-%m-%d %H:%M:%S")
    confirmed_at = now.strftime("%Y-%m-%d %H:%M:%S") if confirmed else None
    conn.execute(
        "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, activity_id, email, name, token, confirmed_at, created),
    )


def test_get_activity_signups_zero_signups(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    result = cap.get_activity_signups(db, "a1")

    assert result == cap.ActivitySignups(id="a1", max=5, confirmed=0, pending=0)
    assert result is not None and result.available == 5


def test_get_activity_signups_missing_activity_is_none(db: sqlite3.Connection) -> None:
    assert cap.get_activity_signups(db, "nope") is None


def test_get_all_activity_signups(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    seed_activity(db, "a2", 3)
    per_activity = {c.id: c for c in cap.get_all_activity_signups(db)}

    assert set(per_activity) == {"a1", "a2"}
    assert per_activity["a1"].max == 5
    assert per_activity["a2"].available == 3


def test_reserve_ok(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    result = cap.reserve_signups(db, "a1", "p@example.com", ["Alice", "Bob"], verification_token="t1")

    assert result.ok is True
    assert result.requested == 2
    after = cap.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending) == (0, 2)
    assert after.available == 3


def test_reserve_exact_fit(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    result = cap.reserve_signups(db, "a1", "p@example.com", ["Alice", "Bob"], verification_token="t1")

    assert result.ok is True
    after = cap.get_activity_signups(db, "a1")
    assert after is not None and after.available == 0


def test_reserve_exceeds_rolls_back_and_reports_counts(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 3)
    insert_signup(db, "a1", name="Confirmed", confirmed=True)
    insert_signup(db, "a1", name="Pending")

    result = cap.reserve_signups(db, "a1", "p@example.com", ["X", "Y"], verification_token="t2")

    assert result.ok is False
    assert result.requested == 2
    assert (result.signups.max, result.signups.confirmed, result.signups.pending) == (3, 1, 1)
    assert result.signups.available == 1

    after = cap.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending) == (1, 1)


def test_reserve_unknown_activity_raises(db: sqlite3.Connection) -> None:
    with pytest.raises(cap.ActivityNotFound):
        cap.reserve_signups(db, "ghost", "p@example.com", ["X"], verification_token="t")


def test_reserve_empty_participants_rejected(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    with pytest.raises(ValueError):
        cap.reserve_signups(db, "a1", "p@example.com", [], verification_token="t")


def test_aged_pending_not_counted_but_fresh_is(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="OldPending", age=timedelta(hours=25))
    insert_signup(db, "a1", name="FreshPending", age=timedelta(minutes=5))

    result = cap.get_activity_signups(db, "a1")
    assert result is not None
    assert (result.confirmed, result.pending) == (0, 1)
    assert result.available == 4


def test_confirmed_counts(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="Confirmed", confirmed=True)

    result = cap.get_activity_signups(db, "a1")
    assert result is not None
    assert (result.confirmed, result.pending) == (1, 0)


def test_reserve_shares_token_across_batch(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    cap.reserve_signups(db, "a1", "p@example.com", ["Alice", "Bob"], verification_token="shared")

    rows = db.execute("SELECT verification_token FROM signups WHERE activity_id = 'a1'").fetchall()
    assert len(rows) == 2
    assert {row["verification_token"] for row in rows} == {"shared"}
