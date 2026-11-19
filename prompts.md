## 1. Overview and system design

I'm building a Python simulator, device plus a central server. Two separate
processes, both running locally on Linux and Windows.

How I want it to work:
- Device agent generates one synthetic test record every 5s (configurable).
- Every record is written to a local SQLite DB first, then synced to the
  server in a background thread. Acquisition never waits on the network.
- Server is FastAPI + SQLite, accepts records over HTTP, and returns them by
  device_id ordered by sequence.
- If the server is down, the agent keeps recording. When it's back, pending
  records go up automatically, no duplicates, no gaps.

Don't write code yet. Go through this design and tell me where it could
break: crashes mid-write, crashes mid-sync, clock issues, concurrent SQLite
access. Keep the answer short.

---

## 2. Folder structure and record schema

Here's the structure I'm going with:

    nuraincs company/
      server/     main.py, schemas.py, sqlite.py
      simulator/  agent.py, storage.py
      requirements.txt, readme.md

Record schema:
- event_id: UUID4, created once at generation and stored, never regenerated
- device_id: e.g. MORPHX_SIM_001, from config
- sample_id: synthetic, built from the sequence, e.g. S-000123
- sequence: int, per device, continues across restarts (read max from DB)
- measured_at: UTC ISO 8601 with timezone, set on the device
- measurements: wbc, rbc, hb, each with value + unit
  (10^3/uL, 10^6/uL, g/dL)
- received_at: server side only, never sent by the device

Write the Pydantic models for this in server/schemas.py. Forbid extra
fields, validate units strictly with exact strings, and reject values
outside a sane physical range. Reject a measured_at without a timezone
instead of guessing. On the device side keep the record as a plain dict,
it shouldn't depend on FastAPI or Pydantic.

---

## 3. Server
Now the server. I want a RecordRepository class in server/sqlite.py that
owns all SQLite logic, endpoints in main.py just call it.

- POST /records takes one record or a list of up to 500
- event_id is UNIQUE, and (device_id, sequence) is UNIQUE too
- use INSERT ... ON CONFLICT DO NOTHING and store a hash of the payload.
  For each record return one of:
  - created: new row
  - duplicate: same event_id, same content, just a retry
  - conflict: same event_id with different data, or the sequence is taken
  Never overwrite anything.
- save the whole batch in one transaction, all or nothing
- GET /devices/{device_id}/records?after_sequence=&limit= ordered by sequence
- GET /health so I can check the server and DB are up
- set received_at on the server, don't trust anything from the client for it

Use WAL mode and synchronous=FULL so an OK really means it's on disk. Host,
port and DB path from env variables with sensible defaults.

---

## 4. Device local storage
storage.py next. LocalStore class, its own SQLite file, set up as an outbox.

- outbox table: sequence (primary key), event_id (unique), the full record
  as JSON payload, and status (pending / synced / failed)
- next_sequence() reads MAX(sequence) from the DB, so a restart continues
  where it left off
- add(record) saves the record as pending
- pending(limit) returns pending records ordered by sequence
- mark(event_ids, status) to move records to synced or failed
- counts() so I can log how many are pending

The main loop and the sync thread will both use this, so open a fresh
connection for each call instead of sharing one. Use WAL and
synchronous=FULL here as well. Tell me if you see a race I've missed.

---

## 5. Record generation and agent loop

simulator/agent.py.

make_record(sequence) builds one record with realistic random values in the
normal ranges, rounded properly (WBC 4.0-11.0, RBC 4.2-6.1, Hb 12.0-17.5).

main() runs the acquisition loop: next sequence, make the record, save it
locally, log one line, sleep for the interval. It must never touch the
network.

Config from env variables: MORPHX_DEVICE_ID, MORPHX_INTERVAL,
MORPHX_SERVER_URL, MORPHX_DEVICE_DB, all with defaults. Ctrl+C should stop
the loop and the sync thread cleanly.

---

## 6. Background sync

Put a Syncer thread class in agent.py.

- pull pending records in batches of 50, oldest first
- POST them with httpx, connect timeout 2s, read timeout 10s
- on 200: mark created and duplicate as synced, conflict as failed
- on 422: mark the batch failed, sending bad data again won't fix it
- on connection error, timeout or 5xx: change nothing locally, back off
  exponentially (1, 2, 4 ... capped at 60s) with jitter, reset after a
  success
- never raise out of the loop, log and continue

The important case: server saves the batch but the response never reaches
the device. Confirm the device resends and the server answers duplicate
safely.

---

## 7. Edge cases to check by hand

Give me a short checklist to test this by hand with both processes running
and the /docs page:

1. Same record posted twice: created the first time, duplicate the second,
   no extra row
2. Wrong unit (g/L instead of g/dL): rejected with 422
3. Server down for a while: agent keeps recording, pending builds up, then
   everything syncs after the server is back
4. Agent restarted: sequence continues from the last value
5. GET returns records in sequence order with measured_at and received_at

---

## 8. Review and README

Here's my code for agent.py and storage.py. Review it the way a senior
engineer would: concurrency bugs, crash points, anything that could lose or
duplicate a record. Don't rewrite it, just list problems by severity.

Then draft a README covering: how to run both processes on Linux and
Windows, the env settings, the record format, the API, how the device deals
with a down or slow server, what I tested, and why I chose FastAPI and
SQLite. Put what I didn't finish (automated tests, splitting a failed
batch, auth, TLS, clock checks, Postgres on the server) in a separate
NOT_IN_SCOPE.md. Keep it in my own voice, I'll edit it myself.
