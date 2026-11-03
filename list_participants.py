import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / "data" / "abordajeux.db"

NAMES_SQL = """
SELECT s.participant_name,
       CASE WHEN s.confirmed_at IS NOT NULL THEN 'confirmed' ELSE 'pending' END AS status,
       CASE WHEN (SELECT COUNT(*) FROM signups s2
                  WHERE s2.activity_id = s.activity_id
                  AND (s2.confirmed_at IS NOT NULL OR s2.created_at > datetime('now', '-48 hours'))
                  AND (s2.created_at, s2.rowid) < (s.created_at, s.rowid)) >= a.max_participants
            THEN 'waitlisted' ELSE 'active' END AS list
FROM signups s JOIN activities a ON a.id = s.activity_id
WHERE s.activity_id = ?
  AND (s.confirmed_at IS NOT NULL OR s.created_at > datetime('now', '-48 hours'))
ORDER BY s.created_at, s.rowid
"""


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <activity_id>", file=sys.stderr)
        sys.exit(2)

    activity_id = sys.argv[1]
    db_path = Path(__file__).parent / "data" / "abordajeux.db"
    if not db_path.exists():
        db_path = DEFAULT_DB

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    activity = conn.execute(
        "SELECT title, starts_at, max_participants FROM activities WHERE id = ?",
        (activity_id, )).fetchone()
    if activity is None:
        print(f"Activity not found: {activity_id}", file=sys.stderr)
        sys.exit(1)

    print(f"{activity['title']} ({activity['starts_at']}) "
          f"— max {activity['max_participants']}")
    rows = conn.execute(NAMES_SQL, (activity_id, )).fetchall()
    if not rows:
        print("No signups.")
        sys.exit(0)

    active = [r for r in rows if r["list"] == "active"]
    waitlisted = [r for r in rows if r["list"] == "waitlisted"]
    print(f"\nParticipants ({len(active)}):")
    for r in active:
        print(f"  {r['participant_name']} [{r['status']}]")
    if waitlisted:
        print(f"\nWaitlisted ({len(waitlisted)}):")
        for r in waitlisted:
            print(f"  {r['participant_name']} [{r['status']}]")
    conn.close()


if __name__ == "__main__":
    main()
