"""Add the selected-reference flag to existing databases."""

from alembic import op
import sqlalchemy as sa

revision = "0003_reference_face_selection"
down_revision = "0002_jsonb_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("reference_faces")}
    if "is_selected" not in columns:
        op.add_column(
            "reference_faces",
            sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("reference_faces", "is_selected", server_default=None)


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("reference_faces")}
    if "is_selected" in columns:
        op.drop_column("reference_faces", "is_selected")
