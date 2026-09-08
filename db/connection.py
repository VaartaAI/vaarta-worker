from psycopg2 import pool
from config.settings import Settings


class DatabasePool:
    _instance: "DatabasePool" = None
    _pool: pool.SimpleConnectionPool = None

    def __new__(cls, settings: Settings = None):
        # Singleton — only one pool ever created per process
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=settings.database_url,
                # TCP keepalives: detect a dropped connection (NAT timeout,
                # Neon idle disconnect) within ~1 minute instead of hanging
                # until the OS gives up. Values are seconds.
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
                # Fail fast on a network partition instead of blocking forever.
                connect_timeout=15,
            )
        return cls._instance

    def get_connection(self):
        conn = self._pool.getconn()
        if conn.closed:
            # A previous user hit a network error and the socket is dead.
            # Discard it and let the pool open a fresh one.
            self._pool.putconn(conn, close=True)
            conn = self._pool.getconn()
        return conn

    def release_connection(self, conn, broken: bool = False):
        """
        Return a connection to the pool. Pass broken=True after an
        OperationalError / InterfaceError so the dead socket is closed
        instead of being handed to the next caller.
        """
        self._pool.putconn(conn, close=broken or conn.closed)

    def close_all(self):
        self._pool.closeall()
