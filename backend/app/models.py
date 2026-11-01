from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_class]


class SearchStatus(str, enum.Enum):
    AWAITING_REFERENCE_SELECTION = "awaiting_reference_selection"
    UPLOADING = "uploading"
    QUEUED = "queued"
    SCANNING = "scanning"
    REVIEWING = "reviewing"
    SAVED = "saved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    INDEXED = "indexed"
    NO_FACE = "no_face"
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    FAILED = "failed"


class MatchDecision(str, enum.Enum):
    UNDECIDED = "undecided"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[SearchStatus] = mapped_column(
        Enum(SearchStatus, name="search_status", values_callable=enum_values), nullable=False
    )
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    expected_files: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collection_name: Mapped[str | None] = mapped_column(String(120))
    model_name: Mapped[str] = mapped_column(String(80), nullable=False, default="YuNet + SFace")
    model_version: Mapped[str] = mapped_column(String(80), nullable=False, default="2023mar / 2021dec")
    target_emotion: Mapped[str | None] = mapped_column(String(32), nullable=True, default="all")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReferenceFace(Base):
    __tablename__ = "reference_faces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    crop_path: Mapped[str] = mapped_column(String(500), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    is_selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("search_id", "source_relative_path", name="uq_asset_search_relative_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    source_relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status", values_callable=enum_values), nullable=False, default=AssetStatus.UPLOADED
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("search_id", "asset_id", name="uq_match_search_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    copy_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str] = mapped_column(String(500), nullable=False)
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True, default="neutral")
    decision: Mapped[MatchDecision] = mapped_column(
        Enum(MatchDecision, name="match_decision", values_callable=enum_values),
        nullable=False,
        default=MatchDecision.UNDECIDED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UploadBatch(Base):
    __tablename__ = "upload_batches"
    __table_args__ = (UniqueConstraint("search_id", "client_batch_id", name="uq_batch_search_client_batch"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    client_batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
