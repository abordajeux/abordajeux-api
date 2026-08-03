import sqlite3
from collections.abc import Iterator

import pytest

from app import db as db_mod


@pytest.fixture()
def db() -> Iterator[sqlite3.Connection]:
    conn = db_mod.connect(":memory:")
    db_mod.init_schema(conn)
    yield conn
    conn.close()
