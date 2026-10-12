from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from ygc import cloud_backup_monitor as monitor
from ygc.db.postgres import TARGETS


def rows(due=1000):
    return [{'target': target, 'enabled': True, 'next_run': due} for target in TARGETS]


def test_due_and_grace_boundary():
    assert monitor.schedule_report(rows(), 8200)['late_targets'] == []
    assert monitor.schedule_report(rows(), 8201)['late_targets'] == list(TARGETS)


def test_independent_due_and_disabled_schedules():
    schedules = rows()
    schedules[0]['enabled'] = False
    schedules[1]['next_run'] = 10000
    report = monitor.schedule_report(schedules, 9000)
    assert report['enabled_targets'] == 3
    assert report['late_targets'] == list(TARGETS[2:])
    assert report['status'] == 'late'


@pytest.mark.parametrize('invalid', [[], rows()[:-1], rows() + rows()[:1]])
def test_missing_or_duplicate_schedule_is_not_healthy(invalid):
    with pytest.raises(ValueError):
        monitor.schedule_report(invalid, 1000)


def test_nonfinite_due_is_not_healthy():
    schedules = rows()
    schedules[0]['next_run'] = float('nan')
    with pytest.raises(ValueError):
        monitor.schedule_report(schedules, 1000)


def test_report_query_is_read_only(monkeypatch):
    con = Mock()
    con.execute.return_value.fetchall.return_value = rows()
    @contextmanager
    def connect(settings, target):
        assert target == 'operations'
        yield con
    monkeypatch.setattr(monitor, 'connect', connect)
    assert monitor.read_schedule_report(object(), 1000)['status'] == 'ok'
    assert [call.args[0] for call in con.execute.call_args_list] == [
        'SET TRANSACTION READ ONLY',
        'SELECT target,enabled,next_run FROM backup_schedules',
    ]
