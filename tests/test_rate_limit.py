"""
Tests for per-IP rate limiting on public read endpoints.

Each test builds a fresh app so the limiter storage is isolated.
The limiter is enabled via app.config["RATELIMIT_ENABLED"] = True.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("WEBHOOK_SECRET",    "test-secret")

from app import create_app, limiter  # noqa: E402


@pytest.fixture()
def limited_app():
    """Fresh app with rate limiting explicitly enabled."""
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = True
    # Reset storage so counts from other tests don't bleed in
    with flask_app.app_context():
        limiter.reset()
    return flask_app


def _mock_alpaca():
    mock = MagicMock()
    mock.list_positions_full.return_value = []
    mock.get_account.return_value = {"equity": 10000.0, "cash": 500.0}
    return mock


def test_delta_rate_limited(limited_app):
    """Bursting /delta well beyond the 5/s limit must produce at least one 429."""
    with limited_app.test_client() as client:
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_cls.return_value.get_all.return_value = []
            responses = [client.get("/delta") for _ in range(40)]

    status_codes = [r.status_code for r in responses]
    assert 429 in status_codes, (
        f"Expected at least one 429 in {status_codes}"
    )


def test_single_request_ok(limited_app):
    """A single GET /strategies must still return 200 with the limiter enabled."""
    with limited_app.test_client() as client:
        resp = client.get("/strategies")
    assert resp.status_code == 200


def test_single_request_delta_ok(limited_app):
    """A single GET /delta must still return 200 with the limiter enabled."""
    with limited_app.test_client() as client:
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_cls.return_value.get_all.return_value = []
            resp = client.get("/delta?strategy_id=vix")
    assert resp.status_code == 200


def test_single_request_config_ok(limited_app):
    """A single GET /config must still return 200 with the limiter enabled."""
    with limited_app.test_client() as client:
        resp = client.get("/config")
    assert resp.status_code == 200


def test_single_request_positions_ok(limited_app):
    """A single GET /positions must still return 200 with the limiter enabled."""
    with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
        with limited_app.test_client() as client:
            resp = client.get("/positions")
    assert resp.status_code == 200
