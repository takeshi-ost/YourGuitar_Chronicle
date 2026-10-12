"""Read-only due-time monitoring for the independent scheduled backups."""
import math

from ygc.db.postgres import TARGETS, connect


def schedule_report(rows, now, *, grace_seconds=7200):
    """An enabled schedule is late only after its due time plus two hours.

    A manual save does not advance the scheduled due time. Disabled schedules
    are explicitly excluded; missing schedules are an operational failure.
    """
    if not math.isfinite(now) or grace_seconds < 0:
        raise ValueError('Invalid monitoring time.')
    by_target = {row['target']: row for row in rows}
    if set(by_target) != set(TARGETS) or len(rows) != len(TARGETS):
        raise ValueError('Incomplete backup schedules.')
    late = []
    enabled = 0
    for target in TARGETS:
        row = by_target[target]
        due = float(row['next_run'])
        if not math.isfinite(due):
            raise ValueError('Invalid backup due time.')
        if not row['enabled']:
            continue
        enabled += 1
        if now > due + grace_seconds:
            late.append(target)
    return {'monitor': 'backup_schedule', 'status': 'late' if late else 'ok',
            'enabled_targets': enabled, 'late_targets': late,
            'grace_seconds': grace_seconds}


def read_schedule_report(settings, now):
    with connect(settings, 'operations') as con:
        con.execute('SET TRANSACTION READ ONLY')
        rows = con.execute('SELECT target,enabled,next_run FROM backup_schedules').fetchall()
    return schedule_report(rows, now)
