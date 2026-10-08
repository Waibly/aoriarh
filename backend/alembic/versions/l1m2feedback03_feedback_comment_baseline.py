"""Complete fresh databases with the existing message feedback comment field.

Some deployed databases already contain this column. Never remove their data
on downgrade: older application versions also use this existing model field.
"""
from alembic import op
import sqlalchemy as sa

revision = "l1m2feedback03"
down_revision = "k0l1dossiers02"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("messages")}
    if "feedback_comment" not in columns:
        op.add_column("messages", sa.Column("feedback_comment", sa.Text(), nullable=True))


def downgrade():
    # Compatibility field predates Dossiers; preserve existing user feedback.
    pass
