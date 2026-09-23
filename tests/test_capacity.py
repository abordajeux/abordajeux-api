import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import signups


def seed_activity(
    conn: sqlite3.Connection,
    activity_id: str = "a1",
    max_participants: int = 5,
    *,
    title: str = "Atelier de jeux",
    starts_at: str = "2026-11-14 10:00:00",
) -> None:
    conn.execute(
        "INSERT INTO activities (id, title, starts_at, max_participants) VALUES (?, ?, ?, ?)",
        (activity_id, title, starts_at, max_participants),
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
    created = (now - age).strftime(
        "%Y-%m-%d %H:%M:%S") if age is not None else now.strftime(
            "%Y-%m-%d %H:%M:%S")
    confirmed_at = now.strftime("%Y-%m-%d %H:%M:%S") if confirmed else None
    conn.execute(
        "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, activity_id, email, name, token, confirmed_at,
         created),
    )


def expire_and_delete(conn: sqlite3.Connection, token: str) -> None:
    conn.execute(
        "UPDATE signups SET created_at = datetime('now', '-25 hours') "
        "WHERE verification_token = ?", (token, ))
    conn.execute("DELETE FROM signups WHERE verification_token = ?",
                 (token, ))


def test_get_activity_signups_zero_signups(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    result = signups.get_activity_signups(db, "a1")

    assert result == signups.ActivitySignups(id="a1",
                                             max=5,
                                             confirmed=0,
                                             pending=0,
                                             waitlisted=0)
    assert result is not None and result.available == 5


def test_get_activity_signups_missing_activity_is_none(
        db: sqlite3.Connection) -> None:
    assert signups.get_activity_signups(db, "nope") is None


def test_get_all_activity_signups(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    seed_activity(db, "a2", 3)
    per_activity = {c.id: c for c in signups.get_all_activity_signups(db)}

    assert set(per_activity) == {"a1", "a2"}
    assert per_activity["a1"].max == 5
    assert per_activity["a2"].available == 3


def test_reserve_ok(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    result = signups.reserve_signups(db,
                                     "a1",
                                     "p@example.com", ["Alice", "Bob"],
                                     verification_token="t1")

    assert result.ok is True
    assert result.requested == 2
    assert result.waitlisted is False
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending) == (0, 2)
    assert after.available == 3


def test_reserve_returns_activity_display_fields(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5,
                  title="D&D — La Mine de Phandelver",
                  starts_at="2026-11-14T10:00:00")
    result = signups.reserve_signups(db,
                                     "a1",
                                     "p@example.com", ["Alice"],
                                     verification_token="t1")

    assert result.activity_title == "D&D — La Mine de Phandelver"
    assert result.activity_starts_at == datetime(2026, 11, 14, 10, 0)


def test_reserve_exact_fit(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    result = signups.reserve_signups(db,
                                     "a1",
                                     "p@example.com", ["Alice", "Bob"],
                                     verification_token="t1")

    assert result.ok is True
    after = signups.get_activity_signups(db, "a1")
    assert after is not None and after.available == 0


def test_reserve_exceeds_rolls_back_and_reports_counts(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 3)
    insert_signup(db, "a1", name="Confirmed", confirmed=True)
    insert_signup(db, "a1", name="Pending")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "p@example.com", ["X", "Y"],
                                     verification_token="t2")

    assert result.ok is False
    assert result.requested == 2
    assert (result.signups.max, result.signups.confirmed,
            result.signups.pending,
            result.signups.waitlisted) == (3, 1, 1, 0)
    assert result.signups.available == 1

    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending) == (1, 1)


def test_reserve_unknown_activity_raises(db: sqlite3.Connection) -> None:
    with pytest.raises(signups.ActivityNotFound):
        signups.reserve_signups(db,
                                "ghost",
                                "p@example.com", ["X"],
                                verification_token="t")


def test_reserve_empty_participants_rejected(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    with pytest.raises(ValueError):
        signups.reserve_signups(db,
                                "a1",
                                "p@example.com", [],
                                verification_token="t")


def test_aged_pending_not_counted_but_fresh_is(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="OldPending", age=timedelta(hours=25))
    insert_signup(db, "a1", name="FreshPending", age=timedelta(minutes=5))

    result = signups.get_activity_signups(db, "a1")
    assert result is not None
    assert (result.confirmed, result.pending, result.waitlisted) == (0, 1, 0)
    assert result.available == 4


def test_confirmed_counts(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="Confirmed", confirmed=True)

    result = signups.get_activity_signups(db, "a1")
    assert result is not None
    assert (result.confirmed, result.pending) == (1, 0)


def test_view_splits_seated_confirmed_pending_and_overflow(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    insert_signup(db, "a1", name="C1", confirmed=True)
    insert_signup(db, "a1", name="P1")
    insert_signup(db, "a1", name="P2")
    insert_signup(db, "a1", name="C2", confirmed=True)

    result = signups.get_activity_signups(db, "a1")
    assert result is not None
    assert (result.confirmed, result.pending, result.waitlisted) == (1, 1, 2)
    assert result.total_active == 4
    assert result.available == 0


def test_reserve_shares_token_across_batch(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    signups.reserve_signups(db,
                            "a1",
                            "p@example.com", ["Alice", "Bob"],
                            verification_token="shared")

    rows = db.execute(
        "SELECT verification_token FROM signups WHERE activity_id = 'a1'"
    ).fetchall()
    assert len(rows) == 2
    assert {row["verification_token"] for row in rows} == {"shared"}


def test_reserve_individual_overflow_joins_waitlist(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    insert_signup(db, "a1", name="First")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "w@example.com", ["Wait"],
                                     verification_token="tw")

    assert result.ok is True
    assert result.waitlisted is True
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending, after.waitlisted) == (0, 1, 1)
    assert after.available == 0


def test_reserve_group_overflow_with_queue_rejected(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    insert_signup(db, "a1", name="First")
    insert_signup(db, "a1", name="Queued")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "g@example.com", ["A", "B"],
                                     verification_token="tg")

    assert result.ok is False
    assert result.waitlisted is False


def test_reserve_fills_waitlist_up_to_capacity_limit(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    insert_signup(db, "a1", name="S1", token="t1")
    insert_signup(db, "a1", name="S2", token="t2")
    insert_signup(db, "a1", name="W1", token="t3")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "w2@example.com", ["W2"],
                                     verification_token="t4")

    assert result.ok is True
    assert result.waitlisted is True
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending, after.waitlisted) == (0, 2, 2)
    assert after.waitlisted == 2
    rows = db.execute("SELECT COUNT(*) FROM signups").fetchone()[0]
    assert rows == 4


def test_reserve_rejected_when_waitlist_full(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    insert_signup(db, "a1", name="Seated", token="t1")
    insert_signup(db, "a1", name="Wait1", token="t2")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "late@example.com", ["Late"],
                                     verification_token="t3")

    assert result.ok is False
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert after.total_active == 2
    assert after.waitlisted == 1
    rows = db.execute("SELECT COUNT(*) FROM signups").fetchone()[0]
    assert rows == 2


def test_reserve_waitlist_boundary_matches_max(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    insert_signup(db, "a1", name="S1", token="t1")
    insert_signup(db, "a1", name="S2", token="t2")
    insert_signup(db, "a1", name="W1", token="t3")
    insert_signup(db, "a1", name="W2", token="t4")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "late@example.com", ["Late"],
                                     verification_token="t5")

    assert result.ok is False
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert after.waitlisted == 2


def test_newcomer_cannot_jump_pending_waitlisted(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    insert_signup(db, "a1", name="AgedSeated", token="t1",
                  age=timedelta(hours=25))
    insert_signup(db, "a1", name="EarlyQueued", token="t2")

    result = signups.reserve_signups(db,
                                     "a1",
                                     "new@example.com", ["New"],
                                     verification_token="t3")

    assert result.ok is True
    assert result.waitlisted is True
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending, after.waitlisted) == (0, 1, 1)


def test_newcomer_cannot_jump_confirmed_waitlisted(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    insert_signup(db, "a1", name="AgedSeated", token="t1",
                  age=timedelta(hours=25))
    insert_signup(db, "a1", name="EarlyQueued", token="t2", confirmed=True)

    result = signups.reserve_signups(db,
                                     "a1",
                                     "new@example.com", ["New"],
                                     verification_token="t3")

    assert result.ok is True
    assert result.waitlisted is True
    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending, after.waitlisted) == (1, 0, 1)


def test_confirm_invalid_token(db: sqlite3.Connection) -> None:
    outcome = signups.confirm_by_token(db, "nope")
    assert outcome.status == "invalid_token"
    assert outcome.activity_id is None


def test_confirm_confirms_fresh_pending(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    signups.reserve_signups(db,
                            "a1",
                            "p@example.com", ["Alice", "Bob"],
                            verification_token="tok")

    outcome = signups.confirm_by_token(db, "tok")

    assert outcome.status == "confirmed"
    assert outcome.activity_id == "a1"
    assert outcome.waitlisted is False
    rows = db.execute(
        "SELECT confirmed_at FROM signups WHERE verification_token = 'tok'"
    ).fetchall()
    assert len(rows) == 2
    assert all(row["confirmed_at"] is not None for row in rows)


def test_confirm_idempotent_when_already_confirmed(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="Alice", token="tok", confirmed=True)

    outcome = signups.confirm_by_token(db, "tok")

    assert outcome.status == "confirmed"
    assert outcome.activity_id == "a1"


def test_confirm_expired_when_all_aged_and_unconfirmed(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="Late", token="tok", age=timedelta(hours=25))

    outcome = signups.confirm_by_token(db, "tok")

    assert outcome.status == "expired"
    assert outcome.activity_id == "a1"
    row = db.execute(
        "SELECT confirmed_at FROM signups WHERE verification_token = 'tok'"
    ).fetchone()
    assert row is not None and row["confirmed_at"] is None


def test_confirm_seated_sets_promotion_marker(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)
    insert_signup(db, "a1", name="Alice", token="t1")

    outcome = signups.confirm_by_token(db, "t1")

    assert outcome.status == "confirmed"
    assert outcome.waitlisted is False
    row = db.execute(
        "SELECT promoted_at FROM signups WHERE verification_token = 't1'"
    ).fetchone()
    assert row is not None and row["promoted_at"] is not None
    report = signups.promote_waitlisted(db, lambda p: None)
    assert report.promoted == []
    assert report.failed == []


def test_confirm_waitlisted_owes_promotion_email(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    insert_signup(db, "a1", name="First", token="t1")
    insert_signup(db, "a1", name="Queued", token="t2")

    outcome = signups.confirm_by_token(db, "t2")

    assert outcome.status == "confirmed"
    assert outcome.waitlisted is True
    row = db.execute(
        "SELECT promoted_at FROM signups WHERE verification_token = 't2'"
    ).fetchone()
    assert row is not None and row["promoted_at"] is None


def test_promotion_fifo_after_max_increase(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.confirm_by_token(db, "t1")
    signups.reserve_signups(db, "a1", "q1@example.com", ["Q1"],
                            verification_token="t2")
    signups.confirm_by_token(db, "t2")
    signups.reserve_signups(db, "a1", "q2@example.com", ["Q2"],
                            verification_token="t3")
    signups.confirm_by_token(db, "t3")
    signups.reserve_signups(db, "a1", "q3@example.com", ["Q3"],
                            verification_token="t4")
    signups.confirm_by_token(db, "t4")

    assert signups.promote_waitlisted(db, lambda p: None).promoted == []

    db.execute("UPDATE activities SET max_participants = 3 WHERE id = 'a1'")

    sent: list[signups.Promotion] = []
    report = signups.promote_waitlisted(db, sent.append)
    assert [(p.contact_email, p.participant_name)
            for p in report.promoted] == [("q2@example.com", "Q2")]
    assert report.failed == []
    assert [p.contact_email for p in sent] == ["q2@example.com"]
    assert report.promoted[0].activity_id == "a1"
    assert report.promoted[0].activity_title == "Atelier de jeux"
    assert report.promoted[0].activity_starts_at == datetime(2026, 11, 14, 10,
                                                             0)

    assert signups.promote_waitlisted(db, sent.append).promoted == []

    after = signups.get_activity_signups(db, "a1")
    assert after is not None
    assert (after.confirmed, after.pending, after.waitlisted) == (3, 0, 1)


def test_promotion_partial_fewer_seats_than_queue(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.confirm_by_token(db, "t1")
    for token, name in (("t2", "Q1"), ("t3", "Q2"), ("t4", "Q3")):
        signups.reserve_signups(db, "a1", f"{name.lower()}@example.com",
                                [name], verification_token=token)
        signups.confirm_by_token(db, token)

    db.execute("UPDATE activities SET max_participants = 3 WHERE id = 'a1'")

    report = signups.promote_waitlisted(db, lambda p: None)
    assert [p.participant_name for p in report.promoted] == ["Q2"]
    assert signups.promote_waitlisted(db, lambda p: None).promoted == []


def test_promotion_after_expiry_delete(db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.reserve_signups(db, "a1", "q@example.com", ["Q"],
                            verification_token="t2")
    outcome = signups.confirm_by_token(db, "t2")
    assert outcome.waitlisted is True

    expire_and_delete(db, "t1")

    report = signups.promote_waitlisted(db, lambda p: None)
    assert [p.participant_name for p in report.promoted] == ["Q"]
    assert [p.contact_email for p in report.promoted] == ["q@example.com"]
    assert signups.promote_waitlisted(db, lambda p: None).promoted == []


def test_seat_freed_before_confirm_owes_no_promotion_email(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.reserve_signups(db, "a1", "q@example.com", ["Q"],
                            verification_token="t2")

    expire_and_delete(db, "t1")

    outcome = signups.confirm_by_token(db, "t2")
    assert outcome.status == "confirmed"
    assert outcome.waitlisted is False
    row = db.execute(
        "SELECT promoted_at FROM signups WHERE verification_token = 't2'"
    ).fetchone()
    assert row is not None and row["promoted_at"] is not None
    report = signups.promote_waitlisted(db, lambda p: None)
    assert report.promoted == []
    assert report.failed == []


def test_promotion_send_failure_keeps_marker_and_retries(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 1)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.confirm_by_token(db, "t1")
    signups.reserve_signups(db, "a1", "q@example.com", ["Q"],
                            verification_token="t2")
    signups.confirm_by_token(db, "t2")

    db.execute("UPDATE activities SET max_participants = 2 WHERE id = 'a1'")

    def _fail(promotion: signups.Promotion) -> None:
        raise RuntimeError("provider down")

    failed_run = signups.promote_waitlisted(db, _fail)
    assert [p.participant_name for p in failed_run.failed] == ["Q"]
    assert failed_run.promoted == []
    row = db.execute(
        "SELECT promoted_at FROM signups WHERE verification_token = 't2'"
    ).fetchone()
    assert row is not None and row["promoted_at"] is None
    after = signups.get_activity_signups(db, "a1")
    assert after is not None and after.confirmed == 2

    sent: list[signups.Promotion] = []
    retried = signups.promote_waitlisted(db, sent.append)
    assert [p.participant_name for p in retried.promoted] == ["Q"]
    assert [p.contact_email for p in sent] == ["q@example.com"]


def test_promotion_send_failure_does_not_block_later_candidates(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    signups.reserve_signups(db, "a1", "first@example.com", ["First"],
                            verification_token="t1")
    signups.confirm_by_token(db, "t1")
    for token, name in (("t2", "Q1"), ("t3", "Q2"), ("t4", "Q3")):
        signups.reserve_signups(db, "a1", f"{name.lower()}@example.com",
                                [name], verification_token=token)
        signups.confirm_by_token(db, token)

    db.execute("UPDATE activities SET max_participants = 4 WHERE id = 'a1'")

    def _fail_first(promotion: signups.Promotion) -> None:
        if promotion.participant_name == "Q2":
            raise RuntimeError("provider down")

    report = signups.promote_waitlisted(db, _fail_first)
    assert [p.participant_name for p in report.failed] == ["Q2"]
    assert [p.participant_name for p in report.promoted] == ["Q3"]
    markers = dict(
        db.execute("SELECT participant_name, promoted_at FROM signups "
                   "WHERE participant_name IN ('Q2', 'Q3')").fetchall())
    assert markers["Q2"] is None
    assert markers["Q3"] is not None


def test_get_admin_activities_groups_participants(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 2)
    insert_signup(db, "a1", name="C1", email="c1@example.com", token="t1",
                  confirmed=True)
    insert_signup(db, "a1", name="P1", email="p1@example.com", token="t2")
    insert_signup(db, "a1", name="W1", email="w1@example.com", token="t3",
                  confirmed=True)
    insert_signup(db, "a1", name="Aged", token="t4", age=timedelta(hours=25))

    activities = signups.get_admin_activities(db)

    assert len(activities) == 1
    activity = activities[0]
    assert (activity.id, activity.title, activity.max) == (
        "a1", "Atelier de jeux", 2)
    assert (activity.confirmed, activity.pending, activity.waitlisted) == (
        1, 1, 1)
    assert [(p.name, p.email, p.confirmed, p.waitlisted)
            for p in activity.participants] == [
                ("C1", "c1@example.com", True, False),
                ("P1", "p1@example.com", False, False),
                ("W1", "w1@example.com", True, True),
            ]


def test_get_admin_activities_empty_activity(
        db: sqlite3.Connection) -> None:
    seed_activity(db, "a1", 5)

    activities = signups.get_admin_activities(db)

    assert len(activities) == 1
    assert activities[0].participants == []
    assert (activities[0].confirmed, activities[0].pending,
            activities[0].waitlisted) == (0, 0, 0)
