# Runbook: backup and restore

The platform's state is:

- the metadata database (SQLite by default, or Postgres via `DATABASE_URL`);
- the object store (`HOP_OBJECT_STORE_DIR`), which holds raw provider payloads, model-call records and
  exports.

Both are needed to prove evidence lineage, so always back them up together.

## Back up

```bash
python infrastructure/backup/backup.py backup --out backups/
```

This produces `backups/hop-backup-<UTC timestamp>/` containing:

- `hop.db` (made with the SQLite online-backup API, so the app can keep running) or `hop.pgdump`
  (made with `pg_dump --format=custom`);
- `objects.tar.gz`;
- `manifest.json`, with the SHA-256 of the database dump and of every object.

Schedule it daily, keep 30 days, and copy it off-host. Pilot targets are an RPO of 24 hours and an
RTO of 4 hours.

## Verify

```bash
python infrastructure/backup/backup.py verify backups/hop-backup-<ts>
```

This recomputes every hash. A damaged or tampered backup is reported, and `restore` refuses to use
it (see `tests/unit/test_backup.py`).

## Restore

```bash
HOP_DATA_DIR=/restore/target python infrastructure/backup/backup.py restore backups/hop-backup-<ts>
HOP_DATA_DIR=/restore/target hop audit verify
HOP_DATA_DIR=/restore/target hop run list
```

Restore refuses to overwrite an existing database or a non-empty object store unless you pass
`--force`. After restoring, confirm that the audit chain is valid and spot-check the lineage of one
card's evidence with `GET /evidence/{id}`; `lineage.valid` must be true.

Test a restore at least once a quarter, and before every production release.
