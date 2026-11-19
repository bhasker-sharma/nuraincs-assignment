# MorphX Device Simulator

My submission for the Neuranics software engineer assignment.

There are two separate Python programs here:

- **Device agent** (`simulator/`): pretends to be a MorphX analyser. It creates one blood test record (WBC, RBC, Hb) every 5 seconds.
- **Central server** (`server/`): receives the records over HTTP and stores them.

The device always saves a record locally first, then sends it to the server from a background thread. If the server is down, the device just keeps recording. Once the server is back, everything that piled up gets sent on its own.

## Project layout

```
nuraincs company/
├── server/
│   ├── schemas.py      what a valid record looks like (Pydantic)
│   ├── sqlite.py       RecordRepository, all the server database code
│   └── main.py         FastAPI endpoints and entry point
├── simulator/
│   ├── storage.py      LocalStore, the device's local outbox
│   └── agent.py        record generation, sync thread, retries
├── requirements.txt
├── readme.md
└── NOT_IN_SCOPE.md     things I didn't get to
```

## What I used and why

- **FastAPI** for the server. It's small, and Pydantic gives me validation almost for free. A bad request gets a clear 422 without me writing the checks by hand.
- **SQLite** on both sides. There's no setup, it's a single file, and it survives restarts. I turned on WAL mode and `synchronous=FULL`, so when the server says OK, the data really is on disk.
- **httpx** on the device, because it lets me set the connect and read timeouts separately.

The database code lives in its own class on each side (`RecordRepository` and `LocalStore`). That keeps the endpoints and the agent loop short.

## How to run it

You need Python 3.10 or newer. Run every command from the project root, not from inside `server/` or `simulator/`, because the imports are package-relative.

**Linux / macOS**

```bash
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

**Windows**

```bat
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
```

Then start the server in one terminal:

```bash
python -m server.main
```

And the device in a second terminal (activate the env there too):

```bash
python -m simulator.agent
```

While the server is running, the API docs are at http://127.0.0.1:8000/docs.

### Settings

Everything is set through environment variables, and each one has a default.

| Variable | Default | Used by |
|---|---|---|
| `MORPHX_HOST` / `MORPHX_PORT` | `127.0.0.1` / `8000` | server |
| `MORPHX_DB_PATH` | `data/morphx_server.db` | server |
| `MORPHX_SERVER_URL` | `http://127.0.0.1:8000` | device |
| `MORPHX_DEVICE_ID` | `MORPHX_SIM_001` | device |
| `MORPHX_INTERVAL` | `5` (seconds) | device |
| `MORPHX_DEVICE_DB` | `device_data/device.db` | device |

For example, to record every 2 seconds on Linux:

```bash
MORPHX_INTERVAL=2 python -m simulator.agent
```

## The record

```json
{
  "event_id": "3f1c...uuid",
  "device_id": "MORPHX_SIM_001",
  "sample_id": "S-000042",
  "sequence": 42,
  "measured_at": "2026-11-18T10:00:05+00:00",
  "measurements": {
    "wbc": {"value": 7.2,  "unit": "10^3/uL"},
    "rbc": {"value": 4.8,  "unit": "10^6/uL"},
    "hb":  {"value": 14.1, "unit": "g/dL"}
  }
}
```

- `event_id` is a UUID that's created once, along with the record, and saved with it. A retry always sends the same id.
- `sequence` is one more than the highest number in the local database, so it carries on after a restart.
- `sample_id` comes from the sequence and ties the three values of one test together.
- `measured_at` is the device clock in UTC. The server adds its own `received_at` and keeps both.
- The server only accepts those exact unit strings and sensible value ranges. A timestamp without a timezone is rejected rather than guessed.

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/records` | Takes one record or a list of up to 500 |
| GET | `/devices/{device_id}/records` | Records in sequence order. Use `after_sequence` and `limit` to page through them |
| GET | `/health` | Returns ok when the server and the database are up |

Every record sent to `POST /records` comes back with one of three statuses:

- **created**: new record, saved.
- **duplicate**: same `event_id` and same content as a record already stored. This is just a retry, and no extra row is added.
- **conflict**: same `event_id` with different data, or that device's sequence number is already taken.

Nothing ever gets overwritten. A batch is saved all at once or not at all.

## When the server is down or slow

Recording and sending are kept apart. The main loop only writes to the local database and never waits on the network. A background thread picks up pending records, oldest first, 50 at a time.

- The connect timeout is 2 seconds, so a dead server is noticed quickly. The read timeout is 10 seconds, so a slow one still gets a chance.
- On a connection error, a timeout or a 5xx, nothing changes locally. The thread waits and tries again, doubling the wait each time (1, 2, 4 ... up to 60 seconds) plus a bit of random jitter.
- On a 200, `created` and `duplicate` are marked synced, and `conflict` is marked failed.
- On a 422, the batch is marked failed, because sending the same bad data again won't fix it.

A timeout doesn't always mean the server didn't save the batch. That's fine: resending is safe, because the server recognises the `event_id` and answers `duplicate`.

## What I tested

I tested by hand, using the docs page and the two programs running side by side:

- A valid record comes back as `created`. Sending it again gives `duplicate`, and no extra row appears.
- A wrong unit (`g/L` instead of `g/dL`) gets a 422.
- I stopped the server while the device kept running. Pending records built up and the device kept retrying. When I started the server again, the backlog went up in batches and pending dropped back to zero.
- I stopped and restarted the device. The sequence carried on from where it had stopped instead of going back to 1.
- Records show up in sequence order on the GET endpoint, with both `measured_at` and `received_at`.

## Not done yet

I've kept the list of what's unfinished, and what I'd do next, in [NOT_IN_SCOPE.md](NOT_IN_SCOPE.md).
