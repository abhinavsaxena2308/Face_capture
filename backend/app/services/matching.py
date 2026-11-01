from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def cosine_scores(reference_embedding: Sequence[float], embeddings: Sequence[Sequence[float]]) -> np.ndarray:
    reference = np.asarray(reference_embedding, dtype=np.float32)
    vectors = np.asarray(embeddings, dtype=np.float32)
    if reference.ndim != 1 or vectors.ndim != 2 or vectors.shape[1] != reference.shape[0]:
        raise ValueError("Face embeddings must be non-empty vectors with matching dimensions.")
    if not np.isfinite(reference).all() or not np.isfinite(vectors).all():
        raise ValueError("Face embeddings must contain only finite values.")

    reference_norm = np.linalg.norm(reference)
    vector_norms = np.linalg.norm(vectors, axis=1)
    if reference_norm == 0 or np.any(vector_norms == 0):
        raise ValueError("Face embeddings must have non-zero magnitude.")

    scores = (vectors @ reference) / (vector_norms * reference_norm)
    return np.clip(scores, -1.0, 1.0)
