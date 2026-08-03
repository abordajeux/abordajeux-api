import sqlite3
import uuid
from dataclasses import dataclass


class ActivityNotFound(LookupError):
    pass


@dataclass
class ActivitySignups:
    id: str | None
    max: int
    confirmed: int
    pending: int

    @property
    def available(self) -> int:
        return self.max - self.confirmed - self.pending


@dataclass
class ReserveResult:
    ok: bool
    signups: ActivitySignups
    requested: int


_GET_ONE_ACTIVITY_SIGNUPS_SQL = (
    "SELECT activity_id, max_participants, "
    "number_of_confirmed_participants, number_of_pending_participants "
    "FROM activity_signups WHERE activity_id = ?"
)

_GET_ALL_ACTIVITY_SIGNUPS_SQL = (
    "SELECT activity_id, max_participants, "
    "number_of_confirmed_participants, number_of_pending_participants "
    "FROM activity_signups ORDER BY activity_id"
)

_INSERT_SIGNUP_SQL = (
    "INSERT INTO signups (id, activity_id, contact_email, participant_name, verification_token, confirmed_at) "
    "VALUES (?, ?, ?, ?, ?, NULL)"
)


def _row_to_activity_signups(row: sqlite3.Row) -> ActivitySignups:
    return ActivitySignups(
        id=row["activity_id"],
        max=row["max_participants"],
        confirmed=row["number_of_confirmed_participants"],
        pending=row["number_of_pending_participants"],
    )


def get_activity_signups(conn: sqlite3.Connection, activity_id: str) -> ActivitySignups | None:
    row = conn.execute(_GET_ONE_ACTIVITY_SIGNUPS_SQL, (activity_id,)).fetchone()
    if row is None:
        return None
    return _row_to_activity_signups(row)


def get_all_activity_signups(conn: sqlite3.Connection) -> list[ActivitySignups]:
    rows = conn.execute(_GET_ALL_ACTIVITY_SIGNUPS_SQL).fetchall()
    return [_row_to_activity_signups(row) for row in rows]


def reserve_signups(
    conn: sqlite3.Connection,
    activity_id: str,
    contact_email: str,
    participant_names: list[str],
    *,
    verification_token: str,
) -> ReserveResult:
    n = len(participant_names)
    if n < 1:
        raise ValueError("participant_names must not be empty")

    conn.execute("BEGIN IMMEDIATE")
    signups = get_activity_signups(conn, activity_id)
    if signups is None:
        conn.execute("ROLLBACK")
        raise ActivityNotFound(activity_id)

    if signups.confirmed + signups.pending + n > signups.max:
        conn.execute("ROLLBACK")
        return ReserveResult(ok=False, signups=signups, requested=n)

    rows = [
        (uuid.uuid4().hex, activity_id, contact_email, name, verification_token)
        for name in participant_names
    ]
    try:
        conn.executemany(_INSERT_SIGNUP_SQL, rows)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return ReserveResult(ok=True, signups=signups, requested=n)
