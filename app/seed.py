import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from app import db as db_mod
from app.config import load_settings

_REQUIRED_FIELDS = ("id", "title", "start", "max_participants")

_UPSERT_SQL = (
    "INSERT INTO activities (id, title, starts_at, max_participants) "
    "VALUES (?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET "
    "title=excluded.title, starts_at=excluded.starts_at, "
    "max_participants=excluded.max_participants")


@dataclass
class ActivitySeed:
    id: str
    title: str
    starts_at: str
    max_participants: int


def load_programme(path: str | Path) -> list[ActivitySeed]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seeds: list[ActivitySeed] = []
    for raw in data.get("activities", []):
        missing = [field for field in _REQUIRED_FIELDS if field not in raw]
        if missing:
            raise ValueError(
                f"activity {raw.get('id', '?')!r} missing fields: {missing}")
        seeds.append(
            ActivitySeed(
                id=str(raw["id"]),
                title=str(raw["title"]),
                starts_at=str(raw["start"]),
                max_participants=int(raw["max_participants"]),
            ))
    return seeds


def seed_activities(conn: sqlite3.Connection,
                    seeds: list[ActivitySeed]) -> int:
    conn.executemany(
        _UPSERT_SQL,
        [(s.id, s.title, s.starts_at, s.max_participants) for s in seeds])
    return len(seeds)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.seed <path-to-programme.json>",
              file=sys.stderr)
        return 2
    seeds = load_programme(argv[1])
    conn = db_mod.connect(load_settings().database_path)
    try:
        db_mod.init_schema(conn)
        count = seed_activities(conn, seeds)
    finally:
        conn.close()
    print(f"seeded {count} activities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
