import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .schemas import RecordIn

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,
    device_id    TEXT    NOT NULL,
    sample_id    TEXT    NOT NULL,
    sequence     INTEGER NOT NULL,
    measured_at  TEXT    NOT NULL,
    received_at  TEXT    NOT NULL,
    wbc          REAL    NOT NULL,
    rbc          REAL    NOT NULL,
    hb           REAL    NOT NULL,
    payload_hash TEXT    NOT NULL,
    UNIQUE (device_id, sequence)
);
"""

UNITS = {"wbc": "10^3/uL", "rbc": "10^6/uL", "hb": "g/dL"}


def _payload_hash(r: RecordIn) -> str:
    canonical = json.dumps(r.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

class RecordRepository:
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

    def save_many(self, records: list[RecordIn], received_at: datetime) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        received = received_at.isoformat()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for r in records:
                    h = _payload_hash(r)
                    m = r.measurements
                    cur = conn.execute(
                        """INSERT INTO records (event_id, device_id, sample_id, sequence,
                               measured_at, received_at, wbc, rbc, hb, payload_hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT DO NOTHING""",
                        (r.event_id, r.device_id, r.sample_id, r.sequence,
                         r.measured_at.isoformat(), received,
                         m.wbc.value, m.rbc.value, m.hb.value, h),
                    )
                    if cur.rowcount == 1:
                        results.append((r.event_id, "created"))
                        continue
                    row = conn.execute(
                        "SELECT payload_hash FROM records WHERE event_id = ?", (r.event_id,)
                    ).fetchone()
                    status = "duplicate" if row and row["payload_hash"] == h else "conflict"
                    results.append((r.event_id, status))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return results

    def list_by_device(self, device_id: str, after_sequence: int = -1, limit: int = 1000) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT * FROM records
                   WHERE device_id = ? AND sequence > ?
                   ORDER BY sequence ASC LIMIT ?""",
                (device_id, after_sequence, limit),
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def ping(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("SELECT 1")

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        return {
            "event_id": row["event_id"],
            "device_id": row["device_id"],
            "sample_id": row["sample_id"],
            "sequence": row["sequence"],
            "measured_at": row["measured_at"],
            "received_at": row["received_at"],
            "measurements": {k: {"value": row[k], "unit": u} for k, u in UNITS.items()},
        }