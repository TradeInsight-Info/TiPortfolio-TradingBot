"""
Tests for per-strategy routing introduced in Task 2.

Covers:
  - Unknown / missing strategy_id → 400
  - Weights outside the strategy's universe → 400
  - Success path with a non-default strategy (trend_broad) → 202 + strategy_id in event
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.order_executor import ExecutionResult, OrderResult

# Ensure env vars are set before importing create_app
os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ["TIPORTFOLIO_MODE"] = "live"   # prevent simulated (yfinance) mode in tests

from app import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_client():
    """Function-scoped Flask test client with its own in-memory DB."""
    os.environ["WEBHOOK_SECRET"] = "test-secret"
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def mock_alpaca():
    """
    Patch AlpacaClient and OrderExecutor to avoid real network calls.
    Returns (mock_client, mock_executor).
    """
    with patch("app.webhook.AlpacaClient") as mock_client_cls, \
         patch("app.webhook.OrderExecutor") as mock_executor_cls:

        mock_client = MagicMock()
        mock_client.get_positions.side_effect = (
            lambda target_symbols=None: {s: 0.0 for s in (target_symbols or [])}
        )
        mock_client.get_latest_prices.side_effect = (
            lambda symbols: {s: 100.0 for s in symbols}
        )
        mock_client.get_account_equity.return_value = 10_000.0
        mock_client._base_url = "https://paper-api.alpaca.markets"
        mock_client_cls.return_value = mock_client

        mock_executor = MagicMock()
        mock_executor.execute.return_value = ExecutionResult(
            orders=[
                OrderResult("SPY", "buy", 10, "uuid-spy", True, None),
            ],
            status="success",
        )
        mock_executor_cls.return_value = mock_executor

        yield mock_client, mock_executor


def post_webhook(client, payload):
    return client.post(
        "/webhook",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Authorization": "Bearer test-secret"},
    )


# ---------------------------------------------------------------------------
# strategy_id validation
# ---------------------------------------------------------------------------

class TestStrategyIdValidation:
    def test_missing_strategy_id_returns_400(self, fresh_client):
        res = post_webhook(fresh_client, {"weights": {"QQQ": 1.0}})
        assert res.status_code == 400
        assert "strategy_id" in res.get_json()["error"].lower()

    def test_unknown_strategy_id_returns_400(self, fresh_client):
        res = post_webhook(fresh_client, {"strategy_id": "no_such_strategy", "weights": {"QQQ": 1.0}})
        assert res.status_code == 400
        assert "strategy_id" in res.get_json()["error"].lower()

    def test_list_strategy_id_returns_400(self, fresh_client):
        """A non-string strategy_id (e.g. a JSON list) must yield 400, not 500."""
        res = post_webhook(fresh_client, {"strategy_id": ["x"], "weights": {"QQQ": 1.0}})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Universe check
# ---------------------------------------------------------------------------

class TestUniverseCheck:
    def test_ticker_outside_vix_universe_returns_400(self, fresh_client):
        # SPY is not in the vix universe (QQQ/BIL/GLD)
        res = post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"SPY": 1.0}})
        assert res.status_code == 400
        assert "universe" in res.get_json()["error"].lower()

    def test_mixed_in_and_out_of_universe_returns_400(self, fresh_client):
        # QQQ is in-universe, SPY is not
        res = post_webhook(fresh_client, {
            "strategy_id": "vix",
            "weights": {"QQQ": 0.5, "SPY": 0.5},
        })
        assert res.status_code == 400

    def test_empty_universe_skips_subset_check(self, fresh_client, mock_alpaca):
        # pit_top5 has universe=[] — any ticker should pass
        res = post_webhook(fresh_client, {
            "strategy_id": "pit_top5",
            "weights": {"AAPL": 0.5, "MSFT": 0.5},
        })
        assert res.status_code == 202


# ---------------------------------------------------------------------------
# Success path — non-default strategy
# ---------------------------------------------------------------------------

class TestMultiStrategySuccess:
    def test_trend_broad_success_returns_202(self, fresh_client, mock_alpaca):
        res = post_webhook(fresh_client, {
            "strategy_id": "trend_broad",
            "weights": {"SPY": 0.5, "QQQ": 0.5},
        })
        assert res.status_code == 202

    def test_trend_broad_event_carries_strategy_id(self, fresh_client, mock_alpaca):
        res = post_webhook(fresh_client, {
            "strategy_id": "trend_broad",
            "weights": {"SPY": 0.5, "QQQ": 0.5},
        })
        data = res.get_json()
        assert data["rebalance_event"]["strategy_id"] == "trend_broad"

    def test_alpaca_client_built_with_strategy_creds(self, fresh_client, mock_alpaca):
        """AlpacaClient constructor must be called with the per-strategy env-var values."""
        _, _ = mock_alpaca
        # Set known values for the trend_broad env vars
        os.environ["ALPACA_KEY_TREND"]    = "trend-key-123"
        os.environ["ALPACA_SECRET_TREND"] = "trend-secret-456"

        with patch("app.webhook.AlpacaClient") as patched_cls, \
             patch("app.webhook.OrderExecutor") as patched_exec_cls:
            patched_client = MagicMock()
            patched_client.get_positions.side_effect = (
                lambda target_symbols=None: {s: 0.0 for s in (target_symbols or [])}
            )
            patched_client.get_latest_prices.side_effect = (
                lambda symbols: {s: 100.0 for s in symbols}
            )
            patched_client.get_account_equity.return_value = 10_000.0
            patched_client._base_url = "https://paper-api.alpaca.markets"
            patched_cls.return_value = patched_client

            patched_exec_cls.return_value.execute.return_value = ExecutionResult(
                orders=[OrderResult("SPY", "buy", 5, "uuid-x", True, None)],
                status="success",
            )

            post_webhook(fresh_client, {
                "strategy_id": "trend_broad",
                "weights": {"SPY": 0.5, "QQQ": 0.5},
            })

            call_kwargs = patched_cls.call_args
            assert call_kwargs.kwargs.get("api_key") == "trend-key-123" or \
                   (call_kwargs.args and call_kwargs.args[0] == "trend-key-123")
