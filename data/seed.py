"""Database setup + seed data: `python data/seed.py` (run from project root).

WHY a separate script (not create_all() in the app factory): schema creation
and demo data are a ONE-TIME deployment step. Keeping it out of the factory
means `python run.py` never risks touching the database on every boot, and
`gunicorn` in production never needs write access to create tables.

The script is IDEMPOTENT — safe to run any number of times; existing rows are
skipped, never duplicated.
"""
import os
import sys

# Let the script run from anywhere: add the project root (parent of data/) to
# sys.path so `import config` and `from app import ...` always resolve.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from app import create_app
from app.models import db, Fertilizer, User

# Prices are realistic Pakistani market values for 2024-2025 and are marked
# APPROXIMATE — the student can edit them anytime at /costs/fertilizers.
FERTILIZERS = [
    ("Urea", 4600.0, 50.0),
    ("DAP", 11500.0, 50.0),
    ("SOP", 13000.0, 50.0),
    ("NP", 7500.0, 50.0),
    ("CAN", 4200.0, 50.0),
    ("SSP", 6000.0, 50.0),
]

DEMO_EMAIL = "demo@farm.pk"
DEMO_PASSWORD = "demo1234"
DEMO_USERNAME = "demo"


def main():
    app = create_app()
    with app.app_context():
        db.create_all()

        seeded_fertilizers = 0
        for name, price, weight in FERTILIZERS:
            if Fertilizer.query.filter_by(name=name).first():
                continue  # idempotent: skip rows that already exist
            db.session.add(Fertilizer(
                name=name, price_pkr_per_bag=price, bag_weight_kg=weight
            ))
            seeded_fertilizers += 1

        # Demo account for the viva — the examiner can log in instantly.
        demo = User.query.filter_by(email=DEMO_EMAIL).first()
        if demo is None:
            demo = User(username=DEMO_USERNAME, email=DEMO_EMAIL)
            demo.set_password(DEMO_PASSWORD)
            db.session.add(demo)
            demo_created = True
        else:
            demo_created = False

        db.session.commit()

        print("Seed summary")
        print("============")
        print(f"Fertilizers in DB : {Fertilizer.query.count()} "
              f"(added {seeded_fertilizers} this run; prices are approximate 2024-2025 PKR)")
        print(f"Demo user         : {DEMO_EMAIL} / {DEMO_PASSWORD} "
              f"({'created' if demo_created else 'already existed'})")
        print(f"Database file     : {app.config['SQLALCHEMY_DATABASE_URI']}")
        print("Done. Start the app with: python run.py")


if __name__ == "__main__":
    main()
