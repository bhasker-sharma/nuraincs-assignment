# Not in scope / not done yet


## Testing

- **No automated tests.** Everything in the readme was checked by hand. Next I'd add pytest tests for:
  - duplicates and conflicts;
  - missing and invalid fields;
  - the server going down in the middle of a sync.
- **Linux.** I developed on Windows. The code has nothing OS-specific in it (plain Python, SQLite, HTTP), and the Linux setup steps are in the readme, but I haven't done a full run on a real Linux machine.

## Sync behaviour

- **One bad record fails the whole batch.** If a single record in a batch gets a 422, every record in that batch is marked failed. It would be better to split the batch and find the bad one.
- **Failed records just sit there.** Nothing retries them or reports them anywhere except the log.
- **Deleting the device database breaks the sequence.** If `device.db` is deleted, the sequence starts again at 1. Every new record then clashes with sequence numbers the server already has, and comes back as a conflict. A real device would need to get its last sequence back from the server.

## Security

- **No authentication between the device and the server.** Anyone who can reach the server can post records.
- **No HTTPS.** Everything goes over plain HTTP.

## Data quality

- **Device clock not checked.** If the device clock is way off, the server stores `measured_at` as it is. The server does keep its own `received_at`, so the gap can at least be spotted later.
- **Random values.** The measurements are uniform random numbers in a normal range. There are no abnormal results, and no link between Hb and RBC.

## Scaling

- **SQLite only.** It's fine on one machine. For lots of devices I'd move the server to Postgres. Only `RecordRepository` would need to change.
- **One device per process.** To simulate several devices, you start several agents with different `MORPHX_DEVICE_ID` and `MORPHX_DEVICE_DB` values.
