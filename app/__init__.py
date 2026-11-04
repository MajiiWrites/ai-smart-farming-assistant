"""App factory (three-tier architecture glue).

WHY the factory pattern instead of a global `app = Flask(__name__)`:
1. Tests can create a fresh app instance per test with an in-memory database.
2. Multiple configs (dev / test / prod) can be plugged in without editing code.
3. It avoids circular imports: blueprints import `db` from app.models and the
   factory wires everything together at the end.

Three tiers in this project:
  presentation -> app/templates/ + app/routes/   (what the user sees/clicks)
  logic        -> app/services/                  (CV engine, weather, math)
  data         -> app/models.py                  (SQL tables via SQLAlchemy)

The backend workstream owns presentation-routing + data; services are built
by a sibling workstream, so every route imports them defensively (see the
try/except in the disease/irrigation/costs blueprints).
"""
import os

from flask import Flask, render_template
from flask_login import LoginManager

from config import Config
from app.models import db, User

login_manager = LoginManager()
# WHY: @login_required redirects anonymous users here instead of 403-crashing.
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login calls this on every request to re-hydrate the session user."""
    return User.query.get(int(user_id))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Make sure the upload folder exists before any photo arrives.
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    # WHY blueprints: each feature (auth, disease, ...) is a self-contained
    # module with its own routes/templates. The frontend agent can restyle one
    # feature without touching the others.
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.disease import disease_bp
    from app.routes.irrigation import irrigation_bp
    from app.routes.costs import costs_bp

    # English-only UI (deliberate scope decision): templates carry plain
    # English strings directly, so there is no t()/lang context processor
    # and no language blueprint to register.
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(disease_bp)
    app.register_blueprint(irrigation_bp)
    app.register_blueprint(costs_bp)

    @app.errorhandler(404)
    def not_found(error):
        # Friendly page instead of a bare "Not Found" — keeps the demo smooth.
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        # WHY rollback: a crashed request can leave the SQLAlchemy session in
        # a broken state; rolling back keeps the NEXT request healthy.
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(413)
    def too_large(error):
        # WHY a friendly redirect instead of a bare error page: MAX_CONTENT_LENGTH
        # fires BEFORE our route code runs, so the user would otherwise see
        # nothing but "Request Entity Too Large".
        from flask import flash, redirect, request, url_for
        flash("File is too large. Maximum size is 5 MB.", "danger")
        return redirect(request.referrer or url_for("disease.upload"))

    # db.create_all() is deliberately NOT called here — `python data/seed.py`
    # owns schema creation + seeding (idempotent, prints a summary).
    return app
