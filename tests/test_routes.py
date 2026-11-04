"""Route smoke tests through the real Flask app (test client).

Covers: register -> login -> GET /, /disease, /irrigation, /costs (200),
POST /disease/analyze with a synthetic spotted leaf (302 -> result page),
POST /irrigation/estimate with manual weather (no network), and
POST /costs/calculate with a seeded fertilizer price.

WHY tmp overrides: uploads and the sqlite file must never touch the real
project data — the app factory reads UPLOAD_FOLDER / DATABASE_URL from the
config object, so a TestConfig subclass keeps everything hermetic.
"""
import io
import os
import sys

import pytest

flask = pytest.importorskip("flask")
pytest.importorskip("flask_login")
pytest.importorskip("flask_sqlalchemy")

SAMPLES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                       "demo", "samples"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "demo"))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import make_sample_leaves
    make_sample_leaves.main(SAMPLES)  # idempotent, seeded

    tmp = tmp_path_factory.mktemp("routetest")
    upload_dir = tmp / "uploads"
    upload_dir.mkdir()
    db_path = tmp / "test.db"

    from config import Config

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(db_path)
        UPLOAD_FOLDER = str(upload_dir)

    from app import create_app
    from app.models import db

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
    app.test_client()  # warm up
    with app.test_client() as c:
        yield c, app


def _register_and_login(c):
    rv = c.post("/auth/register", data={
        "username": "tester", "email": "tester@example.com",
        "password": "secret123", "confirm": "secret123",
    })
    assert rv.status_code == 302  # -> login page
    rv = c.post("/auth/login", data={
        "email": "tester@example.com", "password": "secret123",
    })
    assert rv.status_code == 302  # -> index
    return c


def test_auth_and_page_smoke(client):
    c, _ = client
    c = _register_and_login(c)
    # NOTE: blueprint index routes use a trailing slash (strict_slashes);
    # request the canonical URLs directly.
    for url in ["/", "/disease/", "/disease/history",
                "/irrigation/", "/costs/", "/costs/history",
                "/costs/fertilizers"]:
        rv = c.get(url)
        assert rv.status_code == 200, url


def test_disease_analyze_end_to_end(client):
    """Upload the synthetic spotted leaf -> redirect to a result page."""
    c, app = client
    c = _register_and_login(c)
    with open(os.path.join(SAMPLES, "spotted_leaf.jpg"), "rb") as f:
        jpg = f.read()
    # Form field name is "file" (fixed by upload.html, frontend-owned).
    rv = c.post("/disease/analyze",
                data={"file": (io.BytesIO(jpg), "spotted.jpg")},
                content_type="multipart/form-data")
    assert rv.status_code == 302
    assert "/disease/result/" in rv.headers["Location"]
    # The result page renders the saved Analysis row.
    rv = c.get(rv.headers["Location"])
    assert rv.status_code == 200
    assert b"leaf_spot" in rv.data or b"Leaf Spot" in rv.data
    # History shows the new analysis.
    rv = c.get("/disease/history")
    assert rv.status_code == 200


def test_disease_analyze_rejects_non_leaf(client):
    """Uploading the non-leaf image must flash + bounce, never 500."""
    c, _ = client
    c = _register_and_login(c)
    with open(os.path.join(SAMPLES, "non_leaf.jpg"), "rb") as f:
        jpg = f.read()
    rv = c.post("/disease/analyze",
                data={"file": (io.BytesIO(jpg), "nonleaf.jpg")},
                content_type="multipart/form-data")
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith("/disease/")


def test_irrigation_estimate_manual_weather(client):
    """Manual temperature path: no network, real Hargreaves math."""
    c, _ = client
    c = _register_and_login(c)
    # The form sends tmin/tmax (or a city); manual values stay offline.
    rv = c.post("/irrigation/estimate", data={
        "crop": "wheat", "growth_stage": "mid", "soil_type": "loam",
        "acres": "2", "city": "manual", "tmin": "24", "tmax": "38",
        "humidity": "50",
    })
    assert rv.status_code == 200
    assert b"litres" in rv.data or b"mm" in rv.data


def test_costs_calculate_with_fertilizer(client):
    c, app = client
    c = _register_and_login(c)
    with app.app_context():
        from app.models import db, Fertilizer
        if not Fertilizer.query.filter_by(name="DAP").first():
            db.session.add(Fertilizer(name="DAP", price_pkr_per_bag=12000.0))
            db.session.commit()
        fert = Fertilizer.query.filter_by(name="DAP").first()
    rv = c.post("/costs/calculate", data={
        "crop": "wheat", "acres": "2",
        f"bags_{fert.id}": "1.5",
        "seed_cost": "8000",
        "expected_yield_maunds": "40", "expected_price": "4000",
    })
    assert rv.status_code == 200
    # 1.5 bags/acre x 2 acres x 12000 = 36000, plus seed 8000 = 44000
    assert b"44000" in rv.data or b"44,000" in rv.data
