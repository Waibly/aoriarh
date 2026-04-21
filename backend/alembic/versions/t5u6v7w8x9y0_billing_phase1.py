"""Billing phase 1: account status, stripe customer, subscriptions, add-ons, booster, monthly usage

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-04-21

Adds the billing foundations needed to sell commercial plans (Solo / Équipe /
Groupe) while keeping the existing technical plans (gratuit / invite / vip)
managed outside Stripe.

Changes to existing schema:
  - accounts.status: lifecycle flag (active / trialing / past_due /
    suspended / canceled), independent from plan.
  - accounts.stripe_customer_id: set only for commercial subscriptions.

New tables:
  - subscriptions: one row per active/past commercial subscription.
  - subscription_addons: paid add-ons attached to a subscription.
  - booster_purchases: one-shot +500 questions packs.
  - monthly_question_usage: aggregated question count per billing period,
    used by the quota middleware.

Data backfill:
  - All existing accounts → status = 'active'.
  - All accounts with plan='gratuit' → trial restarted to 14 days from
    the migration date (plan_assigned_at = now, plan_expires_at = now + 14d).
    Safe because we only have internal test accounts at this stage.
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "t5u6v7w8x9y0"
down_revision = "s4t5u6v7w8x9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- accounts: new columns ---------------------------------------------
    op.add_column(
        "accounts",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "stripe_customer_id",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_accounts_stripe_customer_id",
        "accounts",
        ["stripe_customer_id"],
    )

    # --- subscriptions -----------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("billing_cycle", sa.String(length=10), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_subscriptions_account_id", "subscriptions", ["account_id"])
    op.create_unique_constraint(
        "uq_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
    )

    # --- subscription_addons -----------------------------------------------
    op.create_table(
        "subscription_addons",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.UUID(),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("addon_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("stripe_subscription_item_id", sa.String(length=255), nullable=True),
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
    )
    op.create_index(
        "ix_subscription_addons_subscription_id",
        "subscription_addons",
        ["subscription_id"],
    )
    op.create_unique_constraint(
        "uq_subscription_addons_stripe_item_id",
        "subscription_addons",
        ["stripe_subscription_item_id"],
    )

    # --- booster_purchases -------------------------------------------------
    op.create_table(
        "booster_purchases",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "questions_purchased",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
        sa.Column(
            "questions_remaining",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_booster_purchases_account_id",
        "booster_purchases",
        ["account_id"],
    )
    op.create_unique_constraint(
        "uq_booster_purchases_stripe_payment_intent_id",
        "booster_purchases",
        ["stripe_payment_intent_id"],
    )

    # --- monthly_question_usage -------------------------------------------
    op.create_table(
        "monthly_question_usage",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "questions_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("quota_for_period", sa.Integer(), nullable=False),
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
        sa.UniqueConstraint(
            "account_id", "period_start", name="uq_usage_account_period"
        ),
    )
    op.create_index(
        "ix_monthly_question_usage_account_id",
        "monthly_question_usage",
        ["account_id"],
    )

    # --- data backfill -----------------------------------------------------
    # All existing accounts already have status='active' via the server_default
    # we added above, nothing more to do there.
    #
    # For gratuit accounts, restart the 14-day trial window from today so no
    # one gets immediately suspended at first quota check. Safe because this
    # project only has internal test accounts at the time of migration.
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=14)
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET plan_assigned_at = :now,
                plan_expires_at = :trial_end
            WHERE plan = 'gratuit'
            """
        ).bindparams(
            sa.bindparam("now", now),
            sa.bindparam("trial_end", trial_end),
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monthly_question_usage_account_id",
        table_name="monthly_question_usage",
    )
    op.drop_table("monthly_question_usage")

    op.drop_constraint(
        "uq_booster_purchases_stripe_payment_intent_id",
        "booster_purchases",
        type_="unique",
    )
    op.drop_index("ix_booster_purchases_account_id", table_name="booster_purchases")
    op.drop_table("booster_purchases")

    op.drop_constraint(
        "uq_subscription_addons_stripe_item_id",
        "subscription_addons",
        type_="unique",
    )
    op.drop_index(
        "ix_subscription_addons_subscription_id",
        table_name="subscription_addons",
    )
    op.drop_table("subscription_addons")

    op.drop_constraint(
        "uq_subscriptions_stripe_subscription_id",
        "subscriptions",
        type_="unique",
    )
    op.drop_index("ix_subscriptions_account_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_constraint(
        "uq_accounts_stripe_customer_id",
        "accounts",
        type_="unique",
    )
    op.drop_column("accounts", "stripe_customer_id")
    op.drop_column("accounts", "status")
