import json
from pathlib import Path


def read_schedule(path: str) -> str:
    raw = Path(path).read_text(encoding="utf-8")
    json.loads(raw)
    return raw
