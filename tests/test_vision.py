"""Vision engine tests: synthetic leaves -> expected diagnoses.

The samples are generated deterministically by demo/make_sample_leaves.py
(seeded RNG), so these assertions are stable across runs and machines.
"""
import os

import cv2
import numpy as np
import pytest

from app.services.vision import (
    NoLeafDetectedError,
    analyze_leaf,
    validate_image,
)

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "demo", "samples")
SAMPLES = os.path.abspath(SAMPLES)


@pytest.fixture(scope="module", autouse=True)
def _samples():
    """Regenerate the synthetic leaves (idempotent, seeded -> identical)."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "demo"))
    import make_sample_leaves
    make_sample_leaves.main(SAMPLES)


def _p(name):
    return os.path.join(SAMPLES, name)


@pytest.mark.parametrize("fname,expected", [
    ("healthy_leaf.jpg", "healthy"),
    ("spotted_leaf.jpg", "leaf_spot"),
    ("blight_leaf.jpg", "blight"),
    ("chlorotic_leaf.jpg", "chlorosis"),
])
def test_diagnoses(fname, expected):
    """Each synthetic leaf must classify to its designed diagnosis."""
    result = analyze_leaf(_p(fname))
    assert result["diagnosis_id"] == expected
    # Honest confidence bounds: never below 55, never 99/100.
    assert 55 <= result["confidence"] <= 92
    assert result["severity"] in ("Low", "Moderate", "High")
    assert result["diagnosis_en"]
    assert "diagnosis_ur" not in result  # English-only contract
    # Annotated image must actually be written.
    assert os.path.isfile(result["annotated_path"])


def test_non_leaf_raises():
    """A photo with no foliage hues must raise, not hallucinate."""
    with pytest.raises(NoLeafDetectedError):
        analyze_leaf(_p("non_leaf.jpg"))


def test_sequential_calls_are_stable():
    """Many sequential calls: pure pipeline, no cross-talk, same result."""
    first = analyze_leaf(_p("spotted_leaf.jpg"))
    for _ in range(3):
        again = analyze_leaf(_p("spotted_leaf.jpg"))
        assert again["diagnosis_id"] == first["diagnosis_id"]
        assert again["confidence"] == first["confidence"]
        assert again["diseased_pct"] == first["diseased_pct"]


def test_validate_image_bad_extension(tmp_path):
    bad = tmp_path / "leaf.txt"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="JPG or PNG"):
        validate_image(str(bad))


def test_validate_image_too_big(tmp_path):
    big = tmp_path / "huge.jpg"
    big.write_bytes(b"\xff" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="5 MB"):
        validate_image(str(big))


def test_validate_image_missing():
    with pytest.raises(ValueError, match="not found"):
        validate_image("/nonexistent/leaf.jpg")


def test_tiny_image_rejected(tmp_path):
    tiny = tmp_path / "tiny.jpg"
    cv2.imwrite(str(tiny), np.zeros((40, 40, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="too small"):
        analyze_leaf(str(tiny))


def test_undecodable_file_rejected(tmp_path):
    fake = tmp_path / "fake.jpg"
    fake.write_text("i am not a jpeg")
    with pytest.raises(ValueError, match="decoded as an image"):
        analyze_leaf(str(fake))
