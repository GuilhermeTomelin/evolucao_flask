from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from test_current import DatabaseCase, app, db
from models import Book, Copy, Loan, Member, User, UserMember
from models.loan import utc_now


class CirculationTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.book_data = self.book()
        self.members = {}
        self.users = {}
        for name in ("ana", "bia"):
            member = self.client.post("/members", json={
                "name": name, "email": name + "@example.test"}).get_json()
            user = db.session.scalar(db.select(User).where(User.name == name))
            self.members[name] = member["id"]
            self.users[name] = str(user.id)
        self.copy_data = self.client.post(
            f"/books/{self.book_data['id']}/copies", json={"inventory_code": "P-001"}).get_json()

    def link(self, name):
        response = self.client.put(f"/users/{self.users[name]}/member",
                                   json={"member_id": self.members[name]})
        self.assertEqual(response.status_code, 200)
        return response

    def reader(self, name):
        client = app.test_client()
        self.assertEqual(self.login(name, client).status_code, 200)
        return client

    def borrow(self, client):
        return client.post("/loans", json={"book_id": self.book_data["id"]})

    def test_copies_and_empty_existing_books(self):
        other = self.book()
        self.assertEqual(other["total_copies"], 0)
        self.assertEqual(other["available_copies"], 0)
        path = f"/books/{self.book_data['id']}/copies"
        self.assertEqual(self.client.post(path, json={"inventory_code": " P-001 "}).status_code, 409)
        self.assertEqual(self.client.post(path, json={"inventory_code": ""}).status_code, 400)
        self.assertEqual(self.client.post(path, json={"inventory_code": 3}).status_code, 400)
        self.assertEqual(self.client.post(path, json={"inventory_code": "P-002"}).status_code, 201)
        self.assertEqual(len(self.client.get(path).get_json()), 2)
        book = self.client.get("/books/" + self.book_data["id"]).get_json()
        self.assertEqual((book["total_copies"], book["available_copies"]), (2, 2))
        self.assertEqual(self.client.delete("/books/" + self.book_data["id"]).status_code, 409)
        self.link("ana")
        ana = self.reader("ana")
        self.assertEqual(ana.post("/loans", json={"book_id": other["id"]}).status_code, 409)
        self.assertEqual(self.client.get("/books/not-a-uuid/copies").status_code, 404)

    def test_explicit_unique_fixed_association(self):
        ana = self.reader("ana")
        self.assertIsNone(ana.get("/auth/me").get_json()["member_id"])
        response = self.borrow(ana)
        self.assertEqual(response.status_code, 403)
        self.assertIn("administrador", response.get_json()["erro"])
        self.link("ana")
        self.assertEqual(ana.get("/auth/me").get_json()["member_id"], self.members["ana"])
        self.link("ana")  # repetir o mesmo vínculo é idempotente
        self.assertEqual(self.client.put(f"/users/{self.users['bia']}/member",
            json={"member_id": self.members["ana"]}).status_code, 409)
        self.assertEqual(self.client.put(f"/users/{self.users['ana']}/member",
            json={"member_id": self.members["bia"]}).status_code, 409)
        for payload in ({}, {"member_id": None}, {"member_id": self.members["bia"], "email": "x"}):
            self.assertIn(self.client.put(f"/users/{self.users['bia']}/member", json=payload).status_code, (400, 404))
        self.assertTrue(all("password_hash" not in user for user in self.client.get("/users").get_json()))

    def test_lifecycle_privacy_history_and_deadline(self):
        self.link("ana")
        self.link("bia")
        ana, bia = self.reader("ana"), self.reader("bia")
        for extra in ({"member_id": self.members["bia"]}, {"due_at": "2099-01-01"}):
            self.assertEqual(ana.post("/loans", json={"book_id": self.book_data["id"], **extra}).status_code, 400)
        before = utc_now()
        response = self.borrow(ana)
        self.assertEqual(response.status_code, 201)
        loan = response.get_json()
        row = db.session.get(Loan, UUID(loan["id"]))
        self.assertEqual(row.member_id, UUID(self.members["ana"]))
        self.assertGreaterEqual(row.borrowed_at, before)
        self.assertEqual(row.due_at - row.borrowed_at, timedelta(days=14))
        self.assertFalse(loan["overdue"])
        self.assertEqual(self.borrow(bia).status_code, 409)
        self.assertEqual(len(ana.get("/loans").get_json()), 1)
        self.assertEqual(bia.get("/loans").get_json(), [])
        self.assertEqual(bia.get("/loans?scope=all").status_code, 403)
        self.assertEqual(bia.get("/loans?member_id=" + self.members["ana"]).status_code, 400)
        path = "/loans/" + loan["id"]
        self.assertEqual(bia.get(path).status_code, 404)
        self.assertEqual(bia.post(path + "/return").status_code, 404)
        self.assertEqual(len(self.client.get("/loans?scope=all").get_json()), 1)
        self.assertEqual(self.client.get("/loans").get_json(), [])
        self.assertEqual(self.client.get("/books/" + self.book_data["id"]).get_json()["available_copies"], 0)
        self.assertEqual(ana.post(path + "/return").status_code, 200)
        self.assertEqual(ana.post(path + "/return").status_code, 409)
        history = ana.get("/loans").get_json()
        self.assertEqual(len(history), 1)
        self.assertIsNotNone(history[0]["returned_at"])
        self.assertEqual(self.client.get("/books/" + self.book_data["id"]).get_json()["available_copies"], 1)
        second = self.borrow(bia)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.client.post("/loans/" + second.get_json()["id"] + "/return").status_code, 200)
        self.assertEqual(len(self.client.get("/loans?scope=all").get_json()), 2)
        self.assertEqual(ana.delete(path).status_code, 405)
        self.assertEqual(self.client.delete("/books/" + self.book_data["id"]).status_code, 409)

    def test_overdue_and_closed_history(self):
        self.link("ana")
        ana = self.reader("ana")
        loan = self.borrow(ana).get_json()
        row = db.session.get(Loan, UUID(loan["id"]))
        row.borrowed_at = utc_now() - timedelta(days=16)
        row.due_at = row.borrowed_at + timedelta(days=14)
        db.session.commit()
        self.assertTrue(ana.get("/loans").get_json()[0]["overdue"])
        returned = ana.post("/loans/" + loan["id"] + "/return").get_json()
        self.assertFalse(returned["overdue"])
        self.assertIsNotNone(returned["returned_at"])

    def test_new_route_permissions_and_expired_session(self):
        ana = self.reader("ana")
        routes = [
            ("get", "/users", None),
            ("get", f"/books/{self.book_data['id']}/copies", None),
            ("post", f"/books/{self.book_data['id']}/copies", {"inventory_code": "P-002"}),
            ("put", f"/users/{self.users['ana']}/member", {"member_id": self.members["ana"]}),
        ]
        for method, path, data in routes:
            with self.subTest(path=path):
                self.assertEqual(getattr(ana, method)(path, json=data).status_code, 403)
                self.assertEqual(getattr(app.test_client(), method)(path, json=data).status_code, 401)
        with ana.session_transaction() as session:
            session["user_id"] = "corrompido"
        self.assertEqual(self.borrow(ana).status_code, 401)

    def test_database_rejects_duplicate_and_invalid_references(self):
        self.assertEqual(db.session.execute(text("PRAGMA foreign_keys")).scalar(), 1)
        self.link("ana")
        ana = self.reader("ana")
        loan = self.borrow(ana).get_json()
        now = utc_now()
        db.session.add(Loan(copy_id=UUID(self.copy_data["id"]), member_id=UUID(self.members["bia"]),
                            borrowed_at=now, due_at=now + timedelta(days=14)))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.add(Copy(book_id=uuid4(), inventory_code="INVALID"))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        # Mesmo depois da devolução, referências não podem ser removidas.
        ana.post("/loans/" + loan["id"] + "/return")
        for model, identifier in ((Copy, self.copy_data["id"]), (Member, self.members["ana"]),
                                  (User, self.users["ana"]), (Book, self.book_data["id"])):
            with self.subTest(model=model.__name__):
                db.session.delete(db.session.get(model, UUID(identifier)))
                with self.assertRaises(IntegrityError):
                    db.session.commit()
                db.session.rollback()

    def race(self, clients, operation, sql_prefix):
        barrier = Barrier(2)
        def synchronize(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(sql_prefix):
                barrier.wait(timeout=15)
        engine = db.engine
        event.listen(engine, "before_cursor_execute", synchronize)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(operation, clients))
        finally:
            event.remove(engine, "before_cursor_execute", synchronize)
        return sorted(response.status_code for response in responses)

    def test_simultaneous_borrow_same_copy(self):
        self.link("ana")
        self.link("bia")
        clients = [self.reader("ana"), self.reader("bia")]
        # Ambos já escolheram o exemplar quando chegam à barreira do INSERT.
        self.assertEqual(self.race(clients, self.borrow, "INSERT INTO LOANS"), [201, 409])
        db.session.expire_all()
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(Loan)), 1)

    def test_simultaneous_returns(self):
        self.link("ana")
        ana = self.reader("ana")
        loan = self.borrow(ana).get_json()
        path = "/loans/" + loan["id"] + "/return"
        clients = [self.reader("ana"), self.reader("ana")]
        self.assertEqual(self.race(clients, lambda client: client.post(path), "UPDATE LOANS"), [200, 409])
        self.assertEqual(len(ana.get("/loans").get_json()), 1)
