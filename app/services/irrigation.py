"""Irrigation estimation: FAO-56 Hargreaves ETo x crop coefficient.

WHY Hargreaves instead of Penman-Monteith: the full FAO-56 PM equation
needs net radiation, wind speed and vapor pressure — data a small farmer
never has. Hargreaves needs only max/min temperature (+ latitude and the
day of year, which we know), and FAO-56 explicitly recommends it as the
temperature-only fallback (FAO-56, Eq. 52). For a viva: "we trade some
accuracy for data the farmer actually has."

Chain of math (every intermediate is returned, so the result page and the
viva panel can both audit it):
  1. Ra  = extraterrestrial radiation from latitude + day-of-year
           (FAO-56 Eq. 21 — implemented term by term, no shortcuts)
  2. ETo = 0.0023 * Ra * (Tmean + 17.8) * sqrt(Tmax - Tmin)   [mm/day]
  3. ETc = ETo * Kc            (crop coefficient for crop x growth stage)
  4. water_mm = ETc * soil_factor   (sandy soils need more, clay less)
  5. liters_total = water_mm * 4046.86 * acres
     WHY 4046.86: 1 acre = 4046.86 m^2. A 1-mm sheet of water over it is
     4046.86 m^2 * 0.001 m = 4.04686 m^3 = 4046.86 litres. So "mm x acres"
     converts to litres with exactly that factor — no lookup, just geometry.
"""

import math
from datetime import date

# ---------------------------------------------------------------------------
# Reference tables (documented as FAO-56 typical values)
# ---------------------------------------------------------------------------

# WHY these numbers: FAO-56 Table 12 lists single crop coefficients for
# standard sub-humid conditions (RHmin ~45%, wind ~2 m/s). They are the
# textbook values a viva examiner expects; the module docstring of the
# report says so explicitly.
KC_TABLE = {
    "wheat":     {"initial": 0.40, "development": 0.70, "mid": 1.15, "late": 0.40},
    "rice":      {"initial": 1.05, "development": 1.10, "mid": 1.20, "late": 0.90},
    "cotton":    {"initial": 0.35, "development": 0.70, "mid": 1.20, "late": 0.60},
    "sugarcane": {"initial": 0.40, "development": 0.85, "mid": 1.25, "late": 0.70},
    "maize":     {"initial": 0.30, "development": 0.70, "mid": 1.20, "late": 0.50},
    "potato":    {"initial": 0.50, "development": 0.75, "mid": 1.15, "late": 0.75},
    "tomato":    {"initial": 0.60, "development": 0.85, "mid": 1.15, "late": 0.80},
    "citrus":    {"initial": 0.70, "development": 0.70, "mid": 0.75, "late": 0.70},
}

# WHY: sandy soil drains fast (more water needed per day), clay holds water
# (less per application, but watch waterlogging). Loam is the reference.
SOIL_FACTOR = {"sandy": 1.15, "loam": 1.00, "clay": 0.90}

GROWTH_STAGES = ("initial", "development", "mid", "late")

# When no weather is supplied at all (offline, no city, no manual input)
# the estimate still runs on documented typical mild-season Punjab values —
# WHY: the route promises "the estimate uses safe defaults internally"
# instead of crashing. The result dict flags source='assumed' honestly.
DEFAULT_TMAX = 32.0
DEFAULT_TMIN = 20.0
DEFAULT_LATITUDE = 30.0  # central Punjab; refined from city when known

LITERS_PER_MM_PER_ACRE = 4046.86  # see module docstring derivation

# City -> latitude, reused so Ra matches the weather lookup city.
_CITY_LAT = {
    "bahawalpur": 29.38, "multan": 30.16, "lahore": 31.55,
    "karachi": 24.86, "faisalabad": 31.45, "peshawar": 34.00,
    "hyderabad": 25.38, "rawalpindi": 33.60,
}


# ---------------------------------------------------------------------------
# FAO-56 core
# ---------------------------------------------------------------------------

def extraterrestrial_radiation(lat_deg, day_of_year):
    """Ra in MJ/m^2/day — FAO-56 Eq. 21, term by term.

    WHY each term (viva-ready):
      dr    = inverse relative Earth-Sun distance (orbit is elliptical)
      delta = solar declination (seasons: +23.45 deg at June solstice)
      ws    = sunset hour angle (day length from latitude + declination)
      Ra    = 24*60/pi * Gsc * dr * (ws*sin(phi)*sin(delta)
                                    + cos(phi)*cos(delta)*sin(ws))
      Gsc   = 0.0820 MJ/m^2/min (solar constant)
    """
    if not 1 <= day_of_year <= 366:
        raise ValueError("day_of_year must be 1..366")
    phi = math.radians(lat_deg)
    j = day_of_year
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * j / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * j / 365.0 - 1.39)
    # WHY the clamp: floating-point rounding can push -tan(phi)*tan(delta)
    # a hair outside [-1, 1] near the poles and acos would explode.
    cos_ws = -math.tan(phi) * math.tan(delta)
    cos_ws = min(1.0, max(-1.0, cos_ws))
    ws = math.acos(cos_ws)
    gsc = 0.0820
    ra = (24.0 * 60.0 / math.pi) * gsc * dr * (
        ws * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(ws)
    )
    return ra


def hargreaves_eto(tmax, tmin, ra):
    """Reference evapotranspiration ETo, mm/day — FAO-56 Eq. 52.

    ETo = 0.0023 * Ra * (Tmean + 17.8) * sqrt(Tmax - Tmin)
    WHY the sqrt(Tmax-Tmin): the diurnal temperature range is a proxy for
    cloudiness — clear skies mean hot days AND cold nights (big range, high
    radiation); overcast days stay mild both ways (small range, low
    radiation). That is the whole cleverness of Hargreaves.
    """
    if tmax <= tmin:
        raise ValueError("tmax must be greater than tmin")
    tmean = (tmax + tmin) / 2.0
    return 0.0023 * ra * (tmean + 17.8) * math.sqrt(tmax - tmin)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def _clean(value, name):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required.")
    return str(value).strip().lower()


def _resolve_weather(weather):
    """Normalize the weather dict into (tmax, tmin, source_note)."""
    if weather is None:
        return DEFAULT_TMAX, DEFAULT_TMIN, "assumed"
    try:
        tmax = float(weather["tmax"])
        tmin = float(weather["tmin"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "weather must be a dict with numeric 'tmax' and 'tmin'."
        ) from exc
    if tmax <= tmin:
        raise ValueError("weather tmax must be greater than tmin.")
    return tmax, tmin, weather.get("source", "manual")


def _resolve_latitude(latitude, weather):
    if latitude is not None:
        return float(latitude)
    city = (weather or {}).get("city")
    if city:
        lat = _CITY_LAT.get(str(city).strip().lower())
        if lat is not None:
            return lat
    return DEFAULT_LATITUDE


def _schedule_text(water_mm, liters_total):
    """Human-readable irrigation schedule.

    WHY the 25 mm split: a single heavy application on most Punjab soils
    runs off or waterlogs instead of soaking in; two lighter doses 3-4 days
    apart put the same water into the root zone.
    """
    if water_mm > 25.0:
        half_mm = water_mm / 2.0
        half_l = liters_total / 2.0
        return (
            f"Apply {water_mm:.1f} mm in 2 equal irrigations of {half_mm:.1f} mm "
            f"(about {half_l:,.0f} litres each), 3-4 days apart, to avoid "
            "runoff. Water early morning or late evening."
        )
    return (
        f"Apply a single irrigation of {water_mm:.1f} mm "
        f"(about {liters_total:,.0f} litres total), spread evenly across the "
        "field. Water early morning or late evening to cut evaporation."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def estimate(crop, growth_stage, soil_type, acres, weather=None,
             latitude=None, on_date=None):
    """Estimate daily irrigation need.

    Args:
        crop: one of KC_TABLE keys (e.g. 'wheat').
        growth_stage: 'initial' | 'development' | 'mid' | 'late'.
        soil_type: 'sandy' | 'loam' | 'clay'.
        acres: field size, must be > 0.
        weather: dict with tmax/tmin (+optional source, city); None ->
            documented assumed defaults.
        latitude: override; default from weather city, else 30.0.
        on_date: datetime.date for day-of-year; default today.

    Returns:
        dict with eto, etc_mm, water_mm, liters_total, schedule_text,
        formula_note + every intermediate (kc, soil_factor, ra, tmax, tmin,
        tmean, day_of_year, latitude, weather_source).
    """
    crop = _clean(crop, "crop")
    if crop not in KC_TABLE:
        raise ValueError(
            f"Unknown crop '{crop}'. Choose from: {', '.join(sorted(KC_TABLE))}."
        )
    growth_stage = _clean(growth_stage, "growth_stage")
    if growth_stage not in GROWTH_STAGES:
        raise ValueError(
            f"Unknown growth stage '{growth_stage}'. Choose from: "
            f"{', '.join(GROWTH_STAGES)}."
        )
    soil_type = _clean(soil_type, "soil_type")
    if soil_type not in SOIL_FACTOR:
        raise ValueError(
            f"Unknown soil type '{soil_type}'. Choose from: "
            f"{', '.join(sorted(SOIL_FACTOR))}."
        )
    try:
        acres = float(acres)
    except (TypeError, ValueError) as exc:
        raise ValueError("acres must be a number.") from exc
    if acres <= 0:
        raise ValueError("acres must be greater than 0.")

    tmax, tmin, weather_source = _resolve_weather(weather)
    lat = _resolve_latitude(latitude, weather)
    if not -90.0 <= lat <= 90.0:
        raise ValueError("latitude must be between -90 and 90.")
    day = on_date if on_date is not None else date.today()
    doy = day.timetuple().tm_yday

    ra = extraterrestrial_radiation(lat, doy)
    eto = hargreaves_eto(tmax, tmin, ra)
    kc = KC_TABLE[crop][growth_stage]
    etc = eto * kc
    soil_factor = SOIL_FACTOR[soil_type]
    water_mm = etc * soil_factor
    liters_total = water_mm * LITERS_PER_MM_PER_ACRE * acres

    formula_note = (
        "FAO-56 Hargreaves: ETo = 0.0023 * Ra * (Tmean + 17.8) * sqrt(Tmax - Tmin); "
        f"Ra = {ra:.1f} MJ/m2/day from latitude {lat:.2f} deg, day {doy}; "
        f"ETc = ETo x Kc({kc}); water = ETc x soil_factor({soil_factor}); "
        f"litres = mm x 4046.86 x acres (1 mm over 1 acre = 4046.86 L)."
    )
    return {
        "crop": crop,
        "growth_stage": growth_stage,
        "soil_type": soil_type,
        "acres": acres,
        "tmax": round(tmax, 1),
        "tmin": round(tmin, 1),
        "tmean": round((tmax + tmin) / 2.0, 1),
        "weather_source": weather_source,
        "latitude": round(lat, 2),
        "day_of_year": doy,
        "ra_MJ_m2_day": round(ra, 2),
        "eto": round(eto, 2),
        "kc": kc,
        "etc_mm": round(etc, 2),
        "etc_mm_day": round(etc, 2),
        "soil_factor": soil_factor,
        "water_mm": round(water_mm, 2),
        "water_mm_day": round(water_mm, 2),
        "liters_total": round(liters_total, 1),
        "schedule_text": _schedule_text(water_mm, liters_total),
        "formula_note": formula_note,
    }
