"""
Multi-strategy tests for GET /strategies, GET /delta, and GET /benchmark.

Route-level tests mock RebalanceRepository (same pattern as test_benchmark.py)
to avoid DB session wiring issues between the Flask test client and conftest fixtures.

Repo-layer tests use the conftest `repo` fixture against the real (isolated) DB session.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")

from app import create_app  # noqa: E402
import app.benchmark as bm_module  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────

_ORDERS_VIX = [
    {"symbol": "QQQ", "direction": "buy", "delta_shares": 5,
     "filled_qty": 5.0, "filled_avg_price": 400.0, "fill_status": "filled",
     "status": "accepted", "portfolio_value": 2000.0},
]

_ORDERS_TREND = [
    {"symbol": "SPY", "direction": "buy", "delta_shares": 3,
     "filled_qty": 3.0, "filled_avg_price": 500.0, "fill_status": "filled",
     "status": "accepted", "portfolio_value": 1500.0},
]


def _make_event(ts: datetime, orders: list[dict], strategy_id: str) -> MagicMock:
    ev = MagicMock()
    ev.timestamp = ts
    ev.target_weights = {"SPY": 1.0}
    ev.status = "success"
    ev.orders = orders
    ev.strategy_id = strategy_id
    ev.id = hash(strategy_id + ts.isoformat())
    return ev


_TS_VIX   = datetime(2026, 1, 2, tzinfo=timezone.utc)
_TS_TREND = datetime(2026, 1, 3, tzinfo=timezone.utc)

_EVENT_VIX   = _make_event(_TS_VIX,   _ORDERS_VIX,   "vix")
_EVENT_TREND = _make_event(_TS_TREND, _ORDERS_TREND, "trend_broad")
_ALL_EVENTS  = [_EVENT_VIX, _EVENT_TREND]

_VIX_ONLY   = [_EVENT_VIX]
_TREND_ONLY = [_EVENT_TREND]


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def clear_benchmark_cache():
    bm_module._price_cache.clear()
    bm_module._portfolio_hist_cache.clear()
    yield
    bm_module._price_cache.clear()
    bm_module._portfolio_hist_cache.clear()


def _prices(symbols: list[str], n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {s: [100.0 + i for i in range(n)] for s in symbols},
        index=idx,
    )


# ─── GET /strategies ────────────────────────────────────────────────────────

class TestListStrategies:
    def test_returns_200(self, client):
        assert client.get("/strategies").status_code == 200

    def test_returns_three_entries(self, client):
        body = client.get("/strategies").get_json()
        assert len(body) == 3

    def test_each_entry_has_id_and_name(self, client):
        for item in client.get("/strategies").get_json():
            assert "id" in item
            assert "name" in item

    def test_known_strategy_ids_present(self, client):
        ids = {item["id"] for item in client.get("/strategies").get_json()}
        assert {"vix", "trend_broad", "pit_top5"} == ids


# ─── GET /delta — strategy_id filtering ─────────────────────────────────────

class TestDeltaStrategyFilter:
    def test_no_param_returns_all(self, client):
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_cls.return_value.get_all.return_value = _ALL_EVENTS
            resp = client.get("/delta")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["count"] == 2

    def test_strategy_id_filters_to_matching_events(self, client):
        """Assert response shape only (real DB-level filtering is covered by TestRepoStrategyFilter)."""
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_cls.return_value.get_all.return_value = _TREND_ONLY
            resp = client.get("/delta?strategy_id=trend_broad")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["count"] == 1
        assert body["events"][0]["strategy_id"] == "trend_broad"

    def test_get_all_called_with_strategy_id(self, client):
        """Repo layer receives the strategy_id argument."""
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_repo = mock_cls.return_value
            mock_repo.get_all.return_value = _TREND_ONLY
            client.get("/delta?strategy_id=trend_broad")
        mock_repo.get_all.assert_called_once_with("trend_broad")

    def test_get_all_called_without_strategy_id_by_default(self, client):
        with patch("app.webhook.RebalanceRepository") as mock_cls:
            mock_repo = mock_cls.return_value
            mock_repo.get_all.return_value = _ALL_EVENTS
            client.get("/delta")
        mock_repo.get_all.assert_called_once_with(None)

    def test_unknown_strategy_id_returns_400(self, client):
        resp = client.get("/delta?strategy_id=not_a_strategy")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_400_error_message_mentions_strategy_id(self, client):
        body = client.get("/delta?strategy_id=bogus").get_json()
        assert "bogus" in body["error"]


# ─── GET /benchmark — strategy_id filtering ─────────────────────────────────

class TestBenchmarkStrategyFilter:
    def test_unknown_strategy_id_returns_400(self, client):
        resp = client.get("/benchmark?strategy_id=no_such&ticker=SPY")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_known_strategy_id_with_ticker_returns_200(self, client):
        prices = _prices(["SPY"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)):
            mock_cls.return_value.get_all.return_value = []
            resp = client.get("/benchmark?strategy_id=vix&ticker=SPY")
        # no events → no_data (no config row in sqlite test DB)
        assert resp.status_code == 200

    def test_repo_get_all_called_with_strategy_id(self, client):
        """Repo layer receives the strategy_id argument on /benchmark."""
        prices = _prices(["SPY"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)):
            mock_repo = mock_cls.return_value
            mock_repo.get_all.return_value = [_EVENT_VIX]
            client.get("/benchmark?strategy_id=vix&ticker=SPY")
        mock_repo.get_all.assert_called_once_with("vix")

    def test_benchmark_scoped_to_strategy_excludes_other_strategy_events(self, client):
        """
        When strategy_id=vix, only vix events feed the equity curve.
        trend_broad events should not appear.
        """
        prices = _prices(["SPY"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)):
            mock_repo = mock_cls.return_value
            # Simulate the repo returning only vix events (as the real filtered query would)
            mock_repo.get_all.return_value = _VIX_ONLY
            resp = client.get("/benchmark?strategy_id=vix&ticker=SPY")
        assert resp.status_code == 200
        mock_repo.get_all.assert_called_with("vix")

    def test_strategy_default_benchmark_used_when_ticker_absent(self, client):
        """
        vix strategy's benchmark is QQQ; omitting ticker should resolve to QQQ.
        """
        prices = _prices(["QQQ"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)):
            mock_cls.return_value.get_all.return_value = [_EVENT_VIX]
            resp = client.get("/benchmark?strategy_id=vix")
        assert resp.status_code == 200
        assert resp.get_json()["ticker"] == "QQQ"

    def test_alpaca_equity_curve_receives_strategy_creds(self, client):
        """
        _alpaca_equity_curve is called with strategy-scoped key/secret/strategy_id.
        """
        prices = _prices(["SPY"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)) as mock_eq, \
             patch.dict(os.environ, {"ALPACA_KEY_VIX": "vix-key", "ALPACA_SECRET_VIX": "vix-secret"}):
            mock_cls.return_value.get_all.return_value = [_EVENT_VIX]
            client.get("/benchmark?strategy_id=vix&ticker=SPY")
        mock_eq.assert_called_once()
        call_kwargs = mock_eq.call_args
        assert call_kwargs.kwargs.get("api_key") == "vix-key"
        assert call_kwargs.kwargs.get("api_secret") == "vix-secret"
        assert call_kwargs.kwargs.get("strategy_id") == "vix"

    def test_unset_strategy_env_vars_pass_empty_string_not_config_default(self, client):
        """
        When strategy env vars are unset, _alpaca_equity_curve is called with
        empty-string creds — NOT the config default — so auth fails visibly
        instead of silently falling back to the default Alpaca account.
        """
        prices = _prices(["SPY"])
        config_key    = "test-key"     # matches os.environ.setdefault at module top
        config_secret = "test-secret"
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices), \
             patch("app.benchmark._alpaca_equity_curve", return_value=pd.Series(dtype=float)) as mock_eq, \
             patch.dict(os.environ, {}, clear=False):
            # Ensure the strategy's env vars are absent
            os.environ.pop("ALPACA_KEY_VIX",    None)
            os.environ.pop("ALPACA_SECRET_VIX", None)
            mock_cls.return_value.get_all.return_value = [_EVENT_VIX]
            client.get("/benchmark?strategy_id=vix&ticker=SPY")
        mock_eq.assert_called_once()
        call_kwargs = mock_eq.call_args
        # Must be empty string — NOT the config defaults
        assert call_kwargs.kwargs.get("api_key")    == ""
        assert call_kwargs.kwargs.get("api_secret") == ""
        assert call_kwargs.kwargs.get("api_key")    != config_key
        assert call_kwargs.kwargs.get("api_secret") != config_secret


# ─── Repo layer — strategy_id filter ────────────────────────────────────────

class TestRepoStrategyFilter:
    """
    Integration tests against the real DB session (conftest fixtures).
    These verify the SQL filter is wired correctly.
    """

    def test_get_all_no_filter_returns_all(self, repo):
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_VIX,
            status="success",
            strategy_id="vix",
        )
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_TREND,
            status="success",
            strategy_id="trend_broad",
        )
        all_events = repo.get_all()
        assert len(all_events) == 2

    def test_get_all_filters_by_strategy_id(self, repo):
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_VIX,
            status="success",
            strategy_id="vix",
        )
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_TREND,
            status="success",
            strategy_id="trend_broad",
        )
        vix_events = repo.get_all(strategy_id="vix")
        assert all(e.strategy_id == "vix" for e in vix_events)
        assert len(vix_events) == 1

    def test_get_since_filters_by_strategy_id(self, repo):
        ts_early = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts_late  = datetime(2026, 1, 3, tzinfo=timezone.utc)
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_VIX,
            status="success",
            strategy_id="vix",
            timestamp=ts_late,
        )
        repo.save(
            target_weights={"SPY": 1.0},
            orders=_ORDERS_TREND,
            status="success",
            strategy_id="trend_broad",
            timestamp=ts_late,
        )
        since_dt = datetime(2026, 1, 2, tzinfo=timezone.utc)
        trend_events = repo.get_since(since_dt, strategy_id="trend_broad")
        assert all(e.strategy_id == "trend_broad" for e in trend_events)
        assert len(trend_events) == 1
        # vix event is invisible
        assert not any(e.strategy_id == "vix" for e in trend_events)
