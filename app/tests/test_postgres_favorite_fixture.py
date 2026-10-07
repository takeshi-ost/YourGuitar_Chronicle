"""Validate the PG fixture's Observation identity without starting PostgreSQL."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import postgres_favorite_checks as acceptance
from test_cloud_favorites import SQLiteSQL
from ygc.db.repository import Repository


@pytest.mark.parametrize('ban', ['normal', 'ban', 'silent_ban'])
def test_acceptance_seed_has_rebuildable_identity_without_publishing_hidden_targets(tmp_path, monkeypatch, ban):
    repo = Repository(tmp_path / 'favorite-fixture.db')
    repo.init_db()
    users = {name: repo.create_user(name) for name in ('a', 'b', 'author', 'banned', 'silent')}
    with repo.connect() as con:
        con.execute("UPDATE users SET ban_status='ban' WHERE id=?", (users['banned'],))
        con.execute("UPDATE users SET ban_status='silent_ban' WHERE id=?", (users['silent'],))
        con.execute('UPDATE users SET ban_status=? WHERE id=?', (ban, users['author']))

    @contextmanager
    def connect(_settings, target):
        assert target == 'chronicle'
        with repo.connect() as con:
            yield SQLiteSQL(con)

    monkeypatch.setattr(acceptance, 'connect', connect)
    w = SimpleNamespace(owner=None, user=lambda name='a': users[name])
    acceptance.seed(w)
    with repo.connect() as con:
        targets = [row[0] for row in con.execute('SELECT DISTINCT individual_id FROM claims WHERE author_user_id=?', (users['author'],))]
        assert len(targets) == 6
        for individual in targets:
            repo._rebuild_individual_snapshot_in_connection(con, individual)
            row = con.execute('SELECT manufacturer,serial_number FROM individuals WHERE id=?', (individual,)).fetchone()
            assert row['manufacturer'] == 'Fender' and row['serial_number'] == str(individual)
        visible = con.execute("""SELECT i.id FROM individuals i WHERE EXISTS (
            SELECT 1 FROM claims c JOIN users u ON u.id=c.author_user_id
            WHERE c.individual_id=i.id AND c.status='active' AND u.ban_status='normal'
              AND c.claim_type IN ('listing','ownership','identity_correction','specification','repair','incident','event','media')
              AND c.verification_status IN ('positive','unverified','negative')) ORDER BY i.id DESC""").fetchall()
        assert [row['id'] for row in visible] == ([acceptance.BIG + 2, acceptance.BIG + 1, acceptance.BIG] if ban == 'normal' else [])
