import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


class ActivityNotFound(LookupError):
    pass


@dataclass
class ActivitySignups:
    id: str | None
    max: int
    confirmed: int
    pending: int
    waitlisted: int

    @property
    def available(self) -> int:
        return max(0, self.max - self.confirmed - self.pending - self.waitlisted)

    @property
    def total_active(self) -> int:
        return self.confirmed + self.pending + self.waitlisted


@dataclass
class ReserveResult:
    ok: bool
    signups: ActivitySignups
    requested: int
    activity_title: str
    activity_starts_at: datetime
    waitlisted: bool = False


@dataclass
class Promotion:
    contact_email: str
    participant_name: str
    activity_id: str
    activity_title: str
    activity_starts_at: datetime


_GET_ONE_ACTIVITY_SQL = (
    "SELECT activity_id, max_participants, activity_title, activity_starts_at, "
    "number_of_confirmed_participants, number_of_pending_participants, number_of_waitlisted "
    "FROM activity_signups WHERE activity_id = ?")

_GET_ALL_ACTIVITY_SIGNUPS_SQL = (
    "SELECT activity_id, max_participants, "
    "number_of_confirmed_participants, number_of_pending_participants, number_of_waitlisted "
    "FROM activity_signups ORDER BY activity_id")

_INSERT_SIGNUP_SQL = (
    "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at) "
    "VALUES (?, ?, ?, ?, ?, NULL)")


def _row_to_activity_signups(row: sqlite3.Row) -> ActivitySignups:
    return ActivitySignups(
        id=row["activity_id"],
        max=row["max_participants"],
        confirmed=row["number_of_confirmed_participants"],
        pending=row["number_of_pending_participants"],
        waitlisted=row["number_of_waitlisted"],
    )


def get_activity_signups(
        conn: sqlite3.Connection,
        activity_id: str) -> ActivitySignups | None:
    row = conn.execute(_GET_ONE_ACTIVITY_SQL,
                       (activity_id, )).fetchone()
    if row is None:
        return None
    return _row_to_activity_signups(row)


def get_all_activity_signups(
        conn: sqlite3.Connection) -> list[ActivitySignups]:
    rows = conn.execute(_GET_ALL_ACTIVITY_SIGNUPS_SQL).fetchall()
    return [_row_to_activity_signups(row) for row in rows]


def _read_activity(
    conn: sqlite3.Connection,
    activity_id: str,
) -> tuple[ActivitySignups, str, str] | None:
    row = conn.execute(_GET_ONE_ACTIVITY_SQL,
                       (activity_id, )).fetchone()
    if row is None:
        return None
    return (_row_to_activity_signups(row), row["activity_title"],
            row["activity_starts_at"])


def reserve_signups(
    conn: sqlite3.Connection,
    activity_id: str,
    contact_email: str,
    participant_names: list[str],
    *,
    verification_token: str,
) -> ReserveResult:
    """Atomic reserve under SQLite's writer serialization.

    BEGIN IMMEDIATE takes the write lock before the view read, so concurrent
    submissions cannot interleave between the capacity check and the insert.
    """
    n = len(participant_names)
    if n < 1:
        raise ValueError("participant_names must not be empty")

    conn.execute("BEGIN IMMEDIATE")
    read = _read_activity(conn, activity_id)
    if read is None:
        conn.execute("ROLLBACK")
        raise ActivityNotFound(activity_id)
    state, title, starts_at_raw = read
    starts_at = datetime.fromisoformat(starts_at_raw)

    group_overflow = n > 1 and state.total_active + n > state.max
    waitlist_cap_exceeded = state.total_active + n > 2 * state.max
    if group_overflow or waitlist_cap_exceeded:
        conn.execute("ROLLBACK")
        return ReserveResult(ok=False,
                             signups=state,
                             requested=n,
                             activity_title=title,
                             activity_starts_at=starts_at)

    rows = [(uuid.uuid4().hex, activity_id, contact_email, name,
             verification_token) for name in participant_names]
    try:
        conn.executemany(_INSERT_SIGNUP_SQL, rows)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return ReserveResult(ok=True,
                         signups=state,
                         requested=n,
                         waitlisted=state.total_active + n > state.max,
                         activity_title=title,
                         activity_starts_at=starts_at)


@dataclass
class ConfirmOutcome:
    status: str
    activity_id: str | None = None
    waitlisted: bool = False


_TOKEN_ROWS_SQL = "SELECT activity_id FROM signups WHERE verification_token = ?"
_LIVE_SIGNUP_SQL = (
    "SELECT 1 FROM signups WHERE verification_token = ? "
    "AND (confirmed_at IS NOT NULL OR created_at > datetime('now', '-24 hours')) LIMIT 1"
)
_CONFIRM_TOKEN_SQL = ("UPDATE signups SET confirmed_at = CURRENT_TIMESTAMP "
                      "WHERE verification_token = ? AND confirmed_at IS NULL")
_TOKEN_POSITION_SQL = (
    "SELECT a.max_participants, "
    "(SELECT COUNT(*) FROM signups s2 "
    " WHERE s2.activity_id = s.activity_id "
    " AND (s2.confirmed_at IS NOT NULL OR s2.created_at > datetime('now', '-24 hours')) "
    " AND (s2.created_at, s2.rowid) < (s.created_at, s.rowid)) AS ahead "
    "FROM signups s JOIN activities a ON a.id = s.activity_id "
    "WHERE s.verification_token = ? ORDER BY s.rowid LIMIT 1")
_SET_PROMOTED_BY_TOKEN_SQL = (
    "UPDATE signups SET promoted_at = CURRENT_TIMESTAMP "
    "WHERE verification_token = ? AND promoted_at IS NULL")


def confirm_by_token(conn: sqlite3.Connection, token: str) -> ConfirmOutcome:
    rows = conn.execute(_TOKEN_ROWS_SQL, (token, )).fetchall()
    if not rows:
        return ConfirmOutcome(status="invalid_token")
    activity_id = rows[0]["activity_id"]

    if conn.execute(_LIVE_SIGNUP_SQL, (token, )).fetchone() is None:
        return ConfirmOutcome(status="expired", activity_id=activity_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(_CONFIRM_TOKEN_SQL, (token, ))
        position = conn.execute(_TOKEN_POSITION_SQL, (token, )).fetchone()
        waitlisted = (position is not None
                      and position["ahead"] >= position["max_participants"])
        if not waitlisted:
            conn.execute(_SET_PROMOTED_BY_TOKEN_SQL, (token, ))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return ConfirmOutcome(status="confirmed",
                          activity_id=activity_id,
                          waitlisted=waitlisted)


_PROMOTIONS_SQL = (
    "SELECT s.rowid AS rid, s.contact_email, s.participant_name, s.activity_id, "
    "a.title AS activity_title, a.starts_at AS activity_starts_at "
    "FROM signups s JOIN activities a ON a.id = s.activity_id "
    "WHERE s.confirmed_at IS NOT NULL AND s.promoted_at IS NULL "
    "AND (SELECT COUNT(*) FROM signups s2 "
    "     WHERE s2.activity_id = s.activity_id "
    "     AND (s2.confirmed_at IS NOT NULL OR s2.created_at > datetime('now', '-24 hours')) "
    "     AND (s2.created_at, s2.rowid) < (s.created_at, s.rowid)) < a.max_participants "
    "ORDER BY s.activity_id, s.created_at, s.rowid")
_SET_PROMOTED_BY_ROWID_SQL = (
    "UPDATE signups SET promoted_at = CURRENT_TIMESTAMP "
    "WHERE rowid = ? AND promoted_at IS NULL")


@dataclass
class PromotionReport:
    promoted: list[Promotion]
    failed: list[Promotion]


def promote_waitlisted(
    conn: sqlite3.Connection,
    send: Callable[[Promotion], None],
) -> PromotionReport:
    """Send-then-mark promotion pass (D13: at-least-once).

    A failed send leaves promoted_at NULL so the next run retries; the
    marker is set only after a successful send.
    """
    rows = conn.execute(_PROMOTIONS_SQL).fetchall()
    promoted: list[Promotion] = []
    failed: list[Promotion] = []
    for row in rows:
        promotion = Promotion(
            contact_email=row["contact_email"],
            participant_name=row["participant_name"],
            activity_id=row["activity_id"],
            activity_title=row["activity_title"],
            activity_starts_at=datetime.fromisoformat(
                row["activity_starts_at"]),
        )
        try:
            send(promotion)
        except Exception:
            failed.append(promotion)
        else:
            conn.execute(_SET_PROMOTED_BY_ROWID_SQL, (row["rid"], ))
            promoted.append(promotion)
    return PromotionReport(promoted=promoted, failed=failed)


@dataclass
class AdminParticipant:
    name: str
    email: str
    confirmed: bool
    waitlisted: bool


@dataclass
class AdminActivity:
    id: str
    title: str
    max: int
    confirmed: int
    pending: int
    waitlisted: int
    participants: list[AdminParticipant]


_ADMIN_SQL = (
    "SELECT a.id AS activity_id, a.title AS activity_title, "
    "a.max_participants, sub.contact_email, sub.participant_name, "
    "sub.confirmed_at IS NOT NULL AS confirmed, "
    "sub.pos > a.max_participants AS waitlisted "
    "FROM activities a "
    "LEFT JOIN ("
    "    SELECT s.*, s.rowid AS signup_rowid, "
    "           ROW_NUMBER() OVER (PARTITION BY s.activity_id "
    "                              ORDER BY s.created_at, s.rowid) AS pos "
    "    FROM signups s "
    "    WHERE s.confirmed_at IS NOT NULL "
    "    OR s.created_at > datetime('now', '-24 hours')"
    ") sub ON sub.activity_id = a.id "
    "ORDER BY a.id, sub.created_at, sub.signup_rowid")


def get_admin_activities(conn: sqlite3.Connection) -> list[AdminActivity]:
    rows = conn.execute(_ADMIN_SQL).fetchall()
    grouped: dict[str, tuple[str, int, list[AdminParticipant]]] = {}
    for row in rows:
        activity_id = row["activity_id"]
        entry = grouped.get(activity_id)
        if entry is None:
            entry = (row["activity_title"], row["max_participants"], [])
            grouped[activity_id] = entry
        if row["contact_email"] is not None:
            entry[2].append(
                AdminParticipant(
                    name=row["participant_name"],
                    email=row["contact_email"],
                    confirmed=bool(row["confirmed"]),
                    waitlisted=bool(row["waitlisted"]),
                ))
    activities: list[AdminActivity] = []
    for activity_id, (title, max_participants,
                      participants) in grouped.items():
        activities.append(
            AdminActivity(
                id=activity_id,
                title=title,
                max=max_participants,
                confirmed=sum(
                    1 for p in participants if p.confirmed and not p.waitlisted
                ),
                pending=sum(
                    1 for p in participants
                    if not p.confirmed and not p.waitlisted
                ),
                waitlisted=sum(1 for p in participants if p.waitlisted),
                participants=participants,
            ))
    return activities
