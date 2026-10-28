from uuid import uuid4

from werkzeug.security import generate_password_hash, check_password_hash

from db import db

ROLES = ("reader", "attendant", "admin")
STATUSES = ("pending", "approved", "rejected", "blocked")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    # Compatibilidade com os registros e o CLI antigos. A autorização usa role.
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    role = db.Column(db.String(20),
                     db.CheckConstraint("role IN ('reader', 'attendant', 'admin')", name="ck_users_role"),
                     nullable=False, default="reader", server_default="reader")
    status = db.Column(db.String(20),
                       db.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'blocked')", name="ck_users_status"),
                       nullable=False, default="approved", server_default="approved")
    auth_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def __init__(self, **kwargs):
        # Preserva User(..., is_admin=True), usado pelo CLI e pelos testes antigos.
        role = kwargs.get("role", "admin" if kwargs.get("is_admin") else "reader")
        kwargs.update(role=role, is_admin=role == "admin")
        super().__init__(**kwargs)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def can_manage_loans(self):
        return self.role in ("attendant", "admin")

    @property
    def member_id(self):
        from .user_member import UserMember
        return db.session.scalar(db.select(UserMember.member_id).where(
            UserMember.user_id == self.id))

    def to_dict(self):
        member_id = self.member_id
        return {
            "id": str(self.id), "name": self.name, "email": self.email,
            "role": self.role, "status": self.status,
            "is_admin": self.role == "admin", "active": self.active,
            "member_id": str(member_id) if member_id else None,
        }
