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
                dsn=settings.database_url
            )
        return cls._instance

    def get_connection(self):
        return self._pool.getconn()

    def release_connection(self, conn):
        self._pool.putconn(conn)

    def close_all(self):
        self._pool.closeall()
