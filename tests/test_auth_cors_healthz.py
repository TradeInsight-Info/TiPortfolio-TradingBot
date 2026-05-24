"""
Tests for tasks 1.1 (bearer-token auth), 1.2 (CORS), and 1.3 (/healthz).

All tests use Flask's test client with SQLite in-memory; no real DB or
broker connection required.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# Env must be set before create_app is imported
os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE", "paper")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app  # noqa: E402

_PYTEST_WEBHOOK_TOKEN = "pytest-only-not-a-real-secret"  # noqa: S105
_ALLOWED_ORIGIN = "https://sample-strategy.tradeinsight.info"
_DISALLOWED_ORIGIN = "https://evil.example.com"

VALID_WEIGHTS = {"weights": {"SPY": 0.6, "QQQ": 0.4}}


# ---------------------------------------------------------------------------
# Shared Alpaca mock (reused across fixtures)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_alpaca():
    with (
        patch("app.webhook.AlpacaClient") as mock_cls,
        patch("app.webhook.OrderExecutor") as mock_exec_cls,
    ):
        client = MagicMock()
        client.get_positions.side_effect = lambda target_symbols=None: {
            s: 0.0 for s in (target_symbols or [])
        }
        client.get_latest_prices.side_effect = lambda symbols: {s: 100.0 for s in symbols}
        client.get_account_equity.return_value = 10_000.0
        client._base_url = "https://paper-api.alpaca.markets"
        mock_cls.return_value = client

        executor = MagicMock()
        from app.order_executor import ExecutionResult, OrderResult
        executor.execute.return_value = ExecutionResult(
            status="success",
            orders=[OrderResult(symbol="SPY", side="buy", qty=6, success=True, alpaca_order_id="id-1"),
                    OrderResult(symbol="QQQ", side="buy", qty=4, success=True, alpaca_order_id="id-2")],
            error_message=None,
        )
        mock_exec_cls.return_value = executor
        yield


# ---------------------------------------------------------------------------
# App fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_with_auth():
    """App with WEBHOOK_SECRET and ALLOWED_ORIGINS configured."""
    os.environ["WEBHOOK_SECRET"] = _PYTEST_WEBHOOK_TOKEN
    os.environ["ALLOWED_ORIGINS"] = _ALLOWED_ORIGIN
    try:
        app = create_app()
        app.config["TESTING"] = True
        return app
    finally:
        os.environ.pop("WEBHOOK_SECRET", None)
        os.environ.pop("ALLOWED_ORIGINS", None)


@pytest.fixture()
def client_auth(app_with_auth):
    return app_with_auth.test_client()


@pytest.fixture()
def app_no_auth():
    """App without WEBHOOK_SECRET (auth disabled — local dev mode)."""
    os.environ.pop("WEBHOOK_SECRET", None)
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client_no_auth(app_no_auth):
    return app_no_auth.test_client()


# ---------------------------------------------------------------------------
# Task 1.1 — Bearer-token auth on POST /webhook
# ---------------------------------------------------------------------------

class TestWebhookAuth:
    def test_returns_401_when_no_authorization_header(self, client_auth):
        resp = client_auth.post("/webhook", json=VALID_WEIGHTS)
        assert resp.status_code == 401

    def test_returns_401_for_wrong_token(self, client_auth):
        resp = client_auth.post(
            "/webhook",
            json=VALID_WEIGHTS,
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 401

    def test_returns_401_for_malformed_scheme(self, client_auth):
        resp = client_auth.post(
            "/webhook",
            json=VALID_WEIGHTS,
            headers={"Authorization": _PYTEST_WEBHOOK_TOKEN},  # missing "Bearer " prefix
        )
        assert resp.status_code == 401

    def test_accepts_valid_bearer_token(self, client_auth, mock_alpaca):
        resp = client_auth.post(
            "/webhook",
            json=VALID_WEIGHTS,
            headers={"Authorization": f"Bearer {_PYTEST_WEBHOOK_TOKEN}"},
        )
        assert resp.status_code == 202

    def test_returns_401_when_secret_not_configured(self, client_no_auth):
        """When WEBHOOK_SECRET is absent, all webhook requests are rejected (fail-closed)."""
        resp = client_no_auth.post("/webhook", json=VALID_WEIGHTS)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task 1.2 — CORS headers restricted to ALLOWED_ORIGINS
# ---------------------------------------------------------------------------

class TestCors:
    def test_allowed_origin_receives_cors_header_on_delta(self, client_auth):
        resp = client_auth.get("/delta", headers={"Origin": _ALLOWED_ORIGIN})
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_allowed_origin_receives_cors_header_on_benchmark(self, client_auth):
        resp = client_auth.get(
            "/benchmark",
            headers={"Origin": _ALLOWED_ORIGIN},
            query_string={"ticker": "SPY"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == _ALLOWED_ORIGIN

    def test_disallowed_origin_gets_no_cors_header(self, client_auth):
        resp = client_auth.get("/delta", headers={"Origin": _DISALLOWED_ORIGIN})
        assert resp.headers.get("Access-Control-Allow-Origin") != _DISALLOWED_ORIGIN

    def test_no_cors_configured_when_allowed_origins_empty(self, client_no_auth):
        """Without ALLOWED_ORIGINS, no CORS headers are added."""
        resp = client_no_auth.get("/delta", headers={"Origin": _ALLOWED_ORIGIN})
        assert resp.headers.get("Access-Control-Allow-Origin") is None


# ---------------------------------------------------------------------------
# Task 1.3 — /healthz endpoint
# ---------------------------------------------------------------------------

class TestHealthz:
    def test_returns_200_when_db_reachable(self, client_no_auth):
        resp = client_no_auth.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_returns_503_when_db_unreachable(self, client_no_auth):
        from sqlalchemy.exc import OperationalError
        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("DB down", None, None)
        mock_factory = MagicMock(return_value=mock_session)
        with patch.dict(client_no_auth.application.config, {"DB_SESSION": mock_factory}):
            resp = client_no_auth.get("/healthz")
        assert resp.status_code == 503
