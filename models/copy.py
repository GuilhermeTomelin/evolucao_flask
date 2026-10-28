from uuid import uuid4

from db import db


class Copy(db.Model):
    __tablename__ = "copies"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    book_id = db.Column(db.Uuid(as_uuid=True),
                        db.ForeignKey("books.id", ondelete="RESTRICT"), nullable=False, index=True)
    inventory_code = db.Column(db.String(100), nullable=False, unique=True)

    def to_dict(self):
        from .loan import Loan
        occupied = db.session.scalar(db.select(Loan.id).where(
            Loan.copy_id == self.id, Loan.returned_at.is_(None)).limit(1))
        return {
            "id": str(self.id), "book_id": str(self.book_id),
            "inventory_code": self.inventory_code, "available": occupied is None
        }
