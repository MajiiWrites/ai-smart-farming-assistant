"""Leaf-disease detection routes.

Flow: GET /disease -> upload form; POST /disease/analyze -> CV + treatment ->
save Analysis row -> redirect to /disease/result/<id>; /disease/history lists
the current user's past analyses.

FORM FIELD NAMES (fixed by app/templates/disease/upload.html, frontend-owned):
  file    - the uploaded leaf photo
  crop_id - selected crop (select; currently passed through but unused — the
            vision workstream can adopt it for crop-aware diagnosis later)
  note    - optional user observation text

WHY the try/except around the service import: the vision + knowledge modules
are built by a sibling workstream. If they are not ready yet (or OpenCV is
missing), the app must show a friendly flash message, never a 500 page.
"""
import os
import uuid

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.models import db, Analysis

disease_bp = Blueprint("disease", __name__, url_prefix="/disease")

# WHY a whitelist: the filename extension decides how the browser and the CV
# code treat the bytes; blocking everything else stops e.g. .exe uploads.
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _load_vision():
    """Import the CV service lazily so a missing/broken sibling module degrades
    to a friendly flash message instead of crashing app startup.

    Returns (analyze_leaf, get_treatment, no_leaf_error_class); any element
    may be None when the services workstream has not delivered that piece.
    """
    analyze_leaf = get_treatment = no_leaf_exc = None
    try:
        from app.services.vision import analyze_leaf
    except Exception:
        pass
    try:
        from app.services.vision import NoLeafDetectedError as no_leaf_exc
    except Exception:
        pass
    try:
        from app.services.knowledge import get_treatment
    except Exception:
        pass
    return analyze_leaf, get_treatment, no_leaf_exc


# The vision engine reports severity as Low/Moderate/High; the UI (CSS badges
# + severity labels) speaks healthy/mild/moderate/severe, so the route
# translates between the two vocabularies.
_SEVERITY_MAP = {"Low": "mild", "Moderate": "moderate", "High": "severe"}


def _normalize_severity(raw, diagnosis_id):
    if (diagnosis_id or "").lower() == "healthy":
        return "healthy"
    return _SEVERITY_MAP.get(raw, "moderate")  # unknown -> middle band, safe


@disease_bp.route("/", methods=["GET"])
@login_required
def upload():
    """Upload form. Template context: `crops` (id/name options for the crop
    select, from the knowledge workstream's CROP_INFO; [] when unavailable).
    NOTE: the selected crop_id is currently informational only — the vision
    engine does not yet use it for crop-aware diagnosis."""
    try:
        from app.services.knowledge import CROP_INFO
        crops = [
            {"id": cid, "name": info.get("name", cid)}
            for cid, info in CROP_INFO.items()
        ]
    except Exception:
        crops = []
    return render_template("disease/upload.html", crops=crops)


@disease_bp.route("/analyze", methods=["POST"])
@login_required
def analyze():
    file = request.files.get("file")  # name="file" in upload.html
    note = request.form.get("note", "").strip()

    # Validate BEFORE touching the disk or the CV engine.
    if file is None or file.filename == "":
        flash("Please choose an image file to upload.", "warning")
        return redirect(url_for("disease.upload"))
    if not _allowed(file.filename):
        flash("Invalid file type. Please upload a JPG or PNG image.", "danger")
        return redirect(url_for("disease.upload"))

    analyze_leaf, get_treatment, no_leaf_exc = _load_vision()
    if analyze_leaf is None:
        flash("The leaf-analysis engine is not ready yet. Please try again later.",
              "danger")
        return redirect(url_for("disease.upload"))

    # WHY uuid in the filename: secure_filename alone keeps the user's original
    # name, so two users uploading "leaf.jpg" would overwrite each other.
    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    file.save(save_path)

    try:
        # Contract (services/vision.py): analyze_leaf(path) -> dict with
        # diagnosis_id, diagnosis_en, severity ('Low'|'Moderate'|'High'),
        # confidence (0-100), diseased_pct, lesion_count, annotated_path, ...
        # (English only — there is no diagnosis_ur key.)
        result = analyze_leaf(save_path)
        treatment = get_treatment(result.get("diagnosis_id", "")) \
            if get_treatment else None
    except Exception as exc:  # CV engine blew up — keep the app alive
        # WHY a dedicated message: "no leaf found" is the #1 user error (a
        # photo of soil/sky), and it deserves its own guidance, not a generic
        # "analysis failed".
        if no_leaf_exc is not None and isinstance(exc, no_leaf_exc):
            flash("No leaf detected in the image. Please upload a clear photo of a leaf.",
                  "warning")
        else:
            flash("Analysis failed. Please try again with a clearer image.", "danger")
        return redirect(url_for("disease.upload"))

    if isinstance(treatment, dict):
        advice = treatment.get("advice", "")
    else:
        advice = str(treatment or "")
    # Keep the user's own observation together with the advice (both useful
    # in the history view).
    notes = advice + (f"\nUser note: {note}" if note else "")

    # WHY show the annotated image: the engine draws the detected lesions on
    # it, so the result page demonstrates the CV work instead of just the
    # raw photo. annotated_path is absolute; the template needs it relative
    # to the static folder.
    annotated = result.get("annotated_path") or save_path
    rel_path = "uploads/" + os.path.basename(annotated)

    analysis = Analysis(
        user_id=current_user.id,
        image_path=rel_path,
        diagnosis_id=result.get("diagnosis_id", ""),
        diagnosis_en=result.get("diagnosis_en", ""),
        severity=_normalize_severity(result.get("severity"),
                                     result.get("diagnosis_id")),
        confidence=result.get("confidence", 0.0),
        diseased_pct=result.get("diseased_pct", 0.0),
        lesion_count=result.get("lesion_count", 0),
        notes=notes,
    )
    db.session.add(analysis)
    db.session.commit()

    return redirect(url_for("disease.result", analysis_id=analysis.id))


@disease_bp.route("/result/<int:analysis_id>")
@login_required
def result(analysis_id):
    """Result page. Template context: `analysis` (Analysis row) plus optional
    `symptoms`, `prevention`, `treatment` lists (re-fetched from the knowledge
    service; the template falls back to `analysis.notes` when absent).
    The photo renders via url_for('static', filename=analysis.image_path)."""
    analysis = Analysis.query.filter_by(
        id=analysis_id, user_id=current_user.id
    ).first_or_404()  # user_id filter = nobody can open someone else's result

    # Rich advice lists power the result template's cards; every step is
    # defensive so a missing/broken knowledge module degrades to notes.
    # Contract (services/knowledge.py): get_treatment(id) -> dict with
    # unsuffixed English keys: name, symptoms, prevention, treatment, advice.
    symptoms, prevention, treatment_list = [], [], []
    _, get_treatment, _ = _load_vision()
    if get_treatment is not None:
        try:
            info = get_treatment(analysis.diagnosis_id or "")
            if isinstance(info, dict):
                symptoms = info.get("symptoms", []) or []
                prevention = info.get("prevention", []) or []
                treatment_list = info.get("treatment", []) or []
        except Exception:
            pass

    return render_template(
        "disease/result.html",
        analysis=analysis,
        symptoms=symptoms,
        prevention=prevention,
        treatment=treatment_list,
    )


@disease_bp.route("/history")
@login_required
def history():
    """History page. Template context: `analyses` (list of Analysis, newest first)."""
    analyses = (
        Analysis.query.filter_by(user_id=current_user.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    return render_template("disease/history.html", analyses=analyses)
