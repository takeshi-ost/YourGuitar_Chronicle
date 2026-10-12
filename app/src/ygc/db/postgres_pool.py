"""Small HTTP-lifespan pools; independent transactions and nested leases."""
from contextlib import contextmanager
from threading import Lock, local
from ygc.db.postgres import connection_class, connection_parameters
from ygc.request_metrics import measure


class RuntimeConnectionPools:
    def __init__(self, settings, *, max_size=4, timeout=10):
        if settings.pool is not None:
            raise ValueError('Pool configuration must use unpooled settings.')
        self.settings = settings
        self.max_size = max_size
        self.timeout = timeout
        self.pools = {}
        self.lock = Lock()
        self.depth = local()
        self.closed = False

    @staticmethod
    def reset(con):
        # Success commits and errors roll back before reset. DISCARD also drops
        # temporary tables, session settings/role and session-level locks.
        con.autocommit = True
        try:
            con.execute('DISCARD ALL')
        finally:
            con.autocommit = False
        con.isolation_level = None
        con.read_only = None
        con.deferrable = None

    def _pool(self, target):
        self.settings.database(target)  # Reject before pool creation.
        with self.lock:
            if self.closed:
                raise RuntimeError('Database pools are closed.')
            if target not in self.pools:
                from psycopg_pool import ConnectionPool
                self.pools[target] = ConnectionPool(
                    connection_class=connection_class(),
                    kwargs={**connection_parameters(self.settings, target),
                            'prepare_threshold': None},
                    min_size=0, max_size=self.max_size, timeout=self.timeout,
                    max_waiting=32, max_idle=60, max_lifetime=600,
                    reconnect_timeout=10, num_workers=1,
                    reset=self.reset, name='ygc-' + target, open=True)
            return self.pools[target]

    @contextmanager
    def connection(self, target):
        pool = self._pool(target)
        depths = getattr(self.depth, 'values', None)
        if depths is None:
            depths = self.depth.values = {}
        nested = bool(depths)
        depth = depths.get(target, 0)
        depths[target] = depth + 1
        try:
            # Never wait for a pool while holding another store's lease:
            # canonical-lock/content transactions can nest across stores too.
            # An idle independent lease is safe; saturation uses the original
            # separate connection path rather than creating a wait cycle.
            from psycopg_pool import PoolTimeout
            try:
                with measure('db_acquire'):
                    con = pool.getconn(timeout=0 if nested else self.timeout)
            except PoolTimeout:
                if not nested:
                    raise
                with measure('db_acquire'):
                    con = connection_class().connect(**connection_parameters(self.settings, target))
                with con:
                    yield con
            else:
                try:
                    with con:
                        yield con
                finally:
                    pool.putconn(con)
        finally:
            if depth:
                depths[target] = depth
            else:
                depths.pop(target, None)

    def close(self):
        with self.lock:
            self.closed = True
            pools = list(self.pools.values())
            self.pools.clear()
        for pool in pools:
            pool.close(timeout=5)
