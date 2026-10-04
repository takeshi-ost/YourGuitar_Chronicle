import pytest
from ygc.db.postgres_queries import qmark_parameters


def test_shared_query_binding_preserves_literals_and_comments():
    original = "SELECT ?, '?', 'it''s?', '%s', 8 % 3, \"?\" -- ?\n /* ? */ WHERE id=?"
    assert qmark_parameters(original) == "SELECT %s, '?', 'it''s?', '%%s', 8 %% 3, \"?\" -- ?\n /* ? */ WHERE id=%s"


@pytest.mark.parametrize('query', ["SELECT 'unclosed", 'SELECT /* unclosed', 'SELECT $$?$$'])
def test_unsupported_shared_query_is_rejected(query):
    with pytest.raises(ValueError):
        qmark_parameters(query)
