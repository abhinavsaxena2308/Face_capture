"""Store face embeddings as JSONB instead of pgvector columns."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_jsonb_embeddings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns_by_table = {
        table: {column["name"]: column["type"] for column in sa.inspect(bind).get_columns(table)}
        for table in ("reference_faces", "faces")
    }

    op.execute("DROP INDEX IF EXISTS ix_faces_embedding_cosine")
    for table, columns in columns_by_table.items():
        embedding_type = str(columns["embedding"]).lower()
        if "vector" in embedding_type:
            op.alter_column(
                table,
                "embedding",
                type_=postgresql.JSONB(),
                postgresql_using="embedding::text::jsonb",
            )
        elif "jsonb" not in embedding_type:
            raise RuntimeError(f"Unsupported {table}.embedding type: {columns['embedding']}")


def downgrade() -> None:
    """Keep JSONB: the current initial schema also defines embeddings as JSONB."""
    pass
