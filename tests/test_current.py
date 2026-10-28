"""Regressão da base. Nenhum teste pode usar o banco de desenvolvimento."""
import os
import tempfile
import unittest
from pathlib import Path

TEMP_DATABASE = tempfile.TemporaryDirectory(prefix="evolucao_tests_")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(TEMP_DATABASE.name) / "test.db").as_posix()
os.environ["SECRET_KEY"] = "chave-apenas-para-testes-temporarios"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["FLASK_SKIP_DOTENV"] = "1"

from app import app
from db import db
from models import Book, Member, User


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.context = app.app_context()
        self.context.push()
        self.assertEqual(Path(db.engine.url.database).parent, Path(TEMP_DATABASE.name))
        db.drop_all()
        db.create_all()
        for name, admin in [("admin", True), ("ana", False), ("bia", False)]:
            user = User(name=name, email=name + "@example.test", is_admin=admin)
            user.set_password("senha-de-teste")
            db.session.add(user)
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def login(self, name="admin", client=None):
        return (client or self.client).post("/auth/login", json={
            "email": name + "@example.test", "password": "senha-de-teste"
        })

    def book(self):
        return self.client.post("/books", json={
            "title": "Dom Casmurro", "author": "Machado de Assis", "description": "Estudo"
        }).get_json()


class CurrentFeaturesTests(DatabaseCase):
    def test_auth_and_isolation(self):
        self.assertEqual(self.client.get("/books").status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={}).status_code, 400)
        self.assertEqual(self.client.post("/auth/login", json={
            "email": "ana@example.test", "password": "incorreta"
        }).status_code, 401)
        self.assertEqual(self.login("ana").status_code, 200)
        self.assertNotIn("password_hash", self.client.get("/auth/me").get_json())
        self.assertEqual(app.test_client().get("/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_inactive_account(self):
        self.login("ana")
        user = db.session.execute(db.select(User).where(User.name == "ana")).scalar_one()
        user.active = False
        db.session.commit()
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(self.login("ana").status_code, 401)

    def test_books_crud_and_validation(self):
        self.login()
        self.assertEqual(self.client.post("/books", json={"title": ""}).status_code, 400)
        book = self.book()
        self.assertEqual(self.client.get("/books/" + book["id"]).status_code, 200)
        self.assertEqual(len(self.client.get("/books").get_json()), 1)
        response = self.client.put("/books/" + book["id"], json={"title": "Novo", "author": "Autor"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["description"], "")
        self.assertEqual(self.client.get("/books/invalido").status_code, 404)
        self.assertEqual(self.client.delete("/books/" + book["id"]).status_code, 204)
        self.assertEqual(self.client.get("/books/" + book["id"]).status_code, 404)

    def test_members_and_reader_permissions(self):
        self.login()
        payload = {"name": "Ana", "email": "ana@example.test"}
        self.assertEqual(self.client.post("/members", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/members", json=payload).status_code, 409)
        self.assertEqual(len(self.client.get("/members").get_json()), 1)
        self.login("ana")
        self.assertEqual(self.client.get("/books").status_code, 200)
        for method, path, data in [
            ("get", "/members", None), ("post", "/members", payload),
            ("post", "/books", {}), ("put", "/books/invalido", {}),
            ("delete", "/books/invalido", None),
        ]:
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(path, json=data).status_code, 403)

    def test_create_user_command(self):
        result = app.test_cli_runner().invoke(args=["create-user", "--admin"],
            input="Novo\nnovo@example.test\nsenha-de-teste\nsenha-de-teste\n")
        self.assertEqual(result.exit_code, 0)
        user = db.session.execute(db.select(User).where(User.email == "novo@example.test")).scalar_one()
        self.assertTrue(user.is_admin)
        self.assertTrue(user.check_password("senha-de-teste"))
        duplicate = app.test_cli_runner().invoke(args=["create-user"],
            input="Novo\nnovo@example.test\nsenha-de-teste\nsenha-de-teste\n")
        self.assertNotEqual(duplicate.exit_code, 0)
