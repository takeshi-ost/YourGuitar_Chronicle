"""Request-scoped aggregate timings; never tokens, SQL text or user data."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from threading import Lock
from time import perf_counter

_current = ContextVar('ygc_request_metrics', default=None)

class RequestMetrics:
    def __init__(self):
        self.values = {}
        self.counts = {}
        self.lock = Lock()

    def add(self, name, elapsed):
        with self.lock:
            self.values[name] = self.values.get(name, 0) + elapsed * 1000
            self.counts[name] = self.counts.get(name, 0) + 1

@contextmanager
def measure(name):
    metrics = _current.get()
    if metrics is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        metrics.add(name, perf_counter() - started)

class RequestTiming:
    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger('ygc.performance')
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        metrics = RequestMetrics()
        token = _current.set(metrics)
        started, status = perf_counter(), 500
        async def timed_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                timings = {'app': (perf_counter() - started) * 1000, **metrics.values}
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [(b'server-timing',
                    ', '.join(f'{name};dur={value:.2f}' for name, value in timings.items()).encode('ascii'))]
            await send(message)
        try:
            await self.app(scope, receive, timed_send)
        finally:
            _current.reset(token)
            # Only the declared route template: no input path/query/identifiers.
            route = getattr(scope.get('route'), 'path', 'unmatched')
            self.logger.info(json.dumps({'event': 'request_timing', 'route': route,
                'method': scope['method'], 'status': status,
                'app_ms': round((perf_counter() - started) * 1000, 2),
                'timings_ms': {key: round(value, 2) for key, value in metrics.values.items()},
                'counts': metrics.counts}, separators=(',', ':')))
