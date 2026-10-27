from uuid import uuid4

from sqlalchemy import String, Uuid
from db import db


class Member(db.Model):
    __tablename__ = "members"

    id = db.Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    name = db.Column(String(150), nullable=False)
    email = db.Column(String(200), nullable=False, unique=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email
        }