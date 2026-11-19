import json
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    sequence  INTEGER PRIMARY KEY,
    event_id  TEXT    NOT NULL UNIQUE,
    payload   TEXT    NOT NULL,
    status    TEXT    NOT NULL DEFAULT 'pending'
);
"""


class LocalStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def next_sequence(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MAX(sequence) AS m FROM outbox").fetchone()
        return (row["m"] or 0) + 1

    def add(self, record: dict) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO outbox (sequence, event_id, payload) VALUES (?, ?, ?)",
                (record["sequence"], record["event_id"], json.dumps(record)),
            )

    def pending(self, limit: int = 50) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM outbox WHERE status = 'pending' ORDER BY sequence LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def mark(self, event_ids: list[str], status: str) -> None:
        if not event_ids:
            return
        with closing(self._connect()) as conn:
            conn.executemany(
                "UPDATE outbox SET status = ? WHERE event_id = ?",
                [(status, e) for e in event_ids],
            )

    def counts(self) -> dict:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}