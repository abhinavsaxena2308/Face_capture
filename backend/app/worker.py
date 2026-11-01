from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import Asset, AssetStatus, Face, Match, ReferenceFace, Search, SearchStatus
from app.services.matching import cosine_scores
from app.services.storage import StorageService
from app.services.vision import VisionService


settings = get_settings()
storage = StorageService(settings)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def requeue_stale_jobs(session: Session) -> None:
    stale_before = utcnow() - timedelta(minutes=settings.stale_job_minutes)
    session.execute(
        update(Search)
        .where(Search.status == SearchStatus.SCANNING, Search.heartbeat_at < stale_before)
        .values(status=SearchStatus.QUEUED, error_message="Worker restart detected; resuming scan.")
    )
    session.commit()


def claim_next_search(session: Session) -> uuid.UUID | None:
    search = session.scalar(
        select(Search)
        .where(Search.status == SearchStatus.QUEUED)
        .order_by(Search.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not search:
        return None
    now = utcnow()
    search.status = SearchStatus.SCANNING
    search.started_at = search.started_at or now
    search.heartbeat_at = now
    search.error_message = None
    session.commit()
    return search.id


def index_assets(session: Session, search: Search, vision: VisionService) -> None:
    assets = session.scalars(
        select(Asset).where(Asset.search_id == search.id, Asset.status == AssetStatus.UPLOADED).order_by(Asset.source_relative_path)
    ).all()
    for asset in assets:
        try:
            if not asset.ingest_path:
                raise RuntimeError("The temporary upload file is missing.")
            image = vision.read_image(storage.absolute_path(asset.ingest_path))
            detected = vision.detect(image, settings.min_target_face_pixels)
            if not detected:
                asset.status = AssetStatus.NO_FACE
            else:
                for face in detected:
                    session.add(Face(
                        search_id=search.id,
                        asset_id=asset.id,
                        bbox=face.bbox,
                        embedding=vision.embedding(image, face),
                        quality_score=face.score,
                    ))
                asset.status = AssetStatus.INDEXED
        except Exception as error:
            asset.status = AssetStatus.FAILED
            asset.error_message = str(error)[:2000]
            search.failed_files += 1
        finally:
            asset.processed_at = utcnow()
            search.processed_files += 1
            search.heartbeat_at = utcnow()
            session.commit()


def create_matches_and_cleanup(session: Session, search: Search) -> None:
    reference = session.scalar(select(ReferenceFace).where(ReferenceFace.search_id == search.id, ReferenceFace.is_selected.is_(True)))
    if not reference or reference.embedding is None:
        raise RuntimeError("The selected reference embedding is missing.")

    reference_embedding = reference.embedding
    best_by_asset: dict[uuid.UUID, tuple[uuid.UUID, float, dict]] = {}
    rows = session.execute(
        select(
            Face.id.label("face_id"),
            Face.asset_id.label("asset_id"),
            Face.embedding.label("embedding"),
            Face.bbox.label("bbox"),
        )
        .where(Face.search_id == search.id)
        .order_by(Face.id)
    ).yield_per(512)
    while batch := rows.fetchmany(512):
        scores = cosine_scores(reference_embedding, [row.embedding for row in batch])
        for row, score_value in zip(batch, scores, strict=True):
            score = float(score_value)
            current_best = best_by_asset.get(row.asset_id)
            if current_best is None or score > current_best[1]:
                best_by_asset[row.asset_id] = (row.face_id, score, row.bbox)

    assets = {
        asset.id: asset
        for asset in session.scalars(select(Asset).where(Asset.search_id == search.id)).all()
    }
    for asset_id, (_, score, bbox) in best_by_asset.items():
        asset = assets.get(asset_id)
        if asset is None:
            raise RuntimeError(f"Face record references missing asset {asset_id}.")
        if score >= search.threshold:
            match_id = uuid.uuid4()
            if not asset.ingest_path:
                asset.status = AssetStatus.FAILED
                asset.error_message = "Temporary upload file was removed before result copy."
                search.failed_files += 1
                continue
            emotion = (bbox.get("emotion") if isinstance(bbox, dict) else "neutral") or "neutral"
            match = Match(
                id=match_id,
                search_id=search.id,
                asset_id=asset.id,
                similarity=score,
                bbox=bbox,
                emotion=emotion,
                copy_path=storage.copy_match(search.id, match_id, asset.ingest_path, asset.original_name),
                thumbnail_path=storage.create_thumbnail(search.id, match_id, asset.ingest_path),
            )
            session.add(match)
            asset.status = AssetStatus.MATCHED
            search.matched_files += 1
        else:
            asset.status = AssetStatus.NOT_MATCHED

    # Face vectors were needed only for this search. Results retain score and box, not the target biometric vectors.
    session.execute(delete(Face).where(Face.search_id == search.id))
    reference.embedding = None
    for asset in session.scalars(select(Asset).where(Asset.search_id == search.id)).all():
        storage.delete_ingest_file(asset.ingest_path)
        asset.ingest_path = None
    search.status = SearchStatus.REVIEWING
    search.completed_at = utcnow()
    search.heartbeat_at = utcnow()
    session.commit()


def process_search(search_id: uuid.UUID, vision: VisionService) -> None:
    with SessionLocal() as session:
        search = session.get(Search, search_id)
        if not search or search.status != SearchStatus.SCANNING:
            return
        try:
            index_assets(session, search, vision)
            create_matches_and_cleanup(session, search)
        except Exception as error:
            search.status = SearchStatus.FAILED
            search.error_message = str(error)[:2000]
            search.heartbeat_at = utcnow()
            session.commit()


def run() -> None:
    settings.ensure_directories()
    vision = VisionService(settings)
    while True:
        with SessionLocal() as session:
            requeue_stale_jobs(session)
            search_id = claim_next_search(session)
        if search_id:
            process_search(search_id, vision)
        else:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
