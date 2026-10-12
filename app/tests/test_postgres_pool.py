from dataclasses import replace
from unittest.mock import Mock
import pytest
from ygc.db.postgres import PostgresSettings
from ygc.db.postgres_pool import RuntimeConnectionPools


def test_pool_settings_never_appear_in_repr_and_target_validation_is_early():
    settings = PostgresSettings('127.0.0.1', 'app', 'secret')
    pools = RuntimeConnectionPools(settings)
    assert 'secret' not in repr(replace(settings, pool=pools))
    with pytest.raises(ValueError):
        pools._pool('not-a-database')
    assert not pools.pools
    pools.close()
    with pytest.raises(RuntimeError):
        pools._pool('accounts')


def test_pool_configuration_cannot_recursively_use_another_pool():
    with pytest.raises(ValueError):
        RuntimeConnectionPools(PostgresSettings('127.0.0.1', 'app', 'secret', pool=object()))


def test_failed_reset_propagates_to_pool_for_discard_and_restores_autocommit():
    con = Mock()
    con.execute.side_effect = RuntimeError('reset failed')
    with pytest.raises(RuntimeError):
        RuntimeConnectionPools.reset(con)
    assert con.autocommit is False
