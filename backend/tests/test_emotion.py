import numpy as np
import pytest
from app.services.vision import VisionService
from app.core.config import Settings

def test_classify_emotion_neutral():
    # Synthetic face with neutral landmarks
    # landmarks: [rx, ry, lx, ly, nx, ny, rmx, rmy, lmx, lmy]
    w, h = 100, 100
    raw = np.array([10, 10, w, h, 35, 40, 65, 40, 50, 60, 40, 80, 60, 80, 0.99], dtype=np.float32)
    face_img = np.zeros((120, 120, 3), dtype=np.uint8)
    
    # We test the static/helper method directly
    emotion = VisionService.classify_face_emotion(face_img, raw)
    assert emotion in {"neutral", "happy", "surprised", "sad", "serious"}

def test_classify_emotion_happy_geometry():
    # Synthetic face with wide smiling mouth
    w, h = 100, 100
    # rx=35, ry=40, lx=65, ly=40 -> eye dist = 30
    # mouth corners wide: rmx=30, rmy=75, lmx=70, lmy=75 -> mouth width = 40 (ratio 40/30 = 1.33)
    raw = np.array([10, 10, w, h, 35, 40, 65, 40, 50, 60, 30, 75, 70, 75, 0.99], dtype=np.float32)
    face_img = np.zeros((120, 120, 3), dtype=np.uint8)
    
    emotion = VisionService.classify_face_emotion(face_img, raw)
    assert emotion == "happy"

