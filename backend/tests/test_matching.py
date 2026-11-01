import numpy as np
import pytest

from app.services.matching import cosine_scores


def test_cosine_scores_match_direction_not_magnitude() -> None:
    scores = cosine_scores(
        [1.0, 0.0, 0.0],
        [[2.0, 0.0, 0.0], [0.0, 5.0, 0.0], [-4.0, 0.0, 0.0]],
    )

    np.testing.assert_allclose(scores, [1.0, 0.0, -1.0])


def test_cosine_scores_reject_zero_vectors() -> None:
    with pytest.raises(ValueError, match="non-zero magnitude"):
        cosine_scores([1.0, 0.0], [[0.0, 0.0]])
