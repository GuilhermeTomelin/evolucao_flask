"""Instância compartilhada e integridade referencial no SQLite."""
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def configurar_sqlite(connection, _record):
    if isinstance(connection, sqlite3.Connection):
        # PRAGMA deve ser executado fora de uma transação, em cada conexão.
        previous = getattr(connection, "autocommit", None)
        if previous is not None:
            connection.autocommit = True
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()
        if previous is not None:
            connection.autocommit = previous
