"""Irrigation estimation routes.

Endpoints (base.html nav links here — do not rename without updating it):
  GET  /irrigation          -> irrigation.index    (form)
  POST /irrigation/estimate -> irrigation.estimate (result)

Flow: form -> weather service (city name OR manual tmin/tmax/humidity) ->
irrigation math (Hargreaves ET0 x crop coefficient) -> save IrrigationRecord
-> result page.

EXPECTED FORM FIELD NAMES (frontend-owned):
  crop, growth_stage, soil_type, acres, city, tmin, tmax, humidity

Service imports are defensive: a missing sibling module degrades to a flash
message, never a 500.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import db, IrrigationRecord

irrigation_bp = Blueprint("irrigation", __name__, url_prefix="/irrigation")


def _load_services():
    try:
        from app.services.weather import get_weather
        from app.services.irrigation import estimate
        return get_weather, estimate
    except Exception:
        return None, None


def _get_crops():
    """Crop options for the form select, from the knowledge workstream's
    CROP_INFO (ids match the irrigation KC_TABLE keys). Returns [] when the
    module is missing — the template guards with `| default([])`."""
    try:
        from app.services.knowledge import CROP_INFO
        return [
            {"id": cid, "name": info.get("name", cid)}
            for cid, info in CROP_INFO.items()
        ]
    except Exception:
        return []


def _get_cities():
    """City options for the weather select, from weather.CITY_LATLON."""
    try:
        from app.services.weather import CITY_LATLON
        return sorted(CITY_LATLON)
    except Exception:
        return []


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@irrigation_bp.route("/", methods=["GET"])
@login_required
def index():
    """Form page. Template context: `crops` (id/name options for the crop
    select), `cities` (weather-service city options)."""
    return render_template(
        "irrigation/form.html", crops=_get_crops(), cities=_get_cities()
    )


@irrigation_bp.route("/estimate", methods=["POST"])
@login_required
def estimate():
    crop = request.form.get("crop", "").strip()
    growth_stage = request.form.get("growth_stage", "").strip()
    soil_type = request.form.get("soil_type", "").strip()
    # The form's city select submits "manual" when the user types weather
    # values by hand (see irrigation/form.html) — normalize it to "" so the
    # weather service treats it as "no city" and the record stores cleanly.
    raw_city = request.form.get("city", "").strip()
    city = "" if raw_city.lower() in ("", "manual") else raw_city
    acres = _to_float(request.form.get("acres"))
    tmin = _to_float(request.form.get("tmin"))
    tmax = _to_float(request.form.get("tmax"))
    humidity = _to_float(request.form.get("humidity"))

    if not crop or acres <= 0:
        flash("Please check your input values and try again.", "warning")
        return redirect(url_for("irrigation.index"))

    get_weather, estimate = _load_services()
    if estimate is None:
        flash("The irrigation engine is not ready yet. Please try again later.",
              "danger")
        return redirect(url_for("irrigation.index"))

    # Weather is optional input: a city name -> live/typical values;
    # manual tmin/tmax/humidity -> typed values; neither -> the services
    # fall back to safe defaults internally.
    weather = None
    if get_weather is not None:
        try:
            # Expected contract (services workstream):
            #   get_weather(city=None, tmin=None, tmax=None, humidity=None)
            #   -> dict with temp_c, humidity, ... (or None-safe defaults)
            weather = get_weather(
                city=city or None,
                tmin=tmin or None,
                tmax=tmax or None,
                humidity=humidity or None,
            )
        except Exception as exc:
            flash(f"Weather lookup failed ({exc}); continuing with defaults.",
                  "warning")
            weather = None

    try:
        # Contract (services/irrigation.py):
        #   estimate(crop, growth_stage, soil_type, acres, weather=None,
        #            latitude=None, on_date=None)
        #   -> dict with eto, etc_mm, water_mm, liters_total, schedule_text,
        #      formula_note (+ intermediates). Raises ValueError on bad input.
        out = estimate(
            crop=crop,
            growth_stage=growth_stage,
            soil_type=soil_type,
            acres=acres,
            weather=weather,
        )
    except Exception:
        flash("Please check your input values and try again.", "danger")
        return redirect(url_for("irrigation.index"))

    record = IrrigationRecord(
        user_id=current_user.id,
        crop=crop,
        growth_stage=growth_stage,
        soil_type=soil_type,
        acres=acres,
        city=city,
        eto=out.get("eto"),
        etc_mm=out.get("etc_mm"),
        liters_total=out.get("liters_total"),
        schedule_text=out.get("schedule_text", ""),
    )
    db.session.add(record)
    db.session.commit()

    return render_template(
        "irrigation/result.html",
        record=record,
        # Show the exact formula string the estimation service used
        # (FAO-56 Hargreaves with the computed Ra), falling back to a
        # generic note in the template if absent.
        formula_note=out.get("formula_note"),
    )
