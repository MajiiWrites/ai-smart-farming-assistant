"""Pytest bootstrap: put the project root on sys.path.

WHY: the services live in the `app` package and the app factory does
`from config import Config` — both resolve only when the project root
(~/workspace/smart_farming/) is importable. Tests must not depend on the
developer's cwd or installed packages.
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
