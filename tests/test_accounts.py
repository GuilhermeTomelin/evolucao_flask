from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from test_current import DatabaseCase, app, db
from models import User, Member, UserMember, Loan


class AccountTests(DatabaseCase):
    def user(self, name):
        return db.session.scalar(db.select(User).where(User.email == name + "@example.test"))

    def register(self, name="novo"):
        return self.client.post("/auth/register", json={
            "name": name, "email": name + "@example.test", "password": "senha-de-teste"})

    def approve(self, user_id, **data):
        return self.client.post(f"/users/{user_id}/approve", json=data)

    def client_for(self, name):
        client = app.test_client()
        self.assertEqual(self.login(name, client).status_code, 200)
        return client

    def test_public_registration_is_pending_and_never_privileged(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "pending")
        user = self.user("novo")
        self.assertEqual((user.role, user.status, user.active, user.is_admin),
                         ("reader", "pending", False, False))
        self.assertTrue(user.check_password("senha-de-teste"))
        self.assertIsNone(user.member_id)
        self.assertNotIn("password", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/books").status_code, 401)
        self.assertEqual(self.login("novo").status_code, 403)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        for field, value in [("role", "admin"), ("is_admin", True),
                             ("active", True), ("status", "approved"), ("member_id", "x")]:
            self.assertEqual(self.client.post("/auth/register", json={
                "name": "Hacker", "email": "hacker@example.test",
                "password": "senha-de-teste", field: value}).status_code, 400)

    def test_registration_validation_normalization_and_duplicates(self):
        self.assertEqual(self.client.post("/auth/register", json={
            "name": "  Novo  ", "email": " NOVO@EXAMPLE.TEST ", "password": "senha-de-teste"
        }).status_code, 201)
        self.assertEqual(self.user("novo").name, "Novo")
        self.assertEqual(self.register().status_code, 409)
        for body in ([], {}, {"name": 3, "email": "x@y", "password": "12345678"},
                     {"name": "X", "email": "invalido", "password": "12345678"},
                     {"name": "X", "email": "x@y", "password": "curta"},
                     {"name": "X", "email": "x@y", "password": "x" * 129}):
            self.assertEqual(self.client.post("/auth/register", json=body).status_code, 400)

    def test_approval_creates_reader_atomically(self):
        self.register()
        user_id = str(self.user("novo").id)
        self.login()
        self.assertEqual(self.approve(user_id).status_code, 400)
        response = self.approve(user_id, create_member=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "approved")
        self.assertIsNotNone(response.get_json()["member_id"])
        self.assertEqual(self.approve(user_id, create_member=True).status_code, 409)
        reader = self.client_for("novo")
        self.assertEqual(reader.get("/books").status_code, 200)
        self.assertEqual(reader.get("/loans").get_json(), [])
        self.assertEqual(reader.get("/users").status_code, 403)
        self.assertNotIn("password", str(reader.get("/auth/me").get_json()))

    def test_same_email_never_links_automatically_and_conflict_rolls_back(self):
        self.register()
        user = self.user("novo")
        user_id = str(user.id)
        self.login()
        member = self.client.post("/members", json={"name": "Pessoa anterior", "email": "novo@example.test"}).get_json()
        self.assertIsNone(user.member_id)
        response = self.approve(user_id, create_member=True)
        self.assertEqual(response.status_code, 409)
        db.session.expire_all()
        self.assertEqual((user.status, user.auth_version), ("pending", 0))
        self.assertIsNone(user.member_id)
        self.assertEqual(self.approve(user_id, member_id=member["id"]).status_code, 200)
        self.assertEqual(str(user.member_id), member["id"])
        self.register("outra")
        other_id = str(self.user("outra").id)
        self.assertEqual(self.approve(other_id, member_id=member["id"]).status_code, 409)
        self.assertEqual(self.user("outra").status, "pending")

    def test_reject_block_reapprove_and_old_session_stays_revoked(self):
        self.register()
        identifier = str(self.user("novo").id)
        self.login()
        self.assertEqual(self.client.post(f"/users/{identifier}/reject").status_code, 200)
        self.assertEqual(self.client.post(f"/users/{identifier}/reject").status_code, 409)
        guest = app.test_client()
        self.assertEqual(self.login("novo", guest).status_code, 403)
        self.assertEqual(self.approve(identifier, create_member=True).status_code, 200)
        member_id = self.user("novo").member_id
        reader = self.client_for("novo")
        self.assertEqual(self.client.post(f"/users/{identifier}/block").status_code, 200)
        self.assertEqual(self.approve(identifier).status_code, 200)
        # O cookie antigo não volta a funcionar nem após reaprovação.
        self.assertEqual(reader.get("/books").status_code, 401)
        self.assertEqual(self.user("novo").member_id, member_id)
        self.assertEqual(self.login("novo", reader).status_code, 200)
        self.assertEqual(self.client.post(f"/users/{identifier}/block").status_code, 200)
        self.assertEqual(reader.get("/loans").status_code, 401)
        self.assertEqual(self.login("novo", reader).status_code, 403)
        self.assertEqual(self.client.post(f"/users/{identifier}/reject").status_code, 409)

    def test_role_permissions_are_enforced_by_api(self):
        self.login()
        ana = self.client_for("ana")
        identifier = str(self.user("ana").id)
        self.assertEqual(self.client.put(f"/users/{identifier}/role", json={"role": "attendant"}).status_code, 200)
        self.assertEqual(ana.get("/books").status_code, 401)
        self.login("ana", ana)
        self.assertEqual(ana.get("/auth/me").get_json()["role"], "attendant")
        self.assertEqual(ana.get("/loans?scope=all").status_code, 200)
        for method, path, body in [
            ("get", "/users", None), ("get", "/members", None),
            ("post", "/books", {"title": "X", "author": "Y"}),
            ("post", f"/users/{identifier}/approve", {"create_member": True}),
            ("post", f"/users/{identifier}/reject", None),
            ("post", f"/users/{identifier}/block", None),
            ("put", f"/users/{identifier}/role", {"role": "admin"}),
            ("put", f"/users/{identifier}/member", {"member_id": "x"}),
        ]:
            self.assertEqual(getattr(ana, method)(path, json=body).status_code, 403)
            self.assertEqual(getattr(app.test_client(), method)(path, json=body).status_code, 401)
        self.assertEqual(self.client.put(f"/users/{identifier}/role", json={"role": "admin"}).status_code, 200)
        self.assertTrue(self.user("ana").is_admin)
        self.login("ana", ana)
        self.assertEqual(ana.get("/users").status_code, 200)
        self.assertEqual(self.client.put(f"/users/{identifier}/role", json={"role": "reader"}).status_code, 200)
        self.assertFalse(self.user("ana").is_admin)
        self.assertEqual(ana.get("/users").status_code, 401)

    def test_attendant_can_handle_existing_loans_but_reader_cannot(self):
        self.login()
        for name in ("ana", "bia"):
            member = self.client.post("/members", json={"name": name, "email": name + "@example.test"}).get_json()
            self.client.put(f"/users/{self.user(name).id}/member", json={"member_id": member["id"]})
        book = self.book()
        self.client.post(f"/books/{book['id']}/copies", json={"inventory_code": "A-1"})
        ana, bia = self.client_for("ana"), self.client_for("bia")
        loan = ana.post("/loans", json={"book_id": book["id"]}).get_json()
        path = "/loans/" + loan["id"]
        self.assertEqual(bia.get(path).status_code, 404)
        self.assertEqual(bia.post(path + "/return").status_code, 404)
        self.client.put(f"/users/{self.user('bia').id}/role", json={"role": "attendant"})
        self.login("bia", bia)
        self.assertEqual(bia.get("/loans").get_json(), [])
        self.assertEqual(bia.get(path).status_code, 200)
        self.assertEqual(bia.get(f"/books/{book['id']}/copies").status_code, 200)
        self.assertEqual(bia.post(path + "/return").status_code, 200)
        self.assertIsNotNone(ana.get(path).get_json()["returned_at"])

    def test_self_protection_and_invalid_transitions(self):
        self.login()
        admin_id = str(self.user("admin").id)
        self.assertEqual(self.client.post(f"/users/{admin_id}/block").status_code, 409)
        self.assertEqual(self.client.put(f"/users/{admin_id}/role", json={"role": "reader"}).status_code, 409)
        self.register()
        user_id = str(self.user("novo").id)
        self.assertEqual(self.client.put(f"/users/{user_id}/role", json={"role": "admin"}).status_code, 409)
        for body in ({"role": "superuser"}, {"role": ["admin"]}, {"role": "admin", "active": True}):
            self.assertEqual(self.client.put(f"/users/{user_id}/role", json=body).status_code, 400)
        self.assertEqual(self.client.post("/users/invalido/block").status_code, 404)
        self.assertEqual(self.client.post(f"/users/{user_id}/block").status_code, 409)

    def test_legacy_cookie_and_database_constraints(self):
        self.login("ana")
        with self.client.session_transaction() as session:
            session.pop("auth_version")
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        for column, value in (("role", "root"), ("status", "anything")):
            with self.assertRaises(IntegrityError):
                db.session.execute(text(f"UPDATE users SET {column} = :value"), {"value": value})
                db.session.commit()
            db.session.rollback()

    def test_competing_admin_blocks_preserve_an_administrator(self):
        self.login()
        other_id = str(self.user("ana").id)
        self.client.put(f"/users/{other_id}/role", json={"role": "admin"})
        admin_id = str(self.user("admin").id)
        first, second = self.client_for("admin"), self.client_for("ana")
        barrier = Barrier(2)
        def before_update(_conn, _cursor, sql, _params, _ctx, _many):
            if sql.startswith("UPDATE users SET"):
                barrier.wait(timeout=15)
        engine = db.engine
        event.listen(engine, "before_cursor_execute", before_update)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(first.post, f"/users/{other_id}/block"),
                           pool.submit(second.post, f"/users/{admin_id}/block")]
                statuses = sorted(future.result().status_code for future in futures)
        finally:
            event.remove(engine, "before_cursor_execute", before_update)
        self.assertEqual(statuses, [200, 409])
        db.session.expire_all()
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User).where(
            User.role == "admin", User.status == "approved", User.active.is_(True))), 1)
