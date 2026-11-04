"""Irrigation math tests: hand-verified FAO-56 values + unit identities.

The reference numbers below were computed by an INDEPENDENT hand
calculation of the FAO-56 equations (see the analysis notes), then pasted
here — the test does not re-implement the module, it checks the module
against fixed truth.
"""
from datetime import date

import pytest

from app.services.irrigation import (
    KC_TABLE,
    SOIL_FACTOR,
    estimate,
    extraterrestrial_radiation,
    hargreaves_eto,
)

# Fixed scenario: Bahawalpur (29.38 N), 15 June 2026 (day 166),
# Tmax 40 C, Tmin 26 C.
LAT = 29.38
DAY = date(2026, 6, 15)
WX = {"tmax": 40.0, "tmin": 26.0, "source": "manual"}


def test_ra_matches_hand_calculation():
    """FAO-56 Eq. 21: Ra = 41.0854 MJ/m2/day for the fixed scenario."""
    assert extraterrestrial_radiation(LAT, 166) == pytest.approx(41.0854, abs=1e-3)


def test_hargreaves_matches_hand_calculation():
    """FAO-56 Eq. 52: ETo = 17.9615 mm/day for the fixed scenario."""
    ra = extraterrestrial_radiation(LAT, 166)
    assert hargreaves_eto(40.0, 26.0, ra) == pytest.approx(17.9615, abs=1e-3)


def test_estimate_end_to_end():
    """Wheat/mid/loam/2 acres: ETc = ETo x 1.15, loam factor 1.0."""
    out = estimate("wheat", "mid", "loam", 2.0, weather=WX,
                   latitude=LAT, on_date=DAY)
    assert out["eto"] == pytest.approx(17.96, abs=0.01)
    assert out["kc"] == 1.15
    assert out["etc_mm"] == pytest.approx(17.9615 * 1.15, abs=0.01)
    assert out["soil_factor"] == 1.0
    assert out["water_mm"] == pytest.approx(out["etc_mm"], abs=1e-9)
    # liters = mm x 4046.86 x acres (geometry, not a magic number)
    assert out["liters_total"] == pytest.approx(
        out["water_mm"] * 4046.86 * 2.0, rel=1e-3)
    assert out["liters_total"] == pytest.approx(167181.7, rel=1e-3)
    assert "Hargreaves" in out["formula_note"]
    assert out["schedule_text"]  # non-empty human schedule


def test_liters_identity():
    """10 mm over 1 acre == 40468.6 L — the acre-mm-litre identity."""
    assert 10 * 4046.86 * 1 == pytest.approx(40468.6)


def test_kc_table_sanity():
    """Spot-check FAO-56 typical Kc values used by the module."""
    assert KC_TABLE["wheat"]["mid"] == 1.15
    assert KC_TABLE["rice"]["mid"] == 1.20
    assert KC_TABLE["cotton"]["mid"] == 1.20
    assert KC_TABLE["sugarcane"]["mid"] == 1.25
    # Mid-season Kc must exceed initial Kc for every crop (canopy grows).
    for crop, stages in KC_TABLE.items():
        assert stages["mid"] >= stages["initial"], crop
    assert SOIL_FACTOR["sandy"] > SOIL_FACTOR["loam"] > SOIL_FACTOR["clay"]


def test_heavy_dose_splits_schedule():
    """Water need > 25 mm must suggest splitting into 2 irrigations."""
    out = estimate("sugarcane", "mid", "sandy", 5.0, weather=WX,
                   latitude=LAT, on_date=DAY)
    assert out["water_mm"] > 25.0
    assert "2 equal irrigations" in out["schedule_text"]


def test_validation():
    with pytest.raises(ValueError, match="Unknown crop"):
        estimate("dragonfruit", "mid", "loam", 1.0, weather=WX)
    with pytest.raises(ValueError, match="growth stage"):
        estimate("wheat", "flowering", "loam", 1.0, weather=WX)
    with pytest.raises(ValueError, match="soil type"):
        estimate("wheat", "mid", "peat", 1.0, weather=WX)
    with pytest.raises(ValueError, match="greater than 0"):
        estimate("wheat", "mid", "loam", 0, weather=WX)
    with pytest.raises(ValueError, match="tmax"):
        estimate("wheat", "mid", "loam", 1.0,
                 weather={"tmax": 20.0, "tmin": 25.0})
