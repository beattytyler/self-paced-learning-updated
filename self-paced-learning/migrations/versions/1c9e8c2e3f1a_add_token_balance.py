"""add token balance

Revision ID: 1c9e8c2e3f1a
Revises: b70c22dc926e
Create Date: 2026-01-24 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c9e8c2e3f1a"
down_revision = "b70c22dc926e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("token_balance", sa.Integer(), nullable=False, server_default="10"),
    )
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column("user", "token_balance", server_default=None)


def downgrade():
    op.drop_column("user", "token_balance")
