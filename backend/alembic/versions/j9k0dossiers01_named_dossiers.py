"""Named dossiers and private document scopes; preserve all legacy visibility."""

from alembic import op
import sqlalchemy as sa

revision = "j9k0dossiers01"
down_revision = "i8j9chronology01"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("case_files", "conversation_id", nullable=True)
    op.create_table(
        "dossiers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organisation_id", sa.Uuid(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "case_file_id", sa.Uuid(), sa.ForeignKey("case_files.id"), nullable=False, unique=True
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("creation_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for col in ("organisation_id", "user_id"):
        op.create_index(f"ix_dossiers_{col}", "dossiers", [col])
    op.add_column("conversations", sa.Column("dossier_id", sa.Uuid(), sa.ForeignKey("dossiers.id")))
    op.create_index("ix_conversations_dossier_id", "conversations", ["dossier_id"])
    op.add_column("conversations", sa.Column("recent_hidden_at", sa.DateTime(timezone=True)))
    for col, target in (
        ("private_dossier_id", "dossiers.id"),
        ("private_conversation_id", "conversations.id"),
    ):
        op.add_column("documents", sa.Column(col, sa.Uuid(), sa.ForeignKey(target)))
        op.create_index(f"ix_documents_{col}", "documents", [col])
    op.add_column("documents", sa.Column("retired_at", sa.DateTime(timezone=True)))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM dossiers")).scalar():
        raise RuntimeError(
            "Dossiers présents : retour arrière dédié requis pour préserver les données privées"
        )
    if bind.execute(
        sa.text("SELECT count(*) FROM documents WHERE private_conversation_id IS NOT NULL")
    ).scalar():
        raise RuntimeError("Documents privés présents : restauration contrôlée requise")
    for col in ("retired_at", "private_conversation_id", "private_dossier_id"):
        op.drop_column("documents", col)
    op.drop_column("conversations", "recent_hidden_at")
    op.drop_column("conversations", "dossier_id")
    op.drop_table("dossiers")
    op.alter_column("case_files", "conversation_id", nullable=False)
