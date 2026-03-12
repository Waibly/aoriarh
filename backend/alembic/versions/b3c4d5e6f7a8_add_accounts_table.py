"""add accounts table and link organisations

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create accounts table
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "plan",
            sa.String(20),
            nullable=False,
            server_default="gratuit",
        ),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.UniqueConstraint("owner_id"),
    )

    # 2. Add account_id column to organisations (nullable for now)
    op.add_column(
        "organisations",
        sa.Column("account_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organisations_account_id",
        "organisations",
        "accounts",
        ["account_id"],
        ["id"],
    )
    op.create_index("ix_organisations_account_id", "organisations", ["account_id"])

    # 3. Data migration: create an Account for each user, link orgs
    conn = op.get_bind()

    # Create an account for every existing user
    users = conn.execute(sa.text("SELECT id, full_name FROM users")).fetchall()
    for user in users:
        conn.execute(
            sa.text(
                "INSERT INTO accounts (id, name, owner_id, plan, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :owner_id, 'gratuit', now(), now())"
            ),
            {"name": f"Compte de {user.full_name}", "owner_id": user.id},
        )

    # Link each organisation to the account of its first manager
    orgs = conn.execute(sa.text("SELECT id FROM organisations")).fetchall()
    for org in orgs:
        manager = conn.execute(
            sa.text(
                "SELECT m.user_id FROM memberships m "
                "WHERE m.organisation_id = :org_id AND m.role_in_org = 'manager' "
                "ORDER BY m.created_at ASC LIMIT 1"
            ),
            {"org_id": org.id},
        ).fetchone()
        if manager:
            account = conn.execute(
                sa.text("SELECT id FROM accounts WHERE owner_id = :uid"),
                {"uid": manager.user_id},
            ).fetchone()
            if account:
                conn.execute(
                    sa.text(
                        "UPDATE organisations SET account_id = :aid WHERE id = :oid"
                    ),
                    {"aid": account.id, "oid": org.id},
                )


def downgrade() -> None:
    op.drop_index("ix_organisations_account_id", table_name="organisations")
    op.drop_constraint("fk_organisations_account_id", "organisations", type_="foreignkey")
    op.drop_column("organisations", "account_id")
    op.drop_table("accounts")
