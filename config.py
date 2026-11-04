"""Application configuration.

WHY a config class (not loose globals): Flask's app factory pattern expects a
config object; it keeps environment-specific settings (dev vs production) in
one place so nothing is hardcoded inside the app factory itself.
"""
import os

# Project root = the folder that contains this file (~/workspace/smart_farming/).
# All file paths below are anchored here so the app works no matter where
# `python run.py` is launched from.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # WHY the env override: committing a real secret key to the repo is a
    # classic security bug. Locally we fall back to a dev-only key; on the
    # deployment server the student sets the SECRET_KEY environment variable.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-me"

    # WHY SQLite: the university submission needs zero setup — no MySQL server
    # to install. The whole database is one file that travels with the project.
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or "sqlite:///" + os.path.join(BASE_DIR, "data", "app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # saves memory; we don't use it

    # Leaf photos are stored inside static/ so the result pages can show them
    # with a plain <img> tag.
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")

    # WHY a hard limit: a malicious (or accidental) huge upload would fill the
    # disk; 5 MB is plenty for a phone photo of a leaf.
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # The UI is English-only (deliberate scope decision); kept as a tuple so
    # any future language work has an obvious place to extend.
    LANGUAGES = ("en",)


class DevConfig(Config):
    DEBUG = True
