"""SQLite cache of verified claims and of credits spent per UTC day (PRD §3 P0.7, D11).

A claim is cached by (normalised claim, pack, UTC date), so the same claim from several models costs one search a day.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from terkini.claims import ClaimResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_key TEXT NOT NULL,
    pack TEXT NOT NULL,
    day TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (claim_key, pack, day)
);
CREATE TABLE IF NOT EXISTS credits (
    day TEXT PRIMARY KEY,
    spent INTEGER NOT NULL
);
"""


class Cache:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def get(self, claim_key: str, pack: str, day: date) -> ClaimResult | None:
        row = self._db.execute(
            "SELECT result FROM claims WHERE claim_key = ? AND pack = ? AND day = ?",
            (claim_key, pack, day.isoformat()),
        ).fetchone()
        return ClaimResult.model_validate_json(row[0]) if row else None

    def put(self, claim_key: str, pack: str, day: date, result: ClaimResult) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO claims (claim_key, pack, day, result) VALUES (?, ?, ?, ?)",
                (claim_key, pack, day.isoformat(), result.model_dump_json()),
            )

    def spent_on(self, day: date) -> int:
        row = self._db.execute("SELECT spent FROM credits WHERE day = ?", (day.isoformat(),)).fetchone()
        return int(row[0]) if row else 0

    def add_spent(self, day: date, credits: int) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO credits (day, spent) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET spent = spent + excluded.spent",
                (day.isoformat(), credits),
            )
