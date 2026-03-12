"""add account_members table and account-level invitations

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create account_members table
    op.create_table(
        "account_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_in_org", sa.String(20), nullable=False, server_default="user"),
        sa.Column("access_all", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("selected_org_ids", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "user_id", name="uq_account_user"),
    )

    # 2. Make invitations.organisation_id nullable
    op.alter_column(
        "invitations",
        "organisation_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    # 3. Add account-level columns to invitations
    op.add_column(
        "invitations",
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("access_all", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "invitations",
        sa.Column("selected_org_ids", sa.Text(), nullable=True),
    )

    # 4. Data migration: create AccountMembers from existing Memberships
    # For each user who is a member of an org belonging to an account,
    # create an AccountMember with access_all=false
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("""
            SELECT DISTINCT m.user_id, o.account_id, m.role_in_org
            FROM memberships m
            JOIN organisations o ON o.id = m.organisation_id
            JOIN accounts a ON a.id = o.account_id
            WHERE o.account_id IS NOT NULL
              AND m.user_id != a.owner_id
        """)
    ).fetchall()

    for user_id, account_id, role_in_org in rows:
        # Collect which org_ids this user is a member of within this account
        org_rows = conn.execute(
            sa.text("""
                SELECT m.organisation_id
                FROM memberships m
                JOIN organisations o ON o.id = m.organisation_id
                WHERE m.user_id = :user_id AND o.account_id = :account_id
            """),
            {"user_id": user_id, "account_id": account_id},
        ).fetchall()

        # Check if user has all orgs of this account
        total_orgs = conn.execute(
            sa.text("SELECT count(*) FROM organisations WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()

        has_all = len(org_rows) == total_orgs
        org_ids_json = None if has_all else str([str(r[0]) for r in org_rows]).replace("'", '"')

        conn.execute(
            sa.text("""
                INSERT INTO account_members (id, account_id, user_id, role_in_org, access_all, selected_org_ids, created_at, updated_at)
                VALUES (gen_random_uuid(), :account_id, :user_id, :role_in_org, :access_all, :selected_org_ids, now(), now())
                ON CONFLICT (account_id, user_id) DO NOTHING
            """),
            {
                "account_id": account_id,
                "user_id": user_id,
                "role_in_org": role_in_org,
                "access_all": has_all,
                "selected_org_ids": org_ids_json,
            },
        )


def downgrade() -> None:
    op.drop_column("invitations", "selected_org_ids")
    op.drop_column("invitations", "access_all")
    op.drop_column("invitations", "account_id")
    op.alter_column(
        "invitations",
        "organisation_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_table("account_members")
