"""
Unit tests for the bounded lazy fill-reconcile logic added to GET /delta.

These tests exercise reconcile_pending() and _reconcile_event() directly —
no DB or real Alpaca connection needed.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

# Set env vars before importing the app so startup checks pass
os.environ.setdefault("ALPACA_API_KEY",    "test-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-secret")
os.environ.setdefault("ALPACA_MODE",       "paper")
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("TIPORTFOLIO_MODE",  "live")
os.environ.setdefault("WEBHOOK_SECRET",    "test-secret")

from app import create_app                          # noqa: E402
import app.webhook as wh                            # noqa: E402
from app.alpaca_client import AlpacaError           # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_id: int = 1,
    strategy_id: str = "pit_top5",
    orders: list[dict] | None = None,
    age_days: float = 0.0,
) -> MagicMock:
    """Return a MagicMock that looks like a RebalanceEvent."""
    event = MagicMock()
    event.id = event_id
    event.strategy_id = strategy_id
    event.timestamp = datetime.now(timezone.utc) - timedelta(days=age_days)
    event.orders = orders or []
    return event


def _pending_order(order_id: str = "ord-1") -> dict:
    return {
        "symbol": "SPY",
        "direction": "buy",
        "delta_shares": 5,
        "alpaca_order_id": order_id,
        "fill_status": "accepted",
    }


def _filled_response(order_id: str = "ord-1") -> dict:
    return {
        "id": order_id,
        "status": "filled",
        "filled_qty": "5",
        "filled_avg_price": "100.00",
    }


@pytest.fixture()
def flask_ctx():
    """Push a minimal Flask app context so current_app.config is available."""
    flask_app = create_app()
    flask_app.config["ALPACA_MODE"] = "paper"
    ctx = flask_app.app_context()
    ctx.push()
    yield flask_app
    ctx.pop()


@pytest.fixture(autouse=True)
def clear_cooldown():
    """Reset the module-level cooldown dict between tests."""
    wh._reconcile_cooldown.clear()
    yield
    wh._reconcile_cooldown.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReconcileEvent:
    def test_pending_order_updated(self, flask_ctx):
        """A pending order gets re-polled and repo.update_orders receives filled values."""
        event = _make_event(orders=[_pending_order()])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = _filled_response()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance) as patched_cls:
            wh._reconcile_event(event, repo)

        mock_instance.get_order.assert_called_once_with("ord-1")
        updated_orders = repo.update_orders.call_args[0][1]
        assert updated_orders[0]["fill_status"] == "filled"
        assert updated_orders[0]["filled_qty"] == 5.0
        assert updated_orders[0]["filled_avg_price"] == 100.0

    def test_terminal_order_skipped(self, flask_ctx):
        """An order already in a terminal state is not re-polled."""
        order = _pending_order()
        order["fill_status"] = "filled"
        event = _make_event(orders=[order])
        repo = MagicMock()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient") as patched_cls:
            wh._reconcile_event(event, repo)

        patched_cls.assert_not_called()
        repo.update_orders.assert_not_called()

    def test_partially_filled_order_is_repolled_and_corrected(self, flask_ctx):
        """Regression: pit_top5 event 15 recorded MRNA sold 12.0 when 13.845621 had
        actually filled. partially_filled was treated as settled, so the record froze
        at the first chunk Alpaca reported and was never revisited."""
        order = _pending_order()
        order["fill_status"] = "partially_filled"
        order["filled_qty"] = 12.0
        event = _make_event(orders=[order])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = {
            "status": "filled", "filled_qty": "13.845621", "filled_avg_price": "143.175",
        }

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)

        mock_instance.get_order.assert_called_once_with("ord-1")
        updated = repo.update_orders.call_args[0][1]
        assert updated[0]["fill_status"] == "filled"
        assert updated[0]["filled_qty"] == 13.845621

    def test_partially_filled_records_its_quantity(self, flask_ctx):
        """Still partial on re-poll: keep the newest quantity rather than dropping it."""
        order = _pending_order()
        order["fill_status"] = "accepted"
        event = _make_event(orders=[order])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = {
            "status": "partially_filled", "filled_qty": "7", "filled_avg_price": "99.5",
        }

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)

        updated = repo.update_orders.call_args[0][1]
        assert updated[0]["fill_status"] == "partially_filled"
        assert updated[0]["filled_qty"] == 7.0

    def test_alpaca_error_does_not_raise(self, flask_ctx):
        """An AlpacaError on get_order is swallowed; the function returns normally."""
        event = _make_event(orders=[_pending_order()])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.side_effect = AlpacaError("timeout")

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)   # must not raise

        repo.update_orders.assert_not_called()

    def test_uncredentialed_strategy_skipped(self, flask_ctx):
        """If env vars for the strategy are empty, no Alpaca call is made."""
        os.environ.pop("ALPACA_KEY_PIT", None)
        os.environ.pop("ALPACA_SECRET_PIT", None)

        event = _make_event(orders=[_pending_order()])
        repo = MagicMock()

        with patch("app.webhook.AlpacaClient") as patched_cls:
            wh._reconcile_event(event, repo)

        patched_cls.assert_not_called()
        repo.update_orders.assert_not_called()


class TestReconcilePending:
    def test_cooldown_blocks_second_call(self, flask_ctx):
        """Two back-to-back reconcile_pending calls only trigger one Alpaca call."""
        event = _make_event(event_id=42, orders=[_pending_order()])
        repo = MagicMock()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = _filled_response()

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh.reconcile_pending([event], repo)
            # Second call immediately after — cooldown should block it
            wh.reconcile_pending([event], repo)

        assert mock_instance.get_order.call_count == 1

    def test_event_older_than_7d_skipped(self, flask_ctx):
        """Events older than 7 days are not reconciled."""
        event = _make_event(age_days=8, orders=[_pending_order()])
        repo = MagicMock()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient") as patched_cls:
            wh.reconcile_pending([event], repo)

        patched_cls.assert_not_called()
        repo.update_orders.assert_not_called()

    def test_all_terminal_events_make_no_alpaca_calls(self, flask_ctx):
        """An event whose orders are all terminal triggers no Alpaca calls."""
        order = _pending_order()
        order["fill_status"] = "canceled"
        event = _make_event(orders=[order])
        repo = MagicMock()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient") as patched_cls:
            wh.reconcile_pending([event], repo)

        patched_cls.assert_not_called()

    def test_in_memory_event_updated_after_reconcile(self, flask_ctx):
        """After reconcile, event.orders reflects the new status (same-response freshness)."""
        event = _make_event(orders=[_pending_order()])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = _filled_response()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)

        assert event.orders[0]["fill_status"] == "filled"

    def test_identical_status_does_not_call_update_orders(self, flask_ctx):
        """A re-poll that returns the same status as already stored skips the DB write."""
        order = _pending_order()
        order["fill_status"] = "accepted"  # already stored as accepted
        event = _make_event(orders=[order])
        repo = MagicMock()

        mock_instance = MagicMock()
        # Alpaca returns the same status — no change
        mock_instance.get_order.return_value = {"id": "ord-1", "status": "accepted"}

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)

        repo.update_orders.assert_not_called()

    def test_all_terminal_prunes_cooldown_entry(self, flask_ctx):
        """After reconcile makes all orders terminal, the cooldown entry is removed."""
        event = _make_event(event_id=99, orders=[_pending_order()])
        repo = MagicMock()

        mock_instance = MagicMock()
        mock_instance.get_order.return_value = _filled_response()

        os.environ["ALPACA_KEY_PIT"] = "pit-key"
        os.environ["ALPACA_SECRET_PIT"] = "pit-secret"

        # Seed the cooldown dict so we can verify removal
        wh._reconcile_cooldown[99] = time.monotonic()

        with patch("app.webhook.AlpacaClient", return_value=mock_instance):
            wh._reconcile_event(event, repo)

        assert 99 not in wh._reconcile_cooldown


class TestGetDeltaIntegration:
    def test_reconcile_runs_and_response_shows_filled(self):
        """GET /delta end-to-end: repo returns a pending event, Alpaca confirms filled,
        the same HTTP response body reflects fill_status == 'filled'."""
        os.environ["ALPACA_KEY_VIX"] = "vix-key"
        os.environ["ALPACA_SECRET_VIX"] = "vix-secret"

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["ALPACA_MODE"] = "paper"

        event = _make_event(event_id=7, strategy_id="vix", orders=[_pending_order()])
        event.status = "success"

        stub_repo = MagicMock()
        stub_repo.get_all.return_value = [event]
        stub_repo.update_orders = MagicMock()

        mock_alpaca = MagicMock()
        mock_alpaca.get_order.return_value = _filled_response()

        with patch("app.webhook.RebalanceRepository", return_value=stub_repo), \
             patch("app.webhook.AlpacaClient", return_value=mock_alpaca):
            with flask_app.test_client() as c:
                res = c.get("/delta?strategy_id=vix")

        assert res.status_code == 200
        body = res.get_json()
        assert body["count"] == 1
        order = body["events"][0]["orders"][0]
        assert order["fill_status"] == "filled"
