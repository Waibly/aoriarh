"""Name workspaces still carrying their signup placeholder after their first organisation.

Revision ID: l1workspace01
Revises: k2m3socialdate01
"""

from alembic import op

revision = "l1workspace01"
down_revision = "k2m3socialdate01"
branch_labels = None
depends_on = None


def upgrade():
    # Only accounts never renamed by their owner ("Espace de <full name>")
    # and owning at least one organisation; the oldest organisation wins.
    op.execute(
        """
        UPDATE accounts AS a
        SET name = LEFT(
            (
                SELECT btrim(o.name)
                FROM organisations AS o
                WHERE o.account_id = a.id AND btrim(o.name) <> ''
                ORDER BY o.created_at ASC
                LIMIT 1
            ),
            255
        )
        FROM users AS u
        WHERE u.id = a.owner_id
          AND a.name = 'Espace de ' || u.full_name
          AND EXISTS (
              SELECT 1 FROM organisations AS o
              WHERE o.account_id = a.id AND btrim(o.name) <> ''
          )
        """
    )


def downgrade():
    # Irreversible data rename: the placeholder carries no information.
    pass
