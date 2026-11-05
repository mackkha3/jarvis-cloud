"""
Integration tests for the require_api_key decorator.

A tiny throwaway Flask app mounts a protected route; the test client then
checks the three cases that matter: no key -> 401, wrong key -> 401, correct
key -> 200. The expected key is the deterministic one injected by conftest.
"""

import pytest
from flask import Flask, jsonify

from app.api.auth import require_api_key
from app.config import get_config

VALID_KEY = "test-jarvis-key-0123456789"  # matches conftest's JARVIS_API_KEY


@pytest.fixture
def client():
    get_config.cache_clear()
    app = Flask(__name__)

    @app.route("/protected")
    @require_api_key
    def protected():
        return jsonify({"ok": True})

    app.testing = True
    return app.test_client()


def test_missing_key_is_rejected(client):
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Unauthorized"


def test_wrong_key_is_rejected(client):
    resp = client.get("/protected", headers={"X-API-Key": "nope-wrong-key-123456"})
    assert resp.status_code == 401


def test_correct_key_is_accepted(client):
    resp = client.get("/protected", headers={"X-API-Key": VALID_KEY})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_empty_key_header_is_rejected(client):
    resp = client.get("/protected", headers={"X-API-Key": ""})
    assert resp.status_code == 401
