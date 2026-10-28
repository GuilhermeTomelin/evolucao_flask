import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate, downgrade, upgrade
from sqlalchemy import text

from test_current import db


class MigrationTests(unittest.TestCase):
    def test_upgrade_preserves_old_rows_and_matches_models(self):
        with tempfile.TemporaryDirectory(prefix="evolucao_migration_") as directory:
            app = Flask("migration_test")
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + (Path(directory) / "old.db").as_posix()
            db.init_app(app)
            Migrate(app, db)
            with app.app_context():
                try:
                    upgrade(revision="54ad476dee56")
                    book_id, member_id, user_id = [uuid4().hex for _ in range(3)]
                    db.session.execute(text("INSERT INTO books VALUES (:id, :title, :author, :description)"),
                        {"id": book_id, "title": "Livro antigo", "author": "Autor", "description": "Preservar"})
                    db.session.execute(text("INSERT INTO members VALUES (:id, :name, :email)"),
                        {"id": member_id, "name": "Leitora antiga", "email": "igual@example.test"})
                    db.session.execute(text("INSERT INTO users VALUES (:id, :name, :email, :hash, 1, 1)"),
                        {"id": user_id, "name": "Conta antiga", "email": "igual@example.test", "hash": "valor-sintetico-de-teste"})
                    db.session.commit()
                    old = {table: db.session.execute(text(f"SELECT * FROM {table}")).all()
                           for table in ("books", "members", "users")}
                    db.session.remove()
                    upgrade(revision="a671c92d4e10")
                    for table, rows in old.items():
                        self.assertEqual(db.session.execute(text(f"SELECT * FROM {table}")).all(), rows)
                    for table in ("copies", "loans", "user_members"):
                        self.assertEqual(db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar(), 0)
                    self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
                    self.assertEqual(db.session.execute(text("PRAGMA foreign_keys")).scalar(), 1)
                    # Reversão vazia é possível sem tocar nos registros antigos.
                    db.session.remove()
                    downgrade(revision="54ad476dee56")
                    upgrade(revision="a671c92d4e10")
                    db.session.execute(text("INSERT INTO copies VALUES (:id, :book, :code)"),
                        {"id": uuid4().hex, "book": book_id, "code": "P-OLD"})
                    db.session.commit()
                    db.session.remove()
                    with self.assertRaises(SystemExit) as blocked:
                        downgrade(revision="54ad476dee56")
                    self.assertEqual(blocked.exception.code, 1)
                    self.assertEqual(db.session.execute(text("SELECT COUNT(*) FROM copies")).scalar(), 1)
                    self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
                    db.session.remove()
                    upgrade()
                    with db.engine.connect() as connection:
                        context = MigrationContext.configure(connection, opts={"compare_type": True})
                        self.assertEqual(compare_metadata(context, db.metadata), [])
                finally:
                    db.session.remove()
                    db.engine.dispose()
