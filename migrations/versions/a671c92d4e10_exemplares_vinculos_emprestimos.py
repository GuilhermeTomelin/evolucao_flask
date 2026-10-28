"""Exemplares, vínculos explícitos e empréstimos; sem preencher dados existentes."""
from alembic import op
import sqlalchemy as sa

revision = "a671c92d4e10"
down_revision = "54ad476dee56"
branch_labels = None
depends_on = None


def upgrade():
    # Tabelas novas: não recria users, members ou books nem associa por e-mail.
    op.create_table(
        "user_members",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("member_id"),
    )
    op.create_table(
        "copies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_code", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_code"),
    )
    op.create_index("ix_copies_book_id", "copies", ["book_id"])
    op.create_table(
        "loans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("copy_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("borrowed_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["copy_id"], ["copies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("due_at >= borrowed_at", name="ck_loans_due"),
        sa.CheckConstraint("returned_at IS NULL OR returned_at >= borrowed_at",
                           name="ck_loans_return"),
    )
    op.create_index("ix_loans_member_id", "loans", ["member_id"])
    op.create_index("uq_loans_active_copy", "loans", ["copy_id"], unique=True,
                    sqlite_where=sa.text("returned_at IS NULL"),
                    postgresql_where=sa.text("returned_at IS NULL"))


def downgrade():
    # Reverter tabelas preenchidas apagaria vínculos ou histórico: recusar.
    connection = op.get_bind()
    for table in ("loans", "copies", "user_members"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("Downgrade bloqueado: existem exemplares, vínculos ou histórico.")
    op.drop_index("uq_loans_active_copy", table_name="loans")
    op.drop_index("ix_loans_member_id", table_name="loans")
    op.drop_table("loans")
    op.drop_index("ix_copies_book_id", table_name="copies")
    op.drop_table("copies")
    op.drop_table("user_members")
