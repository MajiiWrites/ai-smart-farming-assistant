"""Database models (the DATA tier).

WHY SQLAlchemy instead of raw sqlite3: models are Python classes, so the
viva demo can explain "this table = this class", and relationships/queries
stay readable. One table per model, columns declared as class attributes.
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _utcnow():
    """WHY UTC everywhere: user data mixes with server logs and timestamps
    stay comparable even if the laptop's timezone changes (viva-safe answer)."""
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    """Registered user. Flask-Login's UserMixin adds is_authenticated etc."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    # One user -> many records in each feature table.
    analyses = db.relationship("Analysis", backref="user", lazy=True)
    irrigations = db.relationship("IrrigationRecord", backref="user", lazy=True)
    cost_records = db.relationship("CostRecord", backref="user", lazy=True)

    def set_password(self, password):
        """WHY hashing: a database leak must never reveal real passwords.
        werkzeug uses PBKDF2/scrypt with a per-password salt — verify-only."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):  # pragma: no cover
        return f"<User {self.username}>"


class Analysis(db.Model):
    """One leaf-disease analysis run (photo + CV result + treatment notes)."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    image_path = db.Column(db.String(255))  # e.g. "uploads/leaf_20261104.png"
    diagnosis_id = db.Column(db.String(80))  # machine key, e.g. "healthy"
    diagnosis_en = db.Column(db.String(120))
    diagnosis_ur = db.Column(db.String(120))
    severity = db.Column(db.String(40))  # healthy / mild / moderate / severe
    confidence = db.Column(db.Float)  # 0..1 from the CV engine
    diseased_pct = db.Column(db.Float)  # % of leaf area flagged diseased
    lesion_count = db.Column(db.Integer)
    notes = db.Column(db.Text)  # treatment advice snippet, may be empty
    created_at = db.Column(db.DateTime, default=_utcnow)


class IrrigationRecord(db.Model):
    """One irrigation estimate the user ran and saved."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    crop = db.Column(db.String(80))
    growth_stage = db.Column(db.String(80))
    soil_type = db.Column(db.String(80))
    acres = db.Column(db.Float)
    city = db.Column(db.String(120))
    eto = db.Column(db.Float)  # reference evapotranspiration, mm/day
    etc_mm = db.Column(db.Float)  # crop water need, mm/day
    liters_total = db.Column(db.Float)
    schedule_text = db.Column(db.Text)  # human-readable schedule
    created_at = db.Column(db.DateTime, default=_utcnow)


class CostRecord(db.Model):
    """One fertilizer-cost calculation the user ran and saved."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    crop = db.Column(db.String(80))
    acres = db.Column(db.Float)
    # JSON text: [{"name": "Urea", "bags": 2.0, "price_per_bag": 4600.0, ...}]
    line_items_json = db.Column(db.Text)
    total_cost = db.Column(db.Float)
    per_acre_cost = db.Column(db.Float)
    expected_yield_maunds = db.Column(db.Float)
    expected_price = db.Column(db.Float)  # PKR per maund
    revenue = db.Column(db.Float)
    profit = db.Column(db.Float)
    breakeven_yield = db.Column(db.Float)  # maunds/acre needed to break even
    created_at = db.Column(db.DateTime, default=_utcnow)


class Fertilizer(db.Model):
    """Shared price list (not per-user) — the /costs/fertilizers page edits it."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    price_pkr_per_bag = db.Column(db.Float, nullable=False)
    bag_weight_kg = db.Column(db.Float, default=50.0)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
