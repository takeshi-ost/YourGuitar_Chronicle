# Test Database

`ygc_test_snapshot.db` is the Git-managed SQLite snapshot used for repeatable WebUI and migration testing.

The live development database remains:

```text
phase1_proto/data/chronicle.db
```

and stays excluded from Git.

To refresh the test snapshot from the current live database, run the repository-root helper:

- Windows: `save_test_db.bat`
- macOS: `./save_test_db.command`

The helper uses SQLite's backup API, so it creates a consistent snapshot even when the source database has WAL/SHM sidecar files.

Do not put user-private data or secrets into the Git-managed test database.
