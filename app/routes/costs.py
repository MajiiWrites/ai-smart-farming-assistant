"""Fertilizer cost calculator routes.

Endpoints (base.html nav links here — do not rename without updating it):
  GET  /costs              -> costs.index       (form)
  POST /costs/calculate    -> costs.calculate   (result)
  GET  /costs/history      -> costs.history     (history)
  GET/POST /costs/fertilizers -> costs.fertilizers (price table)

Flow: form (fertilizer prices come from the DB so they are always the
currently-edited values) -> math service -> save CostRecord -> result page.

EXPECTED FORM FIELD NAMES (frontend-owned):
  crop, acres, expected_yield_maunds, expected_price, bags_<fertilizer_id>,
  seed_cost, diesel_cost, labor_cost, water_cost, pesticide_cost

The *_cost and yield/price readers accept a few name variants so the
frontend template has flexibility — canonical names are documented above.
"""
import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import db, CostRecord, Fertilizer

costs_bp = Blueprint("costs", __name__, url_prefix="/costs")


def _load_services():
    try:
        from app.services.costs import calculate
        return calculate
    except Exception:
        return None


def _get_crops():
    """Crop options for the form select, from the knowledge workstream's
    CROP_INFO. Returns [] when the module is missing — the template guards
    with `| default([])`."""
    try:
        from app.services.knowledge import CROP_INFO
        return [
            {"id": cid, "name": info.get("name", cid)}
            for cid, info in CROP_INFO.items()
        ]
    except Exception:
        return []


def _pick(form, *names, default=""):
    """First non-empty value among candidate field names."""
    for name in names:
        value = form.get(name, "").strip()
        if value:
            return value
    return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@costs_bp.route("/", methods=["GET"])
@login_required
def index():
    """Form page. Template context: `fertilizers` (list of Fertilizer rows),
    `crops` (id/name options for the crop select)."""
    fertilizers = Fertilizer.query.order_by(Fertilizer.name).all()
    return render_template(
        "costs/form.html", fertilizers=fertilizers, crops=_get_crops()
    )


@costs_bp.route("/calculate", methods=["POST"])
@login_required
def calculate():
    form = request.form
    crop = _pick(form, "crop")
    acres = _to_float(_pick(form, "acres"))
    expected_yield = _to_float(_pick(form, "expected_yield_maunds",
                                     "expected_yield", "yield_maunds"))
    expected_price = _to_float(_pick(form, "expected_price",
                                     "expected_price_per_maund",
                                     "price_per_maund"))

    if not crop or acres <= 0:
        flash("Please check your input values and try again.", "warning")
        return redirect(url_for("costs.index"))

    calculate = _load_services()
    if calculate is None:
        flash("The cost engine is not ready yet. Please try again later.",
              "danger")
        return redirect(url_for("costs.index"))

    # Per-fertilizer bags the user typed: bags_<fertilizer_id> fields.
    fertilizers = Fertilizer.query.all()
    items = []
    for f in fertilizers:
        bags = _to_float(_pick(form, f"bags_{f.id}"))
        if bags > 0:
            items.append({
                "fertilizer_id": f.id,
                "name": f.name,
                "bags": bags,
                "price_per_bag": f.price_pkr_per_bag,
            })

    # Other input costs from the form's second section (Rs, totals not per-acre).
    other_costs = {
        "seed": _to_float(_pick(form, "seed_cost", "seed")),
        "diesel": _to_float(_pick(form, "diesel_cost", "diesel")),
        "labor": _to_float(_pick(form, "labor_cost", "labor")),
        "water": _to_float(_pick(form, "water_cost", "water")),
        "pesticide": _to_float(_pick(form, "pesticide_cost", "pesticide")),
    }

    try:
        # Contract (services/costs.py):
        #   calculate(crop, acres, items=[{name, bags, price_per_bag}],
        #             other={seed:.., diesel:.., ...},
        #             expected_yield_maunds=<per-acre maunds>,
        #             expected_price=<Rs per maund>)
        #   -> dict with line_items [{label, amount, ...}], total_cost,
        #      per_acre_cost, revenue, profit, breakeven_yield (None when the
        #      price is 0). Raises ValueError on bad input.
        out = calculate(
            crop=crop,
            acres=acres,
            items=items,
            other=other_costs,
            expected_yield_maunds=expected_yield,
            expected_price=expected_price,
        )
    except Exception:
        flash("Please check your input values and try again.", "danger")
        return redirect(url_for("costs.index"))

    # Build printable line items the costs/result.html template understands
    # (each item needs `label` and `amount`). Prefer the service's own
    # line_items; otherwise derive them from the posted fertilizer bags and
    # other costs so the result page never renders blank.
    service_items = out.get("line_items")
    if service_items:
        line_items = service_items
    else:
        line_items = [
            {
                "label": f"{it['name']} ({it['bags']:g} bags @ Rs "
                         f"{it['price_per_bag']:,.0f})",
                "amount": it["bags"] * it["price_per_bag"],
            }
            for it in items
        ] + [
            {"label": name.capitalize(), "amount": value}
            for name, value in other_costs.items() if value > 0
        ]

    record = CostRecord(
        user_id=current_user.id,
        crop=crop,
        acres=acres,
        line_items_json=json.dumps(line_items),
        total_cost=out.get("total_cost"),
        per_acre_cost=out.get("per_acre_cost"),
        expected_yield_maunds=expected_yield,
        expected_price=expected_price,
        revenue=out.get("revenue"),
        profit=out.get("profit"),
        breakeven_yield=out.get("breakeven_yield"),
    )
    db.session.add(record)
    db.session.commit()

    # Pass both the saved row and the printable line items to the template.
    line_items = json.loads(record.line_items_json or "[]")
    return render_template(
        "costs/result.html", record=record, line_items=line_items
    )


@costs_bp.route("/history")
@login_required
def history():
    """History page. Template context: `records` (list of CostRecord, newest first)."""
    records = (
        CostRecord.query.filter_by(user_id=current_user.id)
        .order_by(CostRecord.created_at.desc())
        .all()
    )
    return render_template("costs/history.html", records=records)


@costs_bp.route("/fertilizers", methods=["GET", "POST"])
@login_required
def fertilizers():
    """Editable shared price table.
    POST expects price_<id> fields with the new PKR-per-bag value."""
    if request.method == "POST":
        for f in Fertilizer.query.all():
            raw = _pick(request.form, f"price_{f.id}")
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                flash(f"'{raw}' is not a number — skipped {f.name}.", "warning")
                continue
            if value <= 0:
                flash(f"Price must be positive — skipped {f.name}.", "warning")
                continue
            f.price_pkr_per_bag = value
        db.session.commit()
        flash("Fertilizer prices updated successfully.", "success")
        return redirect(url_for("costs.fertilizers"))

    fertilizers = Fertilizer.query.order_by(Fertilizer.name).all()
    return render_template("costs/fertilizers.html", fertilizers=fertilizers)
