# Stage 50 — DB migration and integrity audit

Source: stage49 cumulative archive. Roadmap step 50 (no separate ANF-REQ identifier).

`database.migrations.audit_database(path)` performs SQLite integrity and foreign-key checks and returns a schema inventory. `migrate_database(path, backup_path)` rejects invalid databases, future schema versions, existing backup paths, and network-style paths; it creates a SQLite-consistent backup before stamping `PRAGMA user_version=1`. The migration is non-destructive and does not change user-authored canon, manuscripts, or approval state.

**Scope limitation:** This is a baseline migration and audit utility for the existing Novel Bible SQLite database, not a complete versioned migration framework for every independent database, PostgreSQL, or a Windows EXE. A backup file is not encrypted. Keep it private. Windows was not tested.

Run: `PYTHONPATH=src python -m unittest discover -s tests -q`.
