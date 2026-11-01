"""Create the initial Face Finder schema."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    search_status = postgresql.ENUM("awaiting_reference_selection", "uploading", "queued", "scanning", "reviewing", "saved", "failed", "cancelled", name="search_status", create_type=False)
    asset_status = postgresql.ENUM("uploaded", "indexed", "no_face", "matched", "not_matched", "failed", name="asset_status", create_type=False)
    match_decision = postgresql.ENUM("undecided", "accepted", "rejected", name="match_decision", create_type=False)
    search_status.create(op.get_bind(), checkfirst=True)
    asset_status.create(op.get_bind(), checkfirst=True)
    match_decision.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "searches",
        sa.Column("id", sa.UUID(), primary_key=True), sa.Column("status", search_status, nullable=False), sa.Column("sensitivity", sa.String(16), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False), sa.Column("expected_files", sa.Integer(), nullable=False), sa.Column("expected_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("uploaded_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("matched_files", sa.Integer(), nullable=False, server_default="0"), sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collection_name", sa.String(120)), sa.Column("model_name", sa.String(80), nullable=False), sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "reference_faces", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("search_id", sa.UUID(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False), sa.Column("crop_path", sa.String(500), nullable=False), sa.Column("embedding", postgresql.JSONB()),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reference_faces_search_id", "reference_faces", ["search_id"])
    op.create_table(
        "assets", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("search_id", sa.UUID(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_relative_path", sa.String(1000), nullable=False), sa.Column("original_name", sa.String(255), nullable=False), sa.Column("mime_type", sa.String(120)),
        sa.Column("byte_size", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("ingest_path", sa.String(500)), sa.Column("status", asset_status, nullable=False),
        sa.Column("error_message", sa.Text()), sa.Column("processed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("search_id", "source_relative_path", name="uq_asset_search_relative_path"),
    )
    op.create_index("ix_assets_search_id", "assets", ["search_id"])
    op.create_table(
        "faces", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("search_id", sa.UUID(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False), sa.Column("bbox", sa.JSON(), nullable=False), sa.Column("embedding", postgresql.JSONB(), nullable=False), sa.Column("quality_score", sa.Float(), nullable=False),
    )
    op.create_index("ix_faces_search_id", "faces", ["search_id"])
    op.create_index("ix_faces_asset_id", "faces", ["asset_id"])
    op.create_table(
        "matches", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("search_id", sa.UUID(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.UUID(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False), sa.Column("similarity", sa.Float(), nullable=False), sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("copy_path", sa.String(500), nullable=False), sa.Column("thumbnail_path", sa.String(500), nullable=False), sa.Column("decision", match_decision, nullable=False, server_default="undecided"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("search_id", "asset_id", name="uq_match_search_asset"),
    )
    op.create_index("ix_matches_search_id", "matches", ["search_id"])
    op.create_index("ix_matches_asset_id", "matches", ["asset_id"])
    op.create_table(
        "upload_batches", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("search_id", sa.UUID(), sa.ForeignKey("searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_batch_id", sa.String(64), nullable=False), sa.Column("file_count", sa.Integer(), nullable=False), sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("search_id", "client_batch_id", name="uq_batch_search_client_batch"),
    )
    op.create_index("ix_upload_batches_search_id", "upload_batches", ["search_id"])


def downgrade() -> None:
    op.drop_table("upload_batches")
    op.drop_table("matches")
    op.drop_table("faces")
    op.drop_table("assets")
    op.drop_table("reference_faces")
    op.drop_table("searches")
    sa.Enum(name="match_decision").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="asset_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="search_status").drop(op.get_bind(), checkfirst=True)
