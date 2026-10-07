"""Metadata-only legacy evidence checks; never migrate or remove originals.

These conservative bounds protect the existing snapshot format and restore
staging limit. Passing is not proof that the whole database fits: the snapshot
writer still checks every encoded row and the complete archive.
"""

MAX_RESTORE_RAW = 32 * 1024 * 1024


class BackupCapacityError(ValueError):
    """An allowlisted operational code, safe to log without private row data."""
    MESSAGES = {
        'legacy_evidence_line_limit': 'Legacy evidence exceeds the snapshot row budget. Preserve the database and arrange an explicitly approved archival recovery before retrying.',
        'legacy_evidence_restore_limit': 'Legacy evidence exceeds the restore staging budget. Preserve the database and arrange an explicitly approved archival recovery before retrying.',
        'snapshot_line_limit': 'A snapshot record exceeds the existing row budget. Preserve the database and use an approved bounded recovery plan.',
        'snapshot_raw_limit': 'The snapshot exceeds the existing raw archive budget. Preserve the database and use an approved bounded recovery plan.',
        'chronicle_restore_capacity': 'Chronicle exceeds the 32 MiB restore-ready staging budget. No new backup was saved; preserve existing backups and arrange an approved recovery plan.',
        'snapshot_compressed_limit': 'The snapshot exceeds the existing compressed object budget. No new backup was saved.',
        'restore_staging_limit': 'The archive exceeds the existing 32 MiB restore staging budget. No database replacement was started.',
    }

    def __init__(self, code, stage, aggregates=None):
        if code not in self.MESSAGES or stage not in ('legacy_evidence_preflight', 'snapshot_capacity', 'restore_capacity'):
            raise ValueError('Unknown backup capacity failure.')
        self.code, self.stage = code, stage
        self.aggregates = aggregates or {}
        super().__init__(self.MESSAGES[code])


def preflight_legacy_evidence(con):
    """Only aggregate lengths leave SQL, including when a BYTEA is oversized.

    Twelve ASCII JSON bytes per text character covers escaped astral Unicode;
    512 bytes covers field delimiters, integer identities and the typed wrapper.
    This deliberately errs on the side of refusing borderline legacy archives.
    PostgreSQL bytea length and SQLite blob length share the same byte semantics.
    """
    from ygc.cloud_db_snapshot import MAX_LINE
    row = con.execute('''SELECT COUNT(*) AS legacy_rows,
        COALESCE(SUM(byte_size),0) AS legacy_bytes,
        COALESCE(MAX(byte_size),0) AS largest_legacy_bytes,
        COALESCE(MAX(encoded_bound),0) AS largest_legacy_line_bound,
        COALESCE(SUM(encoded_bound),0) AS legacy_raw_bound
        FROM (SELECT CAST(length(content) AS BIGINT) AS byte_size,
          4*((CAST(length(content) AS BIGINT)+2)/3)+512+12*(
            CAST(length(explanation) AS BIGINT)+length(summary)+
            COALESCE(length(published_summary),0)+COALESCE(length(published_at),0)+
            COALESCE(length(filename),0)+COALESCE(length(content_type),0)+length(created_at)
          ) AS encoded_bound
          FROM ownership_dispute_evidence WHERE content IS NOT NULL) AS legacy''').fetchone()
    summary = {key: int(row[key]) for key in ('legacy_rows', 'legacy_bytes', 'largest_legacy_bytes',
        'largest_legacy_line_bound', 'legacy_raw_bound')}
    if summary['largest_legacy_line_bound'] > MAX_LINE:
        raise BackupCapacityError('legacy_evidence_line_limit', 'legacy_evidence_preflight', summary)
    if summary['legacy_raw_bound'] > MAX_RESTORE_RAW:
        raise BackupCapacityError('legacy_evidence_restore_limit', 'legacy_evidence_preflight', summary)
    return summary


def failure_status(exc, stage):
    result = {'status': 'failed', 'stage': stage}
    if isinstance(exc, BackupCapacityError):
        result.update(stage=exc.stage, code=exc.code, **exc.aggregates)
    return result
