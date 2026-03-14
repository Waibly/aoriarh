"""Add API usage tracking tables

Revision ID: j5k6l7m8n9o0
Revises: i4d5e6f7g8h9
Create Date: 2026-03-14

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "j5k6l7m8n9o0"
down_revision = "i4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # API pricing table
    op.create_table(
        "api_pricing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "price_input_per_million",
            sa.Numeric(10, 4),
            nullable=False,
            comment="USD per 1M input tokens",
        ),
        sa.Column(
            "price_output_per_million",
            sa.Numeric(10, 4),
            nullable=True,
            comment="USD per 1M output tokens (null for embeddings)",
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_api_pricing_provider_model", "api_pricing", ["provider", "model"]
    )

    # Seed current pricing
    op.execute("""
        INSERT INTO api_pricing (id, provider, model, price_input_per_million, price_output_per_million)
        VALUES
            (gen_random_uuid(), 'openai', 'gpt-5-mini', 0.2500, 2.0000),
            (gen_random_uuid(), 'openai', 'gpt-4o-mini', 0.1500, 0.6000),
            (gen_random_uuid(), 'voyageai', 'voyage-law-2', 0.1200, NULL),
            (gen_random_uuid(), 'voyageai', 'rerank-2', 0.0500, NULL)
    """)

    # API usage logs table
    op.create_table(
        "api_usage_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "operation_type",
            sa.String(50),
            nullable=False,
            comment="condense | expand | generate | embedding | rerank",
        ),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("organisation_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "context_type",
            sa.String(30),
            nullable=False,
            comment="question | ingestion",
        ),
        sa.Column("context_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_api_usage_logs_created_at", "api_usage_logs", ["created_at"]
    )
    op.create_index(
        "ix_api_usage_logs_organisation_id", "api_usage_logs", ["organisation_id"]
    )
    op.create_index(
        "ix_api_usage_logs_user_id", "api_usage_logs", ["user_id"]
    )
    op.create_index(
        "ix_api_usage_logs_context", "api_usage_logs", ["context_type", "context_id"]
    )


def downgrade() -> None:
    op.drop_table("api_usage_logs")
    op.drop_table("api_pricing")
