from datetime import datetime, timezone
from uuid import uuid4

from db import db


def utc_now():
    # SQLite armazena datetime sem fuso; todos os valores internos são UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(value):
    return value.isoformat(timespec="microseconds") + "Z" if value else None


class Loan(db.Model):
    __tablename__ = "loans"
    __table_args__ = (
        db.Index("uq_loans_active_copy", "copy_id", unique=True,
                 sqlite_where=db.text("returned_at IS NULL"),
                 postgresql_where=db.text("returned_at IS NULL")),
        db.CheckConstraint("due_at >= borrowed_at", name="ck_loans_due"),
        db.CheckConstraint("returned_at IS NULL OR returned_at >= borrowed_at",
                           name="ck_loans_return"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    copy_id = db.Column(db.Uuid(as_uuid=True),
                        db.ForeignKey("copies.id", ondelete="RESTRICT"), nullable=False)
    member_id = db.Column(db.Uuid(as_uuid=True),
                          db.ForeignKey("members.id", ondelete="RESTRICT"),
                          nullable=False, index=True)
    borrowed_at = db.Column(db.DateTime, nullable=False)
    due_at = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        from .copy import Copy
        from .book import Book
        from .member import Member
        copy = db.session.get(Copy, self.copy_id)
        book = db.session.get(Book, copy.book_id)
        member = db.session.get(Member, self.member_id)
        return {
            "id": str(self.id), "copy_id": str(self.copy_id),
            "member_id": str(self.member_id), "member_name": member.name,
            "book_id": str(book.id), "book_title": book.title,
            "inventory_code": copy.inventory_code,
            "borrowed_at": iso_utc(self.borrowed_at), "due_at": iso_utc(self.due_at),
            "returned_at": iso_utc(self.returned_at),
            "overdue": self.returned_at is None and self.due_at < utc_now(),
        }
