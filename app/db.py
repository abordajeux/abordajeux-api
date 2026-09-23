import sqlite3
from pathlib import Path

SCHEMA_SQL = """\
DROP VIEW IF EXISTS activity_signups;

CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    starts_at TIMESTAMP NOT NULL,
    max_participants INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS signups (
    id TEXT PRIMARY KEY,
    activity_id TEXT NOT NULL REFERENCES activities(id),
    contact_email TEXT NOT NULL,
    participant_name TEXT NOT NULL,
    verification_token TEXT,
    confirmed_at TIMESTAMP,
    promoted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signups_activity ON signups(activity_id);
CREATE INDEX IF NOT EXISTS idx_signups_token ON signups(verification_token);

CREATE VIEW IF NOT EXISTS activity_signups AS
SELECT
    a.id AS activity_id,
    a.title AS activity_title,
    a.starts_at AS activity_starts_at,
    a.max_participants,
    COUNT(CASE WHEN sub.pos <= a.max_participants AND sub.confirmed_at IS NOT NULL THEN 1 END)
        AS number_of_confirmed_participants,
    COUNT(CASE WHEN sub.pos <= a.max_participants AND sub.confirmed_at IS NULL THEN 1 END)
        AS number_of_pending_participants,
    COUNT(CASE WHEN sub.pos > a.max_participants THEN 1 END) AS number_of_waitlisted
FROM activities a
LEFT JOIN (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.activity_id
                                   ORDER BY s.created_at, s.rowid) AS pos
    FROM signups s
    WHERE s.confirmed_at IS NOT NULL OR s.created_at > datetime('now', '-24 hours')
) sub ON sub.activity_id = a.id
GROUP BY a.id, a.max_participants;
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    path_str = str(path)
    conn = sqlite3.connect(path_str, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path_str != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
