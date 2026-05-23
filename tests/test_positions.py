"""Tests for GET /positions."""
from __future__ import annotations
import os
from unittest.mock import patch, MagicMock
import pytest

os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")

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

        # Expire cache by backdating it
        from datetime import timedelta
        positions_module._cache["fetched_at"] -= timedelta(hours=2)

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
