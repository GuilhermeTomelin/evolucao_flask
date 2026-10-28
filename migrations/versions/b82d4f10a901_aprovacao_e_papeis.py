"""Etapa A: aprovação e papéis sem reconstruir tabelas existentes."""
from alembic import op
import sqlalchemy as sa

revision = "b82d4f10a901"
down_revision = "a671c92d4e10"
branch_labels = None
depends_on = None


def upgrade():
    # ADD COLUMN preserva users e suas referências. Não usamos batch/recreate.
    op.add_column("users", sa.Column(
        "role", sa.String(20),
        sa.CheckConstraint("role IN ('reader', 'attendant', 'admin')", name="ck_users_role"),
        nullable=False, server_default="reader"))
    op.add_column("users", sa.Column(
        "status", sa.String(20),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'blocked')", name="ck_users_status"),
        nullable=False, server_default="approved"))
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.execute(sa.text("UPDATE users SET role = CASE WHEN is_admin THEN 'admin' ELSE 'reader' END"))
    op.execute(sa.text("UPDATE users SET status = CASE WHEN active THEN 'approved' ELSE 'blocked' END"))
    # is_admin, active, senhas, IDs, vínculos e histórico permanecem intactos.


def downgrade():
    raise RuntimeError(
        "Downgrade da etapa A bloqueado: remover aprovação e papéis pode restaurar "
        "acessos indevidos. Planeje a restauração da cópia de segurança."
    )
