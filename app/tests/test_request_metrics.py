import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool
from ygc.request_metrics import RequestTiming, RequestMetrics, _current, measure


def test_measure_failure_and_thread_context_isolation():
    with measure('identity'):
        pass
    metrics = RequestMetrics()
    token = _current.set(metrics)
    try:
        try:
            with measure('identity'):
                raise ValueError('secret')
        except ValueError:
            pass
        assert metrics.counts == {'identity': 1}
        assert metrics.values['identity'] >= 0
    finally:
        _current.reset(token)
    assert _current.get() is None


def test_request_metrics_follow_threadpool_without_caching_or_logging_inputs(monkeypatch):
    import logging
    logger = Mock()
    original = logging.getLogger
    monkeypatch.setattr(logging, 'getLogger', lambda name=None: logger if name == 'ygc.performance' else original(name))
    app = FastAPI()
    app.add_middleware(RequestTiming)
    @app.get('/api/items/{item}')
    async def read(item: str):
        def work():
            with measure('db_acquire'):
                pass
            for _ in range(2):
                with measure('sql_execute'):
                    pass
        await run_in_threadpool(work)
        return {'ok': True}
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(lambda _: client.get('/api/items/private-id?token=secret',
                headers={'Authorization': 'Bearer secret'}), range(2)))
        missing = client.get('/api/missing-private-id?token=secret')
    assert all(response.status_code == 200 for response in responses)
    assert all('db_acquire;dur=' in response.headers['server-timing'] for response in responses)
    assert missing.status_code == 404
    logs = [json.loads(call.args[0]) for call in logger.info.call_args_list]
    assert len(logs) == 3
    assert [row['counts'] for row in logs[:2]] == [{'db_acquire': 1, 'sql_execute': 2}] * 2
    assert logs[-1]['route'] == 'unmatched'
    assert all('private-id' not in json.dumps(row) and 'secret' not in json.dumps(row) for row in logs)
    assert all(row['route'] == '/api/items/{item}' for row in logs[:2])
    assert _current.get() is None
