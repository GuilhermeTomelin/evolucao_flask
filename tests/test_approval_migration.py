"""Migra a base anterior preenchida; não importa configuração do .env."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate, upgrade, downgrade
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from test_current import db
from models import User


class ApprovalMigrationTests(unittest.TestCase):
    def test_migration_preserves_accounts_links_and_history(self):
        with tempfile.TemporaryDirectory(prefix="evolucao_approval_") as folder:
            app = Flask("approval_migration")
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + (Path(folder) / "old.db").as_posix()
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"hide_parameters": True}
            db.init_app(app)
            Migrate(app, db)
            with app.app_context():
                try:
                    upgrade(revision="a671c92d4e10")
                    ids = [uuid4() for _ in range(4)]
                    for index, (admin, active) in enumerate(((True, True), (False, True), (True, False), (False, False))):
                        db.session.execute(text(
                            "INSERT INTO users (id, name, email, password_hash, is_admin, active) "
                            "VALUES (:id, :name, :email, :hash, :admin, :active)"
                        ), {"id": ids[index].hex, "name": f"Pessoa {index}", "email": f"p{index}@example.test",
                            "hash": generate_password_hash("senha-de-teste"), "admin": admin, "active": active})
                    book, member, copy = [uuid4().hex for _ in range(3)]
                    db.session.execute(text("INSERT INTO books VALUES (:id, 'Livro', 'Autor', 'Descricao')"), {"id": book})
                    db.session.execute(text("INSERT INTO members VALUES (:id, 'Leitor', 'p1@example.test')"), {"id": member})
                    db.session.execute(text("INSERT INTO user_members VALUES (:user, :member)"), {"user": ids[1].hex, "member": member})
                    db.session.execute(text("INSERT INTO copies VALUES (:id, :book, 'ANTIGO-1')"), {"id": copy, "book": book})
                    for returned in ("2026-01-05 10:00:00", None):
                        db.session.execute(text(
                            "INSERT INTO loans VALUES (:id, :copy, :member, '2026-01-01 10:00:00', '2026-01-15 10:00:00', :returned)"
                        ), {"id": uuid4().hex, "copy": copy, "member": member, "returned": returned})
                    db.session.commit()
                    snapshots = {table: db.session.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all()
                                 for table in ("books", "members", "user_members", "copies", "loans")}
                    old_users = db.session.execute(text(
                        "SELECT id, name, email, password_hash, is_admin, active FROM users ORDER BY id")).all()
                    db.session.remove()
                    upgrade()
                    new_users = db.session.execute(text(
                        "SELECT id, name, email, password_hash, is_admin, active FROM users ORDER BY id")).all()
                    # Comparação booleana para não imprimir hashes nem mesmo em uma falha.
                    self.assertTrue(new_users == old_users, "Campos antigos de users foram alterados")
                    for table, rows in snapshots.items():
                        self.assertEqual(db.session.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all(), rows)
                    for index, (role, status) in enumerate((
                        ("admin", "approved"), ("reader", "approved"),
                        ("admin", "blocked"), ("reader", "blocked")
                    )):
                        user = db.session.get(User, ids[index])
                        self.assertEqual((user.role, user.status, user.auth_version), (role, status, 0))
                        self.assertTrue(user.check_password("senha-de-teste"))
                    self.assertIsNone(db.session.get(User, ids[0]).member_id)
                    self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
                    self.assertEqual(db.session.execute(text("PRAGMA foreign_keys")).scalar(), 1)
                    with db.engine.connect() as connection:
                        self.assertEqual(compare_metadata(MigrationContext.configure(connection), db.metadata), [])
                    db.session.remove()
                    with self.assertRaises(SystemExit):
                        downgrade(revision="a671c92d4e10")
                    self.assertEqual(db.session.execute(text("SELECT version_num FROM alembic_version")).scalar(),
                                     "b82d4f10a901")
                finally:
                    db.session.remove()
                    db.engine.dispose()
