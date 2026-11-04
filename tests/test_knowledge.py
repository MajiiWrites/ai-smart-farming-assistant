"""Knowledge-base tests: every diagnosis has complete English content."""
import pytest

from app.services.knowledge import CROP_INFO, get_crop_info, get_treatment

IDS = ["healthy", "leaf_spot", "blight", "chlorosis", "leaf_scorch"]


@pytest.mark.parametrize("diag", IDS)
def test_full_english_entry(diag):
    t = get_treatment(diag)
    assert t["id"] == diag
    assert t["name"] and t["advice"]  # advice feeds Analysis.notes
    for key in ("symptoms", "prevention", "treatment"):
        bullets = t[key]
        assert 3 <= len(bullets) <= 6, f"{diag}.{key}"
        assert all(b.strip() for b in bullets)
    assert isinstance(t["crops_affected"], list)
    # English-only contract: no *_ur / *_en suffixed keys anywhere.
    assert not any(k.endswith(("_ur", "_en")) for k in t), t.keys()


def test_unknown_id_falls_back():
    t = get_treatment("definitely_not_a_disease")
    assert t["id"] == "unknown"
    assert t["treatment"]  # never empty, never raises


def test_crop_info_english_only():
    assert get_crop_info("wheat") == {"id": "wheat", "name": "Wheat"}
    assert set(CROP_INFO) == {"wheat", "rice", "cotton", "sugarcane",
                              "maize", "potato", "tomato", "citrus"}
    for cid, info in CROP_INFO.items():
        assert set(info) == {"id", "name"}, info
    assert get_crop_info("dragonfruit") is None
