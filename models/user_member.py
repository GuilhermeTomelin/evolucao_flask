from db import db


class UserMember(db.Model):
    """Associação manual 1:1. Ausência de linha significa conta sem leitor."""
    __tablename__ = "user_members"

    user_id = db.Column(db.Uuid(as_uuid=True),
                        db.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    member_id = db.Column(db.Uuid(as_uuid=True),
                          db.ForeignKey("members.id", ondelete="RESTRICT"),
                          nullable=False, unique=True)
