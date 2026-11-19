import logging
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from .storage import LocalStore

SERVER_URL = os.environ.get("MORPHX_SERVER_URL", "http://127.0.0.1:8000")
DEVICE_ID = os.environ.get("MORPHX_DEVICE_ID", "MORPHX_SIM_001")
INTERVAL = float(os.environ.get("MORPHX_INTERVAL", "5"))
DB_PATH = os.environ.get("MORPHX_DEVICE_DB", "device_data/device.db")
BATCH_SIZE = 50

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(threadName)s %(message)s")
log = logging.getLogger("agent")


def make_record(sequence: int) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "device_id": DEVICE_ID,
        "sample_id": f"S-{sequence:06d}",
        "sequence": sequence,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "measurements": {
            "wbc": {"value": round(random.uniform(4.0, 11.0), 2), "unit": "10^3/uL"},
            "rbc": {"value": round(random.uniform(4.2, 6.1), 2), "unit": "10^6/uL"},
            "hb": {"value": round(random.uniform(12.0, 17.5), 1), "unit": "g/dL"},
        },
    }

class Syncer(threading.Thread):
    def __init__(self, store: LocalStore, stop: threading.Event):
        super().__init__(name="sync", daemon=True)
        self.store = store
        self.stop = stop
        self.client = httpx.Client(base_url=SERVER_URL, timeout=httpx.Timeout(10, connect=2))

    def run(self):
        attempt = 0
        while not self.stop.is_set():
            batch = self.store.pending(BATCH_SIZE)
            if not batch:
                self.stop.wait(2)
                continue
            try:
                resp = self.client.post("/records", json=batch)
            except httpx.HTTPError as e:
                attempt += 1
                self._backoff(attempt, f"server unreachable ({type(e).__name__})")
                continue

            if resp.status_code == 200:
                attempt = 0
                results = resp.json()["results"]
                ok = [r["event_id"] for r in results if r["status"] in ("created", "duplicate")]
                bad = [r["event_id"] for r in results if r["status"] == "conflict"]
                self.store.mark(ok, "synced")
                self.store.mark(bad, "failed")
                log.info("synced %d, conflicts %d, left %s", len(ok), len(bad), self.store.counts())
            elif resp.status_code == 422:
                self.store.mark([r["event_id"] for r in batch], "failed")
                log.error("server rejected batch: %s", resp.text[:300])
            else:
                attempt += 1
                self._backoff(attempt, f"server error {resp.status_code}")

    def _backoff(self, attempt: int, reason: str):
        delay = min(60, 2 ** (attempt - 1)) + random.uniform(0, 1)
        log.warning("%s, retry in %.1fs", reason, delay)
        self.stop.wait(delay)
        
def main():
    store = LocalStore(DB_PATH)
    stop = threading.Event()
    syncer = Syncer(store, stop)
    syncer.start()
    log.info("device %s started, interval %ss, server %s", DEVICE_ID, INTERVAL, SERVER_URL)

    try:
        while True:
            seq = store.next_sequence()
            record = make_record(seq)
            store.add(record)
            log.info("recorded seq=%d pending=%s", seq, store.counts().get("pending", 0))
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        log.info("stopping...")
    finally:
        stop.set()
        syncer.join(timeout=5)


if __name__ == "__main__":
    main()