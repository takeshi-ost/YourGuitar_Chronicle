from __future__ import annotations

from pathlib import Path

import pytest

from ygc.db.repository import Repository
from ygc.web import _validate_import_database


def test_validate_import_database_accepts_ygc_db(
    tmp_path: Path,
):
    db_path = (
        tmp_path
        / "chronicle.db"
    )

    repository = Repository(
        db_path
    )
    repository.init_db()

    counts = (
        _validate_import_database(
            db_path
        )
    )

    assert counts == {
        "observations": 0,
        "individuals": 0,
        "crawl_runs": 0,
    }


def test_validate_import_database_rejects_non_sqlite(
    tmp_path: Path,
):
    db_path = (
        tmp_path
        / "not-a-db.db"
    )
    db_path.write_bytes(
        b"not sqlite"
    )

    with pytest.raises(
        ValueError,
        match="not a SQLite 3 database",
    ):
        _validate_import_database(
            db_path
        )
