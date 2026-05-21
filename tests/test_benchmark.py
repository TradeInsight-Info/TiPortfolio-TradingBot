"""
Unit tests for GET /benchmark.

All yfinance calls and DB queries are mocked - no network calls, no Flask app, no database.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

os.environ["ALPACA_API_KEY"]    = "test-key"
os.environ["ALPACA_API_SECRET"] = "test-secret"
os.environ["ALPACA_MODE"]       = "paper"
os.environ["DATABASE_URL"]      = "sqlite:///:memory:"

from app import create_app        # noqa: E402
import app.benchmark as bm_module  # noqa: E402

# Helpers
def _prices(symbols: list[str], n: int = 5) -> pd.DataFrame:
    """
    Build a closing-price DataFrame for unit tests.
    """
    idx = pd.date_range("2026-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {s: [100.0 + i for i in range(n)] for s in symbols},
        index=idx,
    )

def _make_event(ts: datetime, weights: dict, status: str = "success") -> MagicMock:
    ev = MagicMock()
    ev.timestamp = ts
    ev.target_weights = weights
    ev.status = status
    ev.orders = []
    return ev

def _make_event_with_fills(ts: datetime, orders: list[dict], status: str = "success") -> MagicMock:
    ev = MagicMock()
    ev.timestamp = ts
    ev.target_weights = {}
    ev.status = status
    ev.orders = orders
    return ev

SAMPLE_EVENTS = [
    _make_event(
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        {"SPY": 0.6, "QQQ": 0.4},
    )
]

# Events with filled orders for _portfolio_value_curve tests
# 1 SPY bought on 2026-01-02; prices start at 100.0 and step +1/day
SAMPLE_FILL_EVENTS = [
    _make_event_with_fills(
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        [{"symbol": "SPY", "direction": "buy", "filled_qty": 1.0, "filled_avg_price": 100.0}],
    )
]

# Fixture
@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

@pytest.fixture(autouse=True)
def clear_price_cache():
    """
    Isolate each test by clearing the in-memory price cache.
    """
    bm_module._price_cache.clear()
    yield
    bm_module._price_cache.clear()

# Invalid ticker
class TestInvalidTicker:
    def test_missing_ticker_returns_400(self, client):
        assert client.get("/benchmark").status_code == 400

    def test_unsupported_ticker_returns_400(self, client):
        assert client.get("/benchmark?ticker=INVALID").status_code == 400

    def test_error_message_lists_supported_tickers(self, client):
        body = client.get("/benchmark?ticker=TSLA").get_json()
        assert "SPY" in body["error"]
        assert "QQQ" in body["error"]

    def test_empty_ticker_string_returns_400(self, client):
        assert client.get("/benchmark?ticker=").status_code == 400

# No data
class TestNoData:
    def test_no_rebalance_records_returns_no_data_true(self, client):
        with patch("app.benchmark.RebalanceRepository") as mock_cls:
            mock_cls.return_value.get_all.return_value = []
            res = client.get("/benchmark?ticker=SPY")
        assert res.status_code == 200
        assert res.get_json()["no_data"] is True

    def test_empty_price_df_returns_no_data_true(self, client):
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=pd.DataFrame()):
            mock_cls.return_value.get_all.return_value = SAMPLE_EVENTS
            assert client.get("/benchmark?ticker=SPY").get_json()["no_data"] is True

# Happy path
class TestHappyPath:
    def _spy_response(self, client):
        prices = _prices(["SPY", "QQQ"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices):
            mock_cls.return_value.get_all.return_value = SAMPLE_EVENTS
            return client.get("/benchmark?ticker=SPY")

    def test_spy_returns_200(self, client):
        assert self._spy_response(client).status_code == 200

    def test_no_data_is_false(self, client):
        assert self._spy_response(client).get_json()["no_data"] is False

    def test_response_has_bot_key(self, client):
        assert "bot" in self._spy_response(client).get_json()

    def test_response_has_benchmark_key(self, client):
        assert "benchmark" in self._spy_response(client).get_json()

    def test_ticker_reflected_in_response(self, client):
        assert self._spy_response(client).get_json()["ticker"] == "SPY"

    def test_first_rebalance_date_present(self, client):
        body = self._spy_response(client).get_json()
        assert body["first_rebalance_date"] == "2026-01-02"

    def test_bot_series_items_have_date_and_value_keys(self, client):
        for item in self._spy_response(client).get_json()["bot"]:
            assert "date" in item and "value" in item

    def test_composite_ticker_url_encoded_returns_200(self, client):
        prices = _prices(["QQQ", "GLD", "BIL"])
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", return_value=prices):
            mock_cls.return_value.get_all.return_value = SAMPLE_EVENTS
            res = client.get("/benchmark?ticker=QQQ%2BGLD%2BBIL")
        assert res.status_code == 200
        assert res.get_json()["ticker"] == "QQQ+GLD+BIL"

# yfinance failure
class TestYfinanceFailure:
    def test_yfinance_exception_returns_502(self, client):
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", side_effect=RuntimeError("network down")):
            mock_cls.return_value.get_all.return_value = SAMPLE_EVENTS
            assert client.get("/benchmark?ticker=SPY").status_code == 502

    def test_502_body_contains_error_key(self, client):
        with patch("app.benchmark.RebalanceRepository") as mock_cls, \
             patch("app.benchmark._get_prices", side_effect=RuntimeError("timeout")):
            mock_cls.return_value.get_all.return_value = SAMPLE_EVENTS
            assert "error" in client.get("/benchmark?ticker=SPY").get_json()

# Caching
class TestCaching:
    def test_second_call_same_day_skips_download(self):
        prices = _prices(["SPY"])
        with patch("app.benchmark._download_prices", return_value=prices) as mock_dl:
            bm_module._get_prices(["SPY"], prices.index[0].date(), prices.index[-1].date())
            bm_module._get_prices(["SPY"], prices.index[0].date(), prices.index[-1].date())
        assert mock_dl.call_count == 1

    def test_different_symbol_sets_cached_separately(self):
        with patch("app.benchmark._download_prices",
                   side_effect=[_prices(["SPY"]), _prices(["QQQ"])]) as mock_dl:
            p = _prices(["SPY"])
            bm_module._get_prices(["SPY"], p.index[0].date(), p.index[-1].date())
            bm_module._get_prices(["QQQ"], p.index[0].date(), p.index[-1].date())
        assert mock_dl.call_count == 2

# Portfolio value curve unit tests
class TestPortfolioValueCurve:
    def test_empty_events_returns_empty_series(self):
        assert bm_module._portfolio_value_curve([], _prices(["SPY"])).empty

    def test_returns_usd_value_on_first_day(self):
        # 1 SPY held; prices[0] = 100.0 → value = 100.0
        prices = _prices(["SPY"], n=5)
        result = bm_module._portfolio_value_curve(SAMPLE_FILL_EVENTS, prices)
        assert not result.empty
        assert result.iloc[0] == pytest.approx(100.0)

    def test_curve_length_matches_price_rows_when_fully_held(self):
        prices = _prices(["SPY"], n=5)
        result = bm_module._portfolio_value_curve(SAMPLE_FILL_EVENTS, prices)
        assert len(result) == len(prices)

_FIRST_DATE = date(2026, 1, 2)  # matches the start of _prices() fixtures

class TestBenchmarkCurve:
    def test_spy_curve_starts_at_1(self):
        assert round(bm_module._benchmark_curve("SPY", _prices(["SPY"]), _FIRST_DATE).iloc[0], 6) == 1.0

    def test_missing_ticker_returns_empty_series(self):
        assert bm_module._benchmark_curve("SPY", _prices(["QQQ"]), _FIRST_DATE).empty

    def test_composite_curve_starts_at_1(self):
        result = bm_module._benchmark_curve("QQQ+GLD+BIL", _prices(["QQQ", "GLD", "BIL"]), _FIRST_DATE)
        assert round(result.iloc[0], 6) == 1.0

    def test_composite_with_missing_component_still_works(self):
        result = bm_module._benchmark_curve("QQQ+GLD+BIL", _prices(["QQQ", "GLD"]), _FIRST_DATE)
        assert not result.empty