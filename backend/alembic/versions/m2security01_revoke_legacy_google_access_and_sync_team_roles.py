"""Revoke legacy Google/password access and apply existing team roles.

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
    # Existing access grants must match the team's role just like newly created
    # grants. Direct organisation memberships without a team grant are untouched.
    op.execute(
        """
        UPDATE memberships
        SET role_in_org = (
            SELECT am.role_in_org FROM account_members AS am
            JOIN organisations AS o ON o.account_id = am.account_id
            WHERE o.id = memberships.organisation_id
              AND am.user_id = memberships.user_id
        )
        WHERE EXISTS (
            SELECT 1 FROM account_members AS am
            JOIN organisations AS o ON o.account_id = am.account_id
            WHERE o.id = memberships.organisation_id
              AND am.user_id = memberships.user_id
              AND am.role_in_org <> memberships.role_in_org
        )
        """
    )


def downgrade():
    # Never restore compromised credentials, revoked sessions or obsolete rights.
    pass
