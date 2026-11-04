"""Service layer: pure logic for the AI Smart Farming Assistant.

Every module here is import-safe: no Flask app context, no database, no
side effects at import time. Each one only needs stdlib + opencv / numpy /
requests, so the routes can import them lazily and unit tests can import
them directly.
"""
