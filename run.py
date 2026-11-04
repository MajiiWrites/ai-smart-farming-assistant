"""Entrypoint: `python run.py`.

WHY this tiny file exists: it keeps "create the app" logic (in app/__init__.py)
separate from "run the server" logic. That is what lets the student run the
same code under gunicorn in production without touching any code.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # 0.0.0.0 lets a phone on the same Wi-Fi open the app (needed for the
    # student's mobile demo). debug=True is dev-only; gunicorn does NOT use it.
    app.run(host="0.0.0.0", port=5000, debug=True)
