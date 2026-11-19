import os
from datetime import datetime, timezone
from fastapi import Body, FastAPI, HTTPException, Query
from .sqlite import RecordRepository
from .schemas import IngestResponse, ItemResult, RecordIn, RecordOut
import uvicorn

MAX_BATCH = 500
DEFAULT_DB = "data/morphx_server.db"


def create_app(db_path: str | None = None) -> FastAPI:
    repo = RecordRepository(db_path or os.environ.get("MORPHX_DB_PATH", DEFAULT_DB))
    app = FastAPI(title="MorphX Central Server", version="1.0")

    @app.get("/health")
    def health():
        repo.ping()
        return {"status": "ok"}

    @app.post("/records", response_model=IngestResponse)
    def ingest(body: RecordIn | list[RecordIn] = Body(...)):
        records = body if isinstance(body, list) else [body]
        if not 1 <= len(records) <= MAX_BATCH:
            raise HTTPException(422, f"batch must contain 1..{MAX_BATCH} records")
        received_at = datetime.now(timezone.utc)
        results = repo.save_many(records, received_at)
        return IngestResponse(
            received_at=received_at,
            results=[ItemResult(event_id=e, status=s) for e, s in results],
        )

    @app.get("/devices/{device_id}/records", response_model=list[RecordOut])
    def list_records(
        device_id: str,
        after_sequence: int = Query(-1, ge=-1),
        limit: int = Query(1000, ge=1, le=5000),
    ):
        return repo.list_by_device(device_id, after_sequence, limit)

    return app

if __name__ == "__main__":
    uvicorn.run(
    "server.main:create_app",
    factory=True,
    host=os.environ.get("MORPHX_HOST", "127.0.0.1"),
    port=int(os.environ.get("MORPHX_PORT", "8000")),
    )