from uuid import uuid4

from sqlalchemy import String, Text, Uuid
from db import db


class Book(db.Model):
    __tablename__ = "books"

    id = db.Column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    title = db.Column(String(200), nullable=False)
    author = db.Column(String(150), nullable=False)
    description = db.Column(Text, nullable=False, default="")

    def to_dict(self):
        from .copy import Copy
        from .loan import Loan
        active = db.select(Loan.id).where(
            Loan.copy_id == Copy.id, Loan.returned_at.is_(None)).exists()
        total = db.session.scalar(db.select(db.func.count()).select_from(Copy).where(
            Copy.book_id == self.id))
        available = db.session.scalar(db.select(db.func.count()).select_from(Copy).where(
            Copy.book_id == self.id, ~active))
        return {
            "id": str(self.id),
            "title": self.title,
            "author": self.author,
            "description": self.description,
            "total_copies": total,
            "available_copies": available
        }
