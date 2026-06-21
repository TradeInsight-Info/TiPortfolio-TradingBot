"""
Unit tests for POST /webhook.

These tests use Flask's built-in test client and an in-memory SQLite DB,
so no real PostgreSQL or broker connection is needed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from unittest.mock import MagicMock, patch
import pytest

from app.order_executor import ExecutionResult, OrderResult

# Set dummy env vars before importing create_app so startup checks pass
os.environ["ALPACA_API_KEY"]    = "test-key"
os.environ["ALPACA_API_SECRET"] = "test-secret"
os.environ["ALPACA_MODE"]       = "paper"
os.environ["DATABASE_URL"]      = "sqlite:///:memory:"
os.environ["TIPORTFOLIO_MODE"]  = "live"   # prevent simulated (yfinance) mode in tests

from app import create_app  # noqa: E402


@pytest.fixture()
def app():
    """Function-scoped Flask app with its own in-memory SQLite DB and WEBHOOK_SECRET."""
    os.environ["WEBHOOK_SECRET"] = "test-secret"
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def seeded_success_event(app):
    """Seed one successful rebalance so symbol-change tests have a baseline."""
    from app.rebalance import RebalanceRepository
    with app.app_context():
        repo = RebalanceRepository(app.config["DB_SESSION"])
        repo.save(
            target_weights={"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10},
            orders=[],
            status="success",
        )


@pytest.fixture()
def mock_alpaca():
    """
    Patch AlpacaClient and OrderExecutor so happy-path tests
    never need a real Alpaca connection.
    """
    with patch("app.webhook.AlpacaClient") as mock_client_cls, \
         patch("app.webhook.OrderExecutor") as mock_executor_cls:

        # --- AlpacaClient instance mock ---
        mock_client = MagicMock()
        mock_client.get_positions.side_effect = (
            lambda target_symbols=None: {s: 0.0 for s in (target_symbols or [])}
        )
        mock_client.get_latest_prices.side_effect = (
            lambda symbols: {s: 100.0 for s in symbols}
        )
        mock_client.get_account_equity.return_value = 10_000.0
        mock_client._base_url = "https://paper-api.alpaca.markets"
        mock_client_cls.return_value = mock_client   # return AlpacaClient instance

        # --- OrderExecutor instance mock ---
        mock_executor = MagicMock()
        mock_executor.execute.return_value = ExecutionResult(
            orders=[
                OrderResult("SPY", "buy", 10, "uuid-spy", True, None),
                OrderResult("QQQ", "buy",  7, "uuid-qqq", True, None),
                OrderResult("GLD", "buy", 10, "uuid-gld", True, None),
            ],
            status="success",
        )
        mock_executor_cls.return_value = mock_executor   # return OrderExecutor instance

        yield mock_client, mock_executor

@pytest.fixture(scope="module")
def client():
    os.environ["WEBHOOK_SECRET"] = "test-secret"
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def post_webhook(client, payload):
    return client.post(
        "/webhook",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Authorization": "Bearer test-secret"},
    )

# Happy Path
class TestValidPayload:
    def test_returns_202(self, client, mock_alpaca):
        res = post_webhook(client, {"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.3, "GLD": 0.2}})
        assert res.status_code == 202

    def test_body_contains_status_success(self, fresh_client, mock_alpaca):
        res = post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.3, "GLD": 0.2}})
        assert res.get_json()["status"] == "success"

    def test_body_contains_received_at(self, client, mock_alpaca):
        res = post_webhook(client, {"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.3, "GLD": 0.2}})
        data = res.get_json()
        assert "received_at" in data

    def test_body_contains_payload_hash(self, client, mock_alpaca):
        payload = {"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.3, "GLD": 0.2}}
        res = post_webhook(client, payload)
        data = res.get_json()
        assert "payload_hash" in data
        # Verify hash is deterministic: recompute and compare
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert data["payload_hash"] == expected

    def test_weights_summing_to_exactly_1_202(self, fresh_client, mock_alpaca):
        # pit_top5 has an empty universe — any tickers pass the subset check
        res = post_webhook(fresh_client, {"strategy_id": "pit_top5", "weights": {"A": 1.0}})
        assert res.status_code == 202

    def test_weights_within_tolerance_202(self, fresh_client, mock_alpaca):
        # 0.999 is within ±0.01 of 1.0; BIL/QQQ are in the vix universe
        res = post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"QQQ": 0.5, "BIL": 0.499}})
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
            headers={"Authorization": "Bearer test-secret"},
        )
        assert res.status_code == 400
        assert "JSON" in res.get_json()["error"]

    def test_empty_body(self, client):
        res = client.post("/webhook", data="", content_type="application/json",
                         headers={"Authorization": "Bearer test-secret"})
        assert res.status_code == 400

    def test_weights_sum_exceeds_tolerance(self, client):
        # 0.5 + 0.6 = 1.1 → outside ±0.01 tolerance
        res = post_webhook(client, {"weights": {"SPY": 0.5, "QQQ": 0.6}})
        assert res.status_code == 400


@pytest.fixture()
def fresh_client():
    """Function-scoped client — each test gets a new in-memory DB."""
    os.environ["WEBHOOK_SECRET"] = "test-secret"
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestPortfolioEquityAndAudit:
    def test_every_call_fetches_live_equity(self, fresh_client, mock_alpaca):
        mock_client, _ = mock_alpaca
        post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"QQQ": 1.0}})
        post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"BIL": 1.0}})
        assert mock_client.get_account_equity.call_count == 2

    def test_initial_amount_saved_on_first_call(self, fresh_client, mock_alpaca):
        post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"QQQ": 1.0}})
        config = fresh_client.get("/config").get_json()
        assert config["initial_amount"] == 10_000.0

    def test_initial_amount_not_overwritten_on_second_call(self, fresh_client, mock_alpaca):
        mock_client, _ = mock_alpaca
        post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"QQQ": 1.0}})
        mock_client.get_account_equity.return_value = 15_000.0
        post_webhook(fresh_client, {"strategy_id": "vix", "weights": {"BIL": 1.0}})
        config = fresh_client.get("/config").get_json()
        assert config["initial_amount"] == 10_000.0


class TestSymbolUniverseWarning:
    def test_no_warning_on_first_rebalance(self, app, mock_alpaca, caplog):
        # No prior events in DB → no warning; QQQ/BIL are in the vix universe
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"strategy_id": "vix", "weights": {"QQQ": 0.6, "BIL": 0.4}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" not in caplog.text

    def test_warning_when_symbols_change(self, app, mock_alpaca, caplog, seeded_success_event):
        # seeded_success_event has target_weights {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}
        # Incoming payload has only QQQ — universe changed (BIL/GLD dropped)
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"strategy_id": "vix", "weights": {"QQQ": 1.0}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" in caplog.text

    def test_no_warning_when_symbols_same(self, app, mock_alpaca, caplog, seeded_success_event):
        with app.test_client() as client:
            with caplog.at_level(logging.WARNING, logger="app.webhook"):
                resp = client.post(
                    "/webhook",
                    json={"strategy_id": "vix", "weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                    headers={"Authorization": "Bearer test-secret"},
                )
        assert resp.status_code == 202
        assert "symbol_universe_changed" not in caplog.text


class TestPositionDriftLogging:
    def test_no_drift_warning_in_normal_operation(self, app, caplog, seeded_success_event):
        """No drift when Alpaca positions match the last event's target symbols."""
        # seeded_success_event targets QQQ/BIL/GLD
        # mock Alpaca to return exactly those same symbols with non-zero qty
        mock_client = MagicMock()
        mock_client.get_positions.return_value = {"QQQ": 10.0, "BIL": 16.0, "GLD": 2.0}
        mock_client.get_latest_prices.return_value = {"QQQ": 700.0, "BIL": 91.0, "GLD": 413.0}
        mock_client.get_account_equity.return_value = 10_000.0

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="no_change", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"strategy_id": "vix", "weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" not in caplog.text

    def test_drift_warning_when_unexpected_symbol_held(self, app, caplog, seeded_success_event):
        """Drift detected when Alpaca holds an unexpected symbol (SPY position via get_positions)."""
        mock_client = MagicMock()
        # Alpaca has SPY (unexpected) alongside the expected symbols
        mock_client.get_positions.return_value = {"QQQ": 10.0, "BIL": 16.0, "GLD": 2.0, "SPY": 8.0}
        mock_client.get_latest_prices.return_value = {
            "QQQ": 700.0, "BIL": 91.0, "GLD": 413.0, "SPY": 738.0
        }
        mock_client.get_account_equity.return_value = 10_000.0

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="success", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"strategy_id": "vix", "weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" in caplog.text

    def test_no_drift_warning_on_fresh_db(self, app, caplog):
        """No drift warning when there are no prior successful events."""
        mock_client = MagicMock()
        mock_client.get_positions.return_value = {"QQQ": 10.0}
        mock_client.get_latest_prices.return_value = {"QQQ": 700.0}
        mock_client.get_account_equity.return_value = 10_000.0

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="success", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"strategy_id": "vix", "weights": {"QQQ": 1.0}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" not in caplog.text

    def test_drift_warning_when_expected_symbol_missing(self, app, caplog, seeded_success_event):
        """Drift detected when last event targeted GLD but Alpaca no longer holds it."""
        mock_client = MagicMock()
        # GLD was sold out-of-band — qty is 0 so it's excluded from actual_symbols
        mock_client.get_positions.return_value = {"QQQ": 10.0, "BIL": 16.0, "GLD": 0.0}
        mock_client.get_latest_prices.return_value = {"QQQ": 700.0, "BIL": 91.0, "GLD": 413.0}
        mock_client.get_account_equity.return_value = 10_000.0

        with patch("app.webhook.AlpacaClient", return_value=mock_client), \
             patch("app.webhook.OrderExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(
                orders=[], status="success", error_message=None
            )
            with app.test_client() as client:
                with caplog.at_level(logging.WARNING, logger="app.webhook"):
                    client.post(
                        "/webhook",
                        json={"strategy_id": "vix", "weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}},
                        headers={"Authorization": "Bearer test-secret"},
                    )
        assert "position_drift_detected" in caplog.text


# ---------------------------------------------------------------------------
# refresh_fill_status — per-strategy creds
# ---------------------------------------------------------------------------

class TestRefreshFillStatus:
    def test_refresh_uses_per_strategy_creds(self, app):
        """POST /delta/<id>/refresh must build AlpacaClient with the event's strategy creds."""
        from app.rebalance import RebalanceRepository

        os.environ["ALPACA_KEY_TREND"]    = "trend-refresh-key"
        os.environ["ALPACA_SECRET_TREND"] = "trend-refresh-secret"

        pending_order = {
            "symbol": "SPY",
            "direction": "buy",
            "delta_shares": 5,
            "alpaca_order_id": "order-abc",
            "fill_status": "pending",
        }

        with app.app_context():
            repo = RebalanceRepository(app.config["DB_SESSION"])
            event = repo.save(
                target_weights={"SPY": 0.5, "QQQ": 0.5},
                orders=[pending_order],
                status="pending",
                strategy_id="trend_broad",
            )
            event_id = event.id

        mock_alpaca_instance = MagicMock()
        mock_alpaca_instance.get_order.return_value = {
            "id": "order-abc",
            "status": "filled",
            "filled_qty": "5",
            "filled_avg_price": "100.00",
        }

        with patch("app.webhook.AlpacaClient") as patched_cls:
            patched_cls.return_value = mock_alpaca_instance
            with app.test_client() as c:
                res = c.post(
                    f"/delta/{event_id}/refresh",
                    headers={"Authorization": "Bearer test-secret"},
                )

        assert res.status_code == 200
        call_kwargs = patched_cls.call_args
        assert call_kwargs.kwargs.get("api_key") == "trend-refresh-key"
        assert call_kwargs.kwargs.get("api_secret") == "trend-refresh-secret"