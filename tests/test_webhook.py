"""
Unit tests for POST /webhook.

These tests use Flask's built-in test client and an in-memory SQLite DB,
so no real PostgreSQL or broker connection is needed.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

# Set dummy env vars before importing create_app so startup checks pass
os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE", "paper")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def post_webhook(client, payload):
    return client.post(
        "/webhook",
        data=json.dumps(payload),
        content_type="application/json",
    )

# Happy Path
class TestValidPayload:
    def test_returns_202(self, client):
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}})
        assert res.status_code == 202

    def test_body_contains_status_accepted(self, client):
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}})
        assert res.get_json()["status"] == "success"

    def test_body_contains_received_at(self, client):
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}})
        data = res.get_json()
        assert "received_at" in data

    def test_body_contains_payload_hash(self, client):
        payload = {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}}
        res = post_webhook(client, payload)
        data = res.get_json()
        assert "payload_hash" in data
        # Verify hash is deterministic: recompute and compare
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert data["payload_hash"] == expected

    def test_weights_summing_to_exactly_1_accepted(self, client):
        res = post_webhook(client, {"weights": {"A": 1.0}})
        assert res.status_code == 202

    def test_weights_within_tolerance_accepted(self, client):
        # 0.999 is within ±0.01 of 1.0
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.499}})
        assert res.status_code == 202

# Validation errors - 400 
class TestInvalidPayload:
    def test_missing_weights_field(self, client):
        res = post_webhook(client, {"data": {}})
        assert res.status_code == 400
        assert "weights" in res.get_json()["error"]

    def test_weights_is_not_a_dict(self, client):
        res = post_webhook(client, {"weights": [0.5, 0.5]})
        assert res.status_code == 400

    def test_weights_is_empty_dict(self, client):
        res = post_webhook(client, {"weights": {}})
        assert res.status_code == 400
        assert "empty" in res.get_json()["error"].lower()

    def test_weights_do_not_sum_to_one(self, client):
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.1}})
        assert res.status_code == 400
        assert "sum" in res.get_json()["error"].lower()

    def test_weight_value_is_string(self, client):
        res = post_webhook(client, {"weights": {"SPY": "half"}})
        assert res.status_code == 400
        assert "number" in res.get_json()["error"].lower()

    def test_weight_value_is_null(self, client):
        res = post_webhook(client, {"weights": {"SPY": None}})
        assert res.status_code == 400

    def test_non_json_body(self, client):
        res = client.post(
            "/webhook",
            data="not-json",
            content_type="text/plain",
        )
        assert res.status_code == 400
        assert "JSON" in res.get_json()["error"]

    def test_empty_body(self, client):
        res = client.post("/webhook", data="", content_type="application/json")
        assert res.status_code == 400

    def test_weights_sum_exceeds_tolerance(self, client):
        # 0.5 + 0.6 = 1.1 → outside ±0.01 tolerance
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.6}})
        assert res.status_code == 400