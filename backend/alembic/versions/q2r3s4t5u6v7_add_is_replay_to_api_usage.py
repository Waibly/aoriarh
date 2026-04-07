"""Add is_replay flag to api_usage_logs

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-04-08

Adds a boolean flag on api_usage_logs to mark API calls executed via the
admin Quality Sandbox. These calls must be excluded from production cost
metrics so the admin can replay questions without polluting client billing.
"""

import sqlalchemy as sa
from alembic import op

revision = "q2r3s4t5u6v7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_usage_logs",
        sa.Column(
            "is_replay",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_api_usage_logs_is_replay",
        "api_usage_logs",
        ["is_replay"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_usage_logs_is_replay", table_name="api_usage_logs")
    op.drop_column("api_usage_logs", "is_replay")
