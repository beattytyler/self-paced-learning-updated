"""fix cycles primary key for sqlite autoincrement

Revision ID: 6f3c1a2b9d7e
Revises: 18889e964c62
Create Date: 2026-02-02 19:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f3c1a2b9d7e"
down_revision = "18889e964c62"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite needs INTEGER PRIMARY KEY to auto-increment.
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    op.drop_table("cycles")

    op.create_table(
        "cycles",
        sa.Column("cycle_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("cycle_index", sa.SmallInteger(), nullable=False),
        sa.Column("quiz_id", sa.String(length=100), nullable=False),
        sa.Column("quiz_type", sa.String(length=20), nullable=False),
        sa.Column("quiz_submitted_at", sa.DateTime(), nullable=False),
        sa.Column("score_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("passed_threshold", sa.Boolean(), nullable=False),
        sa.Column("diagnosis_at", sa.DateTime(), nullable=True),
        sa.Column("diagnosis_model_name", sa.String(length=100), nullable=True),
        sa.Column("diagnosed_concept_ids", sa.JSON(), nullable=True),
        sa.Column("intervention_issued_at", sa.DateTime(), nullable=True),
        sa.Column("lesson_concept_ids", sa.JSON(), nullable=True),
        sa.Column("micro_lesson_count", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "quiz_type IN ('diagnostic','remedial')", name="ck_cycles_quiz_type"
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.attempt_id"]),
        sa.UniqueConstraint("attempt_id", "cycle_index", name="uq_cycle_attempt_index"),
    )

    with op.batch_alter_table("cycles", schema=None) as batch_op:
        batch_op.create_index("idx_cycles_attempt_id", ["attempt_id"], unique=False)
        batch_op.create_index("idx_cycles_quiz_type", ["quiz_type"], unique=False)
        batch_op.create_index("idx_cycles_submitted_at", ["quiz_submitted_at"], unique=False)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    op.drop_table("cycles")

    op.create_table(
        "cycles",
        sa.Column("cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("cycle_index", sa.SmallInteger(), nullable=False),
        sa.Column("quiz_id", sa.String(length=100), nullable=False),
        sa.Column("quiz_type", sa.String(length=20), nullable=False),
        sa.Column("quiz_submitted_at", sa.DateTime(), nullable=False),
        sa.Column("score_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("passed_threshold", sa.Boolean(), nullable=False),
        sa.Column("diagnosis_at", sa.DateTime(), nullable=True),
        sa.Column("diagnosis_model_name", sa.String(length=100), nullable=True),
        sa.Column("diagnosed_concept_ids", sa.JSON(), nullable=True),
        sa.Column("intervention_issued_at", sa.DateTime(), nullable=True),
        sa.Column("lesson_concept_ids", sa.JSON(), nullable=True),
        sa.Column("micro_lesson_count", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "quiz_type IN ('diagnostic','remedial')", name="ck_cycles_quiz_type"
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.attempt_id"]),
        sa.PrimaryKeyConstraint("cycle_id"),
        sa.UniqueConstraint("attempt_id", "cycle_index", name="uq_cycle_attempt_index"),
    )

    with op.batch_alter_table("cycles", schema=None) as batch_op:
        batch_op.create_index("idx_cycles_attempt_id", ["attempt_id"], unique=False)
        batch_op.create_index("idx_cycles_quiz_type", ["quiz_type"], unique=False)
        batch_op.create_index("idx_cycles_submitted_at", ["quiz_submitted_at"], unique=False)
