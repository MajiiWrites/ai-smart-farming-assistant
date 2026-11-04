"""Main blueprint: dashboard (/) and static pages."""
from flask import Blueprint, render_template
from flask_login import current_user

from app.models import Analysis, CostRecord, IrrigationRecord

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Dashboard — links to the three features. Kept public so a visitor sees
    the product; the feature pages themselves are @login_required.

    Template context (see app/templates/index.html, frontend-owned):
      analyses_count, irrigation_count, costs_count — 0 for anonymous visitors.
    """
    if current_user.is_authenticated:
        uid = current_user.id
        analyses_count = Analysis.query.filter_by(user_id=uid).count()
        irrigation_count = IrrigationRecord.query.filter_by(user_id=uid).count()
        costs_count = CostRecord.query.filter_by(user_id=uid).count()
    else:
        analyses_count = irrigation_count = costs_count = 0
    return render_template(
        "index.html",
        analyses_count=analyses_count,
        irrigation_count=irrigation_count,
        costs_count=costs_count,
    )
