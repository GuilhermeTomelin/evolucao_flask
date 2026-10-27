from uuid import uuid4

from werkzeug.security import generate_password_hash, check_password_hash

from db import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "is_admin": self.is_admin,
            "active": self.active
        }