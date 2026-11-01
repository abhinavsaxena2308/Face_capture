from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.core.config import Settings

register_heif_opener()


@dataclass(frozen=True)
class DetectedFace:
    raw: np.ndarray
    bbox: dict[str, float]
    score: float


class VisionService:
    """CPU-only YuNet detection and SFace embedding extraction."""

    def __init__(self, settings: Settings):
        self.settings = settings
        detector_path = settings.model_dir / settings.yunet_model
        recognizer_path = settings.model_dir / settings.sface_model
        missing = [str(path) for path in (detector_path, recognizer_path) if not path.is_file()]
        if missing:
            raise RuntimeError("Face models are missing. Run scripts/fetch_models.py first: " + ", ".join(missing))
        self.detector = cv2.FaceDetectorYN.create(
            str(detector_path), "", (320, 320), settings.detector_score_threshold, settings.detector_nms_threshold, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    @staticmethod
    def read_image(path: Path) -> np.ndarray:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    def detect(self, image: np.ndarray, min_pixels: int) -> list[DetectedFace]:
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, detections = self.detector.detect(image)
        if detections is None:
            return []
        result: list[DetectedFace] = []
        for raw in detections:
            x, y, box_width, box_height, *_, score = raw.tolist()
            if min(box_width, box_height) < min_pixels:
                continue
            result.append(
                DetectedFace(
                    raw=raw,
                    bbox={"x": round(x), "y": round(y), "width": round(box_width), "height": round(box_height)},
                    score=float(score),
                )
            )
        return result

    def embedding(self, image: np.ndarray, face: DetectedFace) -> list[float]:
        aligned = self.recognizer.alignCrop(image, face.raw)
        vector = self.recognizer.feature(aligned).flatten().astype(np.float32)
        norm = np.linalg.norm(vector)
        if not norm:
            raise RuntimeError("The face embedding had zero magnitude.")
        return (vector / norm).tolist()

    @staticmethod
    def crop(image: np.ndarray, face: DetectedFace) -> np.ndarray:
        box = face.bbox
        height, width = image.shape[:2]
        x1 = max(0, int(box["x"]))
        y1 = max(0, int(box["y"]))
        x2 = min(width, x1 + int(box["width"]))
        y2 = min(height, y1 + int(box["height"]))
        return image[y1:y2, x1:x2]
