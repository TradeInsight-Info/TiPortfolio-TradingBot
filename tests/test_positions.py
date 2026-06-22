"""Tests for GET /positions."""
from __future__ import annotations
import os
from unittest.mock import patch, MagicMock, call
import pytest

os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("ALPACA_KEY_VIX",    "vix-key")
os.environ.setdefault("ALPACA_SECRET_VIX", "vix-secret")
os.environ.setdefault("ALPACA_KEY_TREND",  "trend-key")
os.environ.setdefault("ALPACA_SECRET_TREND", "trend-secret")

from app import create_app  # noqa: E402
import app.positions as positions_module  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache():
    """Reset module-level cache between tests."""
    positions_module._cache.clear()
    yield
    positions_module._cache.clear()


@pytest.fixture()
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


MOCK_POSITIONS = [
    {"symbol": "QQQ", "qty": 10.0, "market_value": 7175.40, "avg_entry_price": 700.75},
    {"symbol": "BIL", "qty": 16.0, "market_value": 1465.44, "avg_entry_price": 91.54},
]
MOCK_ACCOUNT = {"equity": 9468.00, "cash": 0.0}


def _mock_alpaca():
    mock = MagicMock()
    mock.list_positions_full.return_value = MOCK_POSITIONS
    mock.get_account.return_value = MOCK_ACCOUNT
    return mock


class TestGetPositions:
    def test_returns_live_positions_from_alpaca(self, app):
        with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["equity"] == 9468.00
        assert data["cash"] == 0.0
        assert len(data["positions"]) == 2
        assert data["positions"][0]["symbol"] == "QQQ"
        assert "as_of" in data

    def test_caches_response_within_ttl(self, app):
        mock_alpaca = _mock_alpaca()
        with patch("app.positions.AlpacaClient", return_value=mock_alpaca):
            with app.test_client() as client:
                client.get("/positions")
                client.get("/positions")
        # Alpaca only called once — second request served from cache
        assert mock_alpaca.list_positions_full.call_count == 1

    def test_serves_stale_on_alpaca_failure_when_cache_exists(self, app):
        from app.alpaca_client import AlpacaError
        # Prime the cache
        with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
            with app.test_client() as client:
                client.get("/positions")

        # Expire cache by backdating it (cache is keyed by None for default path)
        from datetime import timedelta
        positions_module._cache[None]["fetched_at"] -= timedelta(hours=2)

        # Alpaca now fails
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError("timeout")
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stale"] is True

    def test_returns_503_when_alpaca_down_and_no_cache(self, app):
        from app.alpaca_client import AlpacaError
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError("timeout")
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 503


class TestGetPositionsStrategyAware:
    def test_uses_per_strategy_creds_when_strategy_id_given(self, app):
        """AlpacaClient is constructed with the strategy's env creds, not config defaults."""
        with patch("app.positions.AlpacaClient") as MockClient:
            MockClient.return_value = _mock_alpaca()
            with app.test_client() as client:
                resp = client.get("/positions?strategy_id=vix")
        assert resp.status_code == 200
        MockClient.assert_called_once_with(
            api_key="vix-key",
            api_secret="vix-secret",
            mode="paper",
        )

    def test_different_strategies_use_separate_cache_entries(self, app):
        """Two different strategy_ids each call Alpaca once — cache is not shared."""
        with patch("app.positions.AlpacaClient") as MockClient:
            MockClient.return_value = _mock_alpaca()
            with app.test_client() as client:
                client.get("/positions?strategy_id=vix")
                client.get("/positions?strategy_id=trend_broad")
        # Each strategy must hit Alpaca independently
        assert MockClient.call_count == 2
        call_args = [c.kwargs for c in MockClient.call_args_list]
        assert call_args[0]["api_key"] == "vix-key"
        assert call_args[1]["api_key"] == "trend-key"

    def test_unknown_strategy_id_returns_400(self, app):
        with patch("app.positions.AlpacaClient", return_value=_mock_alpaca()):
            with app.test_client() as client:
                resp = client.get("/positions?strategy_id=nonexistent")
        assert resp.status_code == 400
        assert "Unknown strategy_id" in resp.get_json()["error"]

    def test_no_strategy_id_uses_default_config_creds(self, app):
        """Backward compat: omitting strategy_id uses ALPACA_API_KEY/SECRET from config."""
        with patch("app.positions.AlpacaClient") as MockClient:
            MockClient.return_value = _mock_alpaca()
            with app.test_client() as client:
                resp = client.get("/positions")
        assert resp.status_code == 200
        MockClient.assert_called_once_with(
            api_key=app.config["ALPACA_API_KEY"],
            api_secret=app.config["ALPACA_API_SECRET"],
            mode=app.config["ALPACA_MODE"],
        )

    def test_empty_creds_returns_not_configured_without_calling_alpaca(self, app, monkeypatch):
        """When a strategy's creds are not in env, return 200 configured:false without calling Alpaca."""
        monkeypatch.delenv("ALPACA_KEY_VIX", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_VIX", raising=False)
        with patch("app.positions.AlpacaClient") as MockClient:
            with app.test_client() as client:
                resp = client.get("/positions?strategy_id=vix")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["configured"] is False
        assert data["positions"] == []
        assert data["equity"] is None
        assert data["cash"] is None
        MockClient.assert_not_called()

    def test_alpaca_401_returns_not_configured(self, app):
        """Alpaca 401/unauthorized → 200 configured:false (not a 503 error)."""
        from app.alpaca_client import AlpacaError
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError(
            "Alpaca API returned HTTP 401: unauthorized", status_code=401
        )
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions?strategy_id=vix")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["configured"] is False
        assert data["positions"] == []

    def test_non_401_alpaca_error_still_returns_503(self, app):
        """Non-401 AlpacaErrors still produce 503 (regression guard)."""
        from app.alpaca_client import AlpacaError
        failing = MagicMock()
        failing.list_positions_full.side_effect = AlpacaError("connection timeout")
        with patch("app.positions.AlpacaClient", return_value=failing):
            with app.test_client() as client:
                resp = client.get("/positions?strategy_id=vix")
        assert resp.status_code == 503
