"""Revoke legacy Google/password access while preserving organisation role overrides.

Revision ID: m2security01
Revises: l1workspace01
"""

from alembic import op

revision = "m2security01"
down_revision = "l1workspace01"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy Google links kept the password and sessions created before the
    # verified email owner signed in. These sessions cannot be distinguished
    # from legitimate Google sessions, so affected users must sign in again.
    op.execute(
        """
        UPDATE auth_sessions SET revoked = true
        WHERE user_id IN (
            SELECT id FROM users
            WHERE hashed_password IS NOT NULL
              AND (auth_provider = 'google' OR google_sub IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        UPDATE users SET hashed_password = NULL, auth_provider = 'google'
        WHERE hashed_password IS NOT NULL
          AND (auth_provider = 'google' OR google_sub IS NOT NULL)
        """
    )


def downgrade():
    # Never restore compromised credentials or revoked sessions.
    pass
