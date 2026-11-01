from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOCAL_FRONTEND_ORIGINS = {"http://127.0.0.1:4300", "http://localhost:4300"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    app_data_dir: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] | str = ["http://127.0.0.1:4300"]

    cpu_workers: int = Field(default=1, ge=1, le=1)
    worker_poll_seconds: int = Field(default=2, ge=1, le=60)
    stale_job_minutes: int = Field(default=15, ge=1, le=240)

    max_collection_files: int = Field(default=25_000, ge=10_000)
    max_file_mb: int = Field(default=50, ge=1)
    max_batch_files: int = Field(default=25, ge=1, le=100)
    max_batch_mb: int = Field(default=200, ge=1)

    model_dir: Path
    yunet_model: str = "face_detection_yunet_2023mar.onnx"
    sface_model: str = "face_recognition_sface_2021dec.onnx"
    detector_score_threshold: float = Field(default=0.9, ge=0, le=1)
    detector_nms_threshold: float = Field(default=0.3, ge=0, le=1)
    min_target_face_pixels: int = Field(default=40, ge=10)
    min_reference_face_pixels: int = Field(default=80, ge=10)
    match_threshold_broad: float = Field(default=0.32, ge=-1, le=1)
    match_threshold_balanced: float = Field(default=0.363, ge=-1, le=1)
    match_threshold_strict: float = Field(default=0.45, ge=-1, le=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            origins = [item.strip() for item in value.split(",") if item.strip()]
        else:
            origins = value
        if LOCAL_FRONTEND_ORIGINS.intersection(origins):
            origins.extend(LOCAL_FRONTEND_ORIGINS)
        return list(dict.fromkeys(origins))

    @property
    def ingest_dir(self) -> Path:
        return self.app_data_dir / "ingest"

    @property
    def match_dir(self) -> Path:
        return self.app_data_dir / "matches"

    @property
    def thumbnail_dir(self) -> Path:
        return self.app_data_dir / "thumbnails"

    @property
    def reference_dir(self) -> Path:
        return self.app_data_dir / "reference-faces"

    def threshold_for(self, sensitivity: str) -> float:
        return {
            "broad": self.match_threshold_broad,
            "balanced": self.match_threshold_balanced,
            "strict": self.match_threshold_strict,
        }[sensitivity]

    def ensure_directories(self) -> None:
        for path in (self.app_data_dir, self.ingest_dir, self.match_dir, self.thumbnail_dir, self.reference_dir, self.model_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
