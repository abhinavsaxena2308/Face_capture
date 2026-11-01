from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps

from app.core.config import Settings

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


class StorageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def ensure_capacity(self, required_bytes: int) -> None:
        available = shutil.disk_usage(self.settings.app_data_dir).free
        # Temporary ingest plus retained output need a modest safety margin.
        if available < required_bytes + 512 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail="Not enough free disk space for this collection.")

    @staticmethod
    def validate_relative_path(value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
            raise HTTPException(status_code=400, detail="Invalid relative file path.")
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"Unsupported image type: {path.suffix or 'unknown'}.")
        return path.as_posix()

    @staticmethod
    def safe_filename(value: str) -> str:
        safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in value)
        return safe[-180:] or "image"

    async def write_upload(self, search_id: uuid.UUID, asset_id: uuid.UUID, relative_path: str, upload: UploadFile) -> tuple[str, int, str]:
        relative_path = self.validate_relative_path(relative_path)
        target_dir = self.settings.ingest_dir / str(search_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{asset_id}_{self.safe_filename(PurePosixPath(relative_path).name)}"
        digest = hashlib.sha256()
        size = 0
        limit = self.settings.max_file_mb * 1024 * 1024
        try:
            with target.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(status_code=413, detail=f"{relative_path} exceeds the per-file upload limit.")
                    digest.update(chunk)
                    destination.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return (str(target.relative_to(self.settings.app_data_dir)), size, digest.hexdigest())

    def write_reference_crop(self, search_id: uuid.UUID, reference_id: uuid.UUID, crop_bgr) -> str:
        import cv2

        target_dir = self.settings.reference_dir / str(search_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{reference_id}.jpg"
        if not cv2.imwrite(str(target), crop_bgr):
            raise RuntimeError("Could not write reference face preview.")
        return str(target.relative_to(self.settings.app_data_dir))

    def copy_match(self, search_id: uuid.UUID, match_id: uuid.UUID, ingest_relative_path: str, original_name: str) -> str:
        source = self.absolute_path(ingest_relative_path)
        target_dir = self.settings.match_dir / str(search_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{match_id}_{self.safe_filename(original_name)}"
        shutil.copy2(source, target)
        return str(target.relative_to(self.settings.app_data_dir))

    def create_thumbnail(self, search_id: uuid.UUID, match_id: uuid.UUID, ingest_relative_path: str) -> str:
        source = self.absolute_path(ingest_relative_path)
        target_dir = self.settings.thumbnail_dir / str(search_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{match_id}.jpg"
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((640, 640))
            image.save(target, format="JPEG", quality=84, optimize=True)
        return str(target.relative_to(self.settings.app_data_dir))

    def absolute_path(self, relative_path: str) -> Path:
        candidate = (self.settings.app_data_dir / relative_path).resolve()
        root = self.settings.app_data_dir.resolve()
        if root not in candidate.parents and candidate != root:
            raise RuntimeError("Attempted path outside application data directory.")
        return candidate

    def delete_ingest_file(self, relative_path: str | None) -> None:
        if relative_path:
            self.absolute_path(relative_path).unlink(missing_ok=True)

    def remove_search_files(self, search_id: uuid.UUID) -> None:
        for base in (self.settings.ingest_dir, self.settings.match_dir, self.settings.thumbnail_dir, self.settings.reference_dir):
            target = (base / str(search_id)).resolve()
            root = base.resolve()
            if root in target.parents:
                shutil.rmtree(target, ignore_errors=True)
