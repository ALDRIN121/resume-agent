# Candidate backup and rollback

State schema upgrades are forward migrations. An older application rejects a newer database schema. Do not downgrade code against a newer live database.

## Before an upgrade

1. Stop the local web server and active CLI workers.
2. Copy the complete application state directory to a private backup location.
3. Include both SQLite databases, profile source, run artifacts, settings and ownership files.
4. Back up configured output directories separately.
5. Record the application revision, schema version and backup time.
6. Confirm the backup files can be read before starting the candidate.

The default state directory is `~/.resume_generator`. An explicit `RESUME_GENERATOR_STATE_DIR` changes that location. Keep credentials in private backups.

## Roll back safely

1. Stop all candidate workers.
2. Keep a separate copy of the current candidate state and outputs.
3. Select the complete pre-upgrade backup and its matching application revision.
4. Restore that state into a separate directory first.
5. Start the matching application with that explicit state directory.
6. Inspect saved work and artifact availability without starting new runs.
7. Compare canonical PDF hashes before resuming normal use.
8. Reconcile any post-backup work from the retained candidate copy.

Do not merge SQLite rows or replace only one database. A library migration backup alone does not restore matching workflow checkpoints. Post-backup approvals, memory decisions and application events are absent from an older snapshot.

Keep friendly exported PDFs when preserving newer work. A rollback does not mean that a later document was never sent. Record corrections explicitly after restoring the appropriate application state.

No rollback or backup operation has been performed against personal application state during this implementation.
