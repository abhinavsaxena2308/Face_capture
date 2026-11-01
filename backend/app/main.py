from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_session
from app.models import Asset, AssetStatus, Match, MatchDecision, ReferenceFace, Search, SearchStatus, UploadBatch
from app.schemas import MatchDecisionUpdate, ReferenceFaceSelection, SaveCollectionRequest
from app.services.storage import StorageService
from app.services.vision import VisionService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    app.state.storage = StorageService(settings)
    app.state.vision = None
    yield


app = FastAPI(title="Face Finder API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

DbSession = Annotated[Session, Depends(get_session)]


def storage(request: Request) -> StorageService:
    return request.app.state.storage


def vision(request: Request) -> VisionService:
    if request.app.state.vision is None:
        request.app.state.vision = VisionService(settings)
    return request.app.state.vision


def serialize_search(search: Search) -> dict:
    return {
        "id": str(search.id),
        "status": search.status.value,
        "sensitivity": search.sensitivity,
        "threshold": search.threshold,
        "expectedFiles": search.expected_files,
        "expectedBytes": search.expected_bytes,
        "uploadedFiles": search.uploaded_files,
        "uploadedBytes": search.uploaded_bytes,
        "processedFiles": search.processed_files,
        "matchedFiles": search.matched_files,
        "failedFiles": search.failed_files,
        "collectionName": search.collection_name,
        "errorMessage": search.error_message,
        "createdAt": search.created_at,
        "completedAt": search.completed_at,
    }


def get_search_or_404(session: Session, search_id: uuid.UUID) -> Search:
    search = session.get(Search, search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found.")
    return search


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "face-finder-api"}


@app.get("/model-info")
def model_info() -> dict:
    return {
        "detector": settings.yunet_model,
        "recognizer": settings.sface_model,
        "mode": "cpu",
        "thresholds": {"broad": settings.match_threshold_broad, "balanced": settings.match_threshold_balanced, "strict": settings.match_threshold_strict},
    }


@app.post("/api/v1/searches", status_code=status.HTTP_201_CREATED)
async def create_search(
    request: Request,
    reference: Annotated[UploadFile, File(...)],
    expected_files: Annotated[int, Form(...)],
    expected_bytes: Annotated[int, Form(...)],
    sensitivity: Annotated[Literal["broad", "balanced", "strict"], Form()] = "balanced",
    session: Session = Depends(get_session),
) -> dict:
    if expected_files < 1 or expected_files > settings.max_collection_files:
        raise HTTPException(status_code=400, detail=f"Choose between 1 and {settings.max_collection_files} images.")
    if expected_bytes < 1:
        raise HTTPException(status_code=400, detail="Expected collection size must be positive.")
    store = storage(request)
    store.ensure_capacity(expected_bytes)
    name = reference.filename or "reference"
    if PurePosixPath(name).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        raise HTTPException(status_code=415, detail="Reference must be a JPG, PNG, WEBP, HEIC, or HEIF image.")

    # The reference is read into a temporary app-owned file only long enough for detection.
    temporary_id = uuid.uuid4()
    relative, _, _ = await store.write_upload(temporary_id, uuid.uuid4(), name, reference)
    temporary_path = store.absolute_path(relative)
    try:
        image = vision(request).read_image(temporary_path)
        detected = vision(request).detect(image, settings.min_reference_face_pixels)
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"Could not read the reference image: {error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)
        temporary_path.parent.rmdir() if temporary_path.parent.exists() and not any(temporary_path.parent.iterdir()) else None

    if not detected:
        raise HTTPException(status_code=422, detail="No clear face was found in the reference image.")

    search = Search(
        status=SearchStatus.AWAITING_REFERENCE_SELECTION,
        sensitivity=sensitivity,
        threshold=settings.threshold_for(sensitivity),
        expected_files=expected_files,
        expected_bytes=expected_bytes,
    )
    session.add(search)
    session.flush()
    candidates = []
    for face in detected:
        crop = vision(request).crop(image, face)
        if crop.size == 0:
            continue
        reference_face = ReferenceFace(
            search_id=search.id,
            bbox=face.bbox,
            crop_path="pending",
            embedding=vision(request).embedding(image, face),
        )
        session.add(reference_face)
        session.flush()
        reference_face.crop_path = store.write_reference_crop(search.id, reference_face.id, crop)
        candidates.append({
            "id": str(reference_face.id),
            "bbox": reference_face.bbox,
            "previewUrl": f"/api/v1/media/reference-faces/{reference_face.id}",
        })
    if not candidates:
        session.rollback()
        store.remove_search_files(search.id)
        raise HTTPException(status_code=422, detail="No usable reference face was found.")
    session.commit()
    return {"search": serialize_search(search), "referenceFaces": candidates}


@app.post("/api/v1/searches/{search_id}/reference-face")
def select_reference_face(search_id: uuid.UUID, body: ReferenceFaceSelection, session: DbSession) -> dict:
    search = get_search_or_404(session, search_id)
    if search.status != SearchStatus.AWAITING_REFERENCE_SELECTION:
        raise HTTPException(status_code=409, detail="The reference face has already been selected.")
    selected = session.scalar(select(ReferenceFace).where(ReferenceFace.id == body.reference_face_id, ReferenceFace.search_id == search.id))
    if not selected:
        raise HTTPException(status_code=404, detail="Reference face candidate not found.")
    session.query(ReferenceFace).filter(ReferenceFace.search_id == search.id).update({ReferenceFace.is_selected: False})
    selected.is_selected = True
    search.status = SearchStatus.UPLOADING
    session.commit()
    return {"search": serialize_search(search)}


@app.post("/api/v1/searches/{search_id}/batches")
async def upload_batch(
    search_id: uuid.UUID,
    request: Request,
    client_batch_id: Annotated[str, Form(...)],
    manifest: Annotated[str, Form(...)],
    files: Annotated[list[UploadFile], File(...)],
    session: Session = Depends(get_session),
) -> dict:
    search = get_search_or_404(session, search_id)
    if search.status != SearchStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="This search is not accepting uploads.")
    if not client_batch_id or len(client_batch_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid upload batch identifier.")
    existing = session.scalar(select(UploadBatch).where(UploadBatch.search_id == search.id, UploadBatch.client_batch_id == client_batch_id))
    if existing:
        return {"accepted": existing.file_count, "uploadedFiles": search.uploaded_files, "idempotent": True}
    try:
        entries = json.loads(manifest)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Upload manifest is invalid JSON.") from error
    if not isinstance(entries, list) or len(entries) != len(files) or not files or len(files) > settings.max_batch_files:
        raise HTTPException(status_code=400, detail="Upload manifest and batch files do not match.")

    store = storage(request)
    stored: list[Asset] = []
    total_bytes = 0
    try:
        for index, upload in enumerate(files):
            item = entries[index]
            if not isinstance(item, dict) or not isinstance(item.get("relativePath"), str):
                raise HTTPException(status_code=400, detail="Each upload manifest item needs a relativePath.")
            relative_path = store.validate_relative_path(item["relativePath"])
            asset = Asset(
                search_id=search.id,
                source_relative_path=relative_path,
                original_name=PurePosixPath(relative_path).name,
                mime_type=upload.content_type,
                byte_size=0,
                sha256="pending",
                ingest_path=None,
            )
            session.add(asset)
            session.flush()
            ingest_path, size, sha256 = await store.write_upload(search.id, asset.id, relative_path, upload)
            asset.ingest_path = ingest_path
            asset.byte_size = size
            asset.sha256 = sha256
            total_bytes += size
            stored.append(asset)
        if total_bytes > settings.max_batch_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="The upload batch exceeds its configured size limit.")
        session.add(UploadBatch(search_id=search.id, client_batch_id=client_batch_id, file_count=len(stored), byte_size=total_bytes))
        search.uploaded_files += len(stored)
        search.uploaded_bytes += total_bytes
        if search.uploaded_files > search.expected_files:
            raise HTTPException(status_code=400, detail="More files were uploaded than declared for this search.")
        session.commit()
    except Exception:
        session.rollback()
        for asset in stored:
            store.delete_ingest_file(asset.ingest_path)
        raise
    return {"accepted": len(stored), "uploadedFiles": search.uploaded_files, "uploadedBytes": search.uploaded_bytes, "idempotent": False}


@app.post("/api/v1/searches/{search_id}/finalize")
def finalize_upload(search_id: uuid.UUID, session: DbSession) -> dict:
    search = get_search_or_404(session, search_id)
    if search.status != SearchStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="This search cannot be finalized in its current state.")
    if search.uploaded_files != search.expected_files:
        raise HTTPException(status_code=409, detail=f"Only {search.uploaded_files} of {search.expected_files} images have been uploaded.")
    search.status = SearchStatus.QUEUED
    session.commit()
    return {"search": serialize_search(search)}


@app.get("/api/v1/searches/{search_id}")
def get_search(search_id: uuid.UUID, session: DbSession) -> dict:
    return {"search": serialize_search(get_search_or_404(session, search_id))}


@app.get("/api/v1/searches/{search_id}/matches")
def list_matches(search_id: uuid.UUID, cursor: uuid.UUID | None = None, limit: int = 48, decision: MatchDecision | None = None, session: Session = Depends(get_session)) -> dict:
    search = get_search_or_404(session, search_id)
    limit = max(1, min(limit, 100))
    query: Select = select(Match, Asset).join(Asset, Asset.id == Match.asset_id).where(Match.search_id == search.id)
    if decision:
        query = query.where(Match.decision == decision)
    if cursor:
        cursor_item = session.get(Match, cursor)
        if cursor_item:
            query = query.where(Match.created_at < cursor_item.created_at)
    rows = session.execute(query.order_by(Match.similarity.desc(), Match.created_at.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return {
        "items": [{
            "id": str(match.id), "assetId": str(asset.id), "sourceRelativePath": asset.source_relative_path,
            "similarity": match.similarity, "bbox": match.bbox, "decision": match.decision.value,
            "thumbnailUrl": f"/api/v1/media/matches/{match.id}/thumbnail", "imageUrl": f"/api/v1/media/matches/{match.id}/image",
        } for match, asset in page],
        "nextCursor": str(page[-1][0].id) if len(rows) > limit else None,
    }


@app.patch("/api/v1/matches/{match_id}")
def update_match(match_id: uuid.UUID, body: MatchDecisionUpdate, session: DbSession) -> dict:
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
    match.decision = MatchDecision(body.decision)
    session.commit()
    return {"id": str(match.id), "decision": match.decision.value}


@app.post("/api/v1/searches/{search_id}/save")
def save_collection(search_id: uuid.UUID, body: SaveCollectionRequest, session: DbSession) -> dict:
    search = get_search_or_404(session, search_id)
    if search.status not in {SearchStatus.REVIEWING, SearchStatus.SAVED}:
        raise HTTPException(status_code=409, detail="A collection can be saved after matching completes.")
    search.collection_name = body.name.strip()
    search.status = SearchStatus.SAVED
    session.commit()
    return {"search": serialize_search(search)}


@app.get("/api/v1/collections")
def list_collections(session: DbSession) -> dict:
    searches = session.scalars(select(Search).where(Search.status == SearchStatus.SAVED).order_by(Search.completed_at.desc())).all()
    return {"items": [serialize_search(search) for search in searches]}


@app.get("/api/v1/activity")
def activity(session: DbSession) -> dict:
    searches = session.scalars(select(Search).order_by(Search.created_at.desc()).limit(50)).all()
    return {"items": [serialize_search(search) for search in searches]}


@app.get("/api/v1/media/reference-faces/{reference_face_id}")
def reference_face_preview(reference_face_id: uuid.UUID, request: Request, session: DbSession):
    face = session.get(ReferenceFace, reference_face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Reference face not found.")
    path = storage(request).absolute_path(face.crop_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Reference preview file not found.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/v1/media/matches/{match_id}/{variant}")
def match_media(match_id: uuid.UUID, variant: Literal["thumbnail", "image"], request: Request, session: DbSession):
    match = session.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
    path = storage(request).absolute_path(match.thumbnail_path if variant == "thumbnail" else match.copy_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Matched file not found.")
    return FileResponse(path)


@app.delete("/api/v1/searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search(search_id: uuid.UUID, request: Request, session: DbSession) -> None:
    search = get_search_or_404(session, search_id)
    session.delete(search)
    session.commit()
    storage(request).remove_search_files(search_id)


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)
