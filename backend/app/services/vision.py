from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.core.config import Settings

register_heif_opener()


@dataclass(frozen=True)
class DetectedFace:
    raw: np.ndarray
    bbox: dict[str, Any]
    score: float
    emotion: str = "neutral"


class VisionService:
    """CPU-only YuNet detection, facial landmark emotion analysis, and SFace embedding extraction."""

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
        self.smile_cascade: cv2.CascadeClassifier | None = None
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_smile.xml"
            self.smile_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception:
            self.smile_cascade = None

    @staticmethod
    def read_image(path: Path) -> np.ndarray:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def classify_face_emotion(
        image: np.ndarray,
        raw: np.ndarray,
        smile_cascade: cv2.CascadeClassifier | None = None,
    ) -> str:
        """Classify facial emotion using OpenCV smile cascade and facial landmarks."""
        try:
            if len(raw) < 14:
                return "neutral"

            x, y, box_width, box_height = raw[0:4]
            rx, ry = raw[4:6]    # right eye
            lx, ly = raw[6:8]    # left eye
            nx, ny = raw[8:10]   # nose tip
            rmx, rmy = raw[10:12]  # right mouth corner
            lmx, lmy = raw[12:14]  # left mouth corner

            # 1. Smile cascade detection on lower-face region if image is provided
            if smile_cascade is not None and not smile_cascade.empty() and image.size > 0:
                img_h, img_w = image.shape[:2]
                x1 = max(0, int(x))
                y1 = max(0, int(y + box_height * 0.45))
                x2 = min(img_w, int(x + box_width))
                y2 = min(img_h, int(y + box_height))
                if x2 > x1 + 15 and y2 > y1 + 15:
                    mouth_crop = image[y1:y2, x1:x2]
                    gray = cv2.cvtColor(mouth_crop, cv2.COLOR_BGR2GRAY)
                    gray = cv2.equalizeHist(gray)
                    smiles = smile_cascade.detectMultiScale(gray, scaleFactor=1.18, minNeighbors=18, minSize=(16, 16))
                    if len(smiles) > 0:
                        return "happy"

            # 2. Geometric landmarks analysis
            eye_dist = np.hypot(lx - rx, ly - ry)
            mouth_width = np.hypot(lmx - rmx, lmy - rmy)
            if eye_dist <= 0:
                return "neutral"

            ratio = mouth_width / eye_dist
            mouth_mid_y = (rmy + lmy) / 2.0
            nose_to_mouth = mouth_mid_y - ny

            # Smiling: mouth widens significantly relative to eye distance
            if ratio >= 1.05 or (ratio >= 0.88 and nose_to_mouth > 0):
                return "happy"

            # Surprised: jaw drops / mouth opens, nose-to-mouth distance is large relative to face height
            if box_height > 0 and (nose_to_mouth / box_height) > 0.42:
                return "surprised"

            # Sad: corners of mouth are low / mouth is narrow
            if ratio < 0.60 and box_height > 0 and (nose_to_mouth / box_height) > 0.35:
                return "sad"

            # Serious / focused: tight, narrow lips
            if ratio < 0.65:
                return "serious"

            return "neutral"
        except Exception:
            return "neutral"

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
            emotion = self.classify_face_emotion(image, raw, self.smile_cascade)
            result.append(
                DetectedFace(
                    raw=raw,
                    bbox={
                        "x": round(x),
                        "y": round(y),
                        "width": round(box_width),
                        "height": round(box_height),
                        "emotion": emotion,
                    },
                    score=float(score),
                    emotion=emotion,
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
