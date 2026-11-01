"""Add emotion to matches table.

Revision ID: 0004_add_emotion_to_matches
Revises: 0003_reference_face_selection
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_emotion_to_matches"
down_revision = "0003_reference_face_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("matches")}
    if "emotion" not in columns:
        op.add_column(
            "matches",
            sa.Column("emotion", sa.String(length=32), nullable=True, server_default="neutral"),
        )
        op.alter_column("matches", "emotion", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("matches")}
    if "emotion" in columns:
        op.drop_column("matches", "emotion")

