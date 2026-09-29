"""Lazy, per-process PostgreSQL pool; every checkout is one bounded transaction."""
import atexit
import os
from contextlib import contextmanager
from threading import Lock
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from flask import current_app


class Database:
    def __init__(self, config):
        self.config = config
        self.pool = None
        self.pid = None
        self.lock = Lock()

    def get_pool(self):
        with self.lock:
            if self.pool is None or self.pid != os.getpid():
                self.pool = ConnectionPool(
                    self.config['DATABASE_URL'], min_size=0,
                    max_size=self.config['DB_POOL_SIZE'], timeout=self.config['DB_POOL_TIMEOUT'],
                    max_waiting=64, max_idle=60, max_lifetime=1800,
                    reconnect_timeout=15, check=ConnectionPool.check_connection,
                    kwargs={'row_factory': dict_row, 'connect_timeout': 5},
                    open=True, name='inventory',
                )
                self.pid = os.getpid()
                atexit.register(self.pool.close)
        return self.pool

    @contextmanager
    def transaction(self):
        with self.get_pool().connection() as conn:
            conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(self.config['DB_STATEMENT_TIMEOUT_MS']),))
            conn.execute("SELECT set_config('lock_timeout', '2000', true)")
            conn.execute("SELECT set_config('idle_in_transaction_session_timeout', '10000', true)")
            conn.execute("SELECT set_config('TimeZone', 'UTC', true)")
            yield conn

    def close(self):
        if self.pool:
            self.pool.close()


def transaction():
    return current_app.extensions['db'].transaction()
