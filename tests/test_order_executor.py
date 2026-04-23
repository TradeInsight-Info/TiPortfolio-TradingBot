"""
Unit tests for OrderExecutor and serialize_orders().

All HTTP calls are mocked - no network calls, no Flask app, no database.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
import requests

from app.calculator import OrderDelta
from app.order_executor import (
    OrderExecutor,
    OrderResult,
    serialize_orders,
)

# Shared fixtures
BASE_URL = "https://paper-api.alpaca.markets"

def make_executor() -> OrderExecutor:
    return OrderExecutor(
        api_key="test-key",
        api_secret="test-secret",
        base_url=BASE_URL,
    )

def make_delta(symbol: str, delta: int) -> OrderDelta:
    return OrderDelta(
        symbol=symbol,
        delta=delta,
        current_shares=0.0,
        target_shares=abs(delta),
    )

def mock_alpaca_response(order_id: str, status_code: int = 201) -> MagicMock:
    """
    Build a successful fake Alpaca POST /v2/orders response.
    
    Args:
        order_id: The Alpaca order ID to return in the response.
        status_code: The HTTP status code to return (default 201 Created).
        
    Returns:
        A MagicMock that simulates a successful Alpaca API response.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"id": order_id, "status": "accepted"}
    resp.text = f'{{"id": "{order_id}"}}'
    resp.raise_for_status.return_value = None
    return resp

def mock_error_response(status_code: int, body: str = "error") -> MagicMock:
    """
    Build a failed Alpaca response that raises HTTPError on raise_for_status.
    
    Args:
        status_code: The HTTP status code to return.
        body: The error message text to return.
        
    Returns:
        A MagicMock that simulates a failed Alpaca API response.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = body
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=resp
    )
    return resp

# Zero-delta
class TestZeroDelta:
    def test_empty_delta_list_returns_failed_status(self):
        result = make_executor().execute([])
        assert result.status == "failed"

    def test_empty_delta_list_has_no_orders(self):
        result = make_executor().execute([])
        assert result.orders == []

    def test_empty_delta_list_has_error_message(self):
        result = make_executor().execute([])
        assert result.error_message is not None
        assert "zero" in result.error_message.lower()

    def test_empty_delta_list_makes_no_http_calls(self):
        with patch("app.order_executor.requests.post") as mock_post:
            make_executor().execute([])
            mock_post.assert_not_called()

    def test_inline_zero_delta_is_skipped(self):
        """
        A zero-delta slipping through calculate_deltas must not be submitted.
        """
        zero_delta = make_delta("SPY", 0)
        with patch("app.order_executor.requests.post") as mock_post:
            make_executor().execute([zero_delta])
            mock_post.assert_not_called()   # If requests.post has been called, then the test should fail.

# Buy orders (delta > 0)
class TestBuyOrders:
    def test_positive_delta_submits_buy(self):
        resp = mock_alpaca_response("order-buy-001")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("SPY", 5)])
            _, kwargs = mock_post.call_args
            assert kwargs["json"]["side"] == "buy"

    def test_buy_qty_equals_absolute_delta(self):
        resp = mock_alpaca_response("order-buy-002")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("QQQ", 3)])
            assert mock_post.call_args[1]["json"]["qty"] == "3"

    def test_buy_order_captures_alpaca_order_id(self):
        resp = mock_alpaca_response("uuid-buy-123")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([make_delta("AAPL", 10)])
        assert result.orders[0].alpaca_order_id == "uuid-buy-123"

    def test_buy_order_result_success_is_true(self):
        resp = mock_alpaca_response("any-id")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([make_delta("GLD", 2)])
        assert result.orders[0].success is True

# Sell orders (delta < 0)
class TestSellOrders:
    def test_negative_delta_submits_sell(self):
        resp = mock_alpaca_response("order-sell-001")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("SPY", -5)])
            assert mock_post.call_args[1]["json"]["side"] == "sell"

    def test_sell_qty_is_absolute_value_of_delta(self):
        resp = mock_alpaca_response("order-sell-002")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("QQQ", -7)])
            assert mock_post.call_args[1]["json"]["qty"] == "7"

    def test_sell_order_captures_alpaca_order_id(self):
        resp = mock_alpaca_response("uuid-sell-456")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([make_delta("TSLA", -3)])
        assert result.orders[0].alpaca_order_id == "uuid-sell-456"

# Order payload shape
class TestOrderPayload:
    def test_order_type_is_market(self):
        resp = mock_alpaca_response("id-mkt")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("SPY", 1)])
            assert mock_post.call_args[1]["json"]["type"] == "market"

    def test_time_in_force_is_day(self):
        resp = mock_alpaca_response("id-day")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("GLD", 1)])
            assert mock_post.call_args[1]["json"]["time_in_force"] == "day"

    def test_symbol_in_payload_matches_delta(self):
        resp = mock_alpaca_response("id-sym")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("NVDA", 4)])
            assert mock_post.call_args[1]["json"]["symbol"] == "NVDA"

    def test_endpoint_is_v2_orders(self):
        resp = mock_alpaca_response("id-url")
        with patch("app.order_executor.requests.post", return_value=resp) as mock_post:
            make_executor().execute([make_delta("SPY", 1)])
            called_url = mock_post.call_args[0][0]
            assert called_url.endswith("/v2/orders")

# All-success -> ExecutionResult.status == "success"
class TestAllSuccessStatus:
    def test_single_order_success_returns_success_status(self):
        resp = mock_alpaca_response("ok-1")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([make_delta("SPY", 1)])
        assert result.status == "success"

    def test_multiple_orders_all_succeed_returns_success(self):
        resp = mock_alpaca_response("ok-multi")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([
                make_delta("SPY", 2),
                make_delta("QQQ", -1),
                make_delta("GLD", 3),
            ])
        assert result.status == "success"

    def test_success_status_has_no_error_message(self):
        resp = mock_alpaca_response("ok-2")
        with patch("app.order_executor.requests.post", return_value=resp):
            result = make_executor().execute([make_delta("AAPL", 5)])
        assert result.error_message is None

# Single order failure -> remaining orders still attempted
class TestPartialFailure:
    def test_one_failure_does_not_abort_remaining_orders(self):
        """
        Orders: SPY (fail), QQQ (success), GLD (success).
        All three POST calls must be made despite SPY failing.
        """
        fail_resp  = mock_error_response(422, "insufficient funds")
        ok_resp    = mock_alpaca_response("ok-qqq")
        ok_resp2   = mock_alpaca_response("ok-gld")

        with patch(
            "app.order_executor.requests.post",
            side_effect=[fail_resp, ok_resp, ok_resp2],
        ) as mock_post:
            result = make_executor().execute([
                make_delta("SPY", 10),
                make_delta("QQQ", -5),
                make_delta("GLD", 2),
            ])
            assert mock_post.call_count == 3

    def test_partial_failure_returns_partial_status(self):
        fail_resp = mock_error_response(400)
        ok_resp   = mock_alpaca_response("ok-partial")

        with patch(
            "app.order_executor.requests.post",
            side_effect=[fail_resp, ok_resp],   # side_effect: Return different values ​​in sequence or throw an exception
        ):
            result = make_executor().execute([
                make_delta("SPY", 5),
                make_delta("QQQ", 3),
            ])
        assert result.status == "partial"

    def test_partial_failure_has_error_message(self):
        fail_resp = mock_error_response(422)
        ok_resp   = mock_alpaca_response("ok")

        with patch(
            "app.order_executor.requests.post",
            side_effect=[fail_resp, ok_resp],
        ):
            result = make_executor().execute([
                make_delta("SPY", 5),
                make_delta("QQQ", 3),
            ])
        assert result.error_message is not None
        assert "SPY" in result.error_message

    def test_failed_order_has_success_false_and_no_order_id(self):
        fail_resp = mock_error_response(422)

        with patch("app.order_executor.requests.post", return_value=fail_resp):
            result = make_executor().execute([make_delta("SPY", 5)])

        failed_order = result.orders[0]
        assert failed_order.success is False
        assert failed_order.alpaca_order_id is None
        assert failed_order.error is not None

# All orders fail -> status == "failed"
class TestAllFailureStatus:
    def test_all_orders_fail_returns_failed_status(self):
        fail_resp = mock_error_response(500)
        with patch(
            "app.order_executor.requests.post",
            side_effect=[fail_resp, fail_resp],
        ):
            result = make_executor().execute([
                make_delta("SPY", 2),
                make_delta("QQQ", -1),
            ])
        assert result.status == "failed"

    def test_all_orders_fail_has_error_message(self):
        fail_resp = mock_error_response(500)
        with patch(
            "app.order_executor.requests.post",
            return_value=fail_resp,
        ):
            result = make_executor().execute([make_delta("SPY", 1)])
        assert result.error_message is not None

# Network errors (Timeout, ConnectionError)
class TestNetworkErrors:
    def test_timeout_marks_order_as_failed(self):
        with patch(
            "app.order_executor.requests.post",
            side_effect=requests.exceptions.Timeout,
        ):
            result = make_executor().execute([make_delta("SPY", 1)])
        assert result.orders[0].success is False
        assert "timed out" in result.orders[0].error.lower()

    def test_connection_error_marks_order_as_failed(self):
        with patch(
            "app.order_executor.requests.post",
            side_effect=requests.exceptions.ConnectionError("DNS fail"),
        ):
            result = make_executor().execute([make_delta("SPY", 1)])
        assert result.orders[0].success is False
        assert result.orders[0].error is not None

    def test_timeout_on_one_order_does_not_stop_others(self):
        ok_resp = mock_alpaca_response("ok-after-timeout")
        with patch(
            "app.order_executor.requests.post",
            side_effect=[requests.exceptions.Timeout, ok_resp],
        ) as mock_post:
            result = make_executor().execute([
                make_delta("SPY", 1),
                make_delta("QQQ", 2),
            ])
            assert mock_post.call_count == 2
        assert result.status == "partial"

# HTTP error codes
class TestHttpErrorCodes:
    @pytest.mark.parametrize("status_code", [400, 403, 422, 500])
    def test_http_error_marks_order_as_failed(self, status_code):
        fail_resp = mock_error_response(status_code)
        with patch("app.order_executor.requests.post", return_value=fail_resp):
            result = make_executor().execute([make_delta("SPY", 1)])
        order = result.orders[0]
        assert order.success is False
        assert str(status_code) in order.error

# serialize_orders()
class TestSerializeOrders:
    def test_successful_order_serialized_correctly(self):
        order = OrderResult(
            symbol="SPY",
            side="buy",
            qty=5,
            alpaca_order_id="uuid-abc",
            success=True,
            error=None,
        )
        result = serialize_orders([order])
        assert len(result) == 1
        assert result[0] == {
            "symbol":          "SPY",
            "side":            "buy",
            "qty":             5,
            "alpaca_order_id": "uuid-abc",
            "success":         True,
            "error":           None,
        }

    def test_failed_order_serialized_with_error(self):
        order = OrderResult(
            symbol="QQQ",
            side="sell",
            qty=3,
            alpaca_order_id=None,
            success=False,
            error="HTTP 422 — insufficient buying power",
        )
        result = serialize_orders([order])
        assert result[0]["alpaca_order_id"] is None
        assert result[0]["success"] is False
        assert "422" in result[0]["error"]

    def test_empty_list_returns_empty_list(self):
        assert serialize_orders([]) == []

    def test_multiple_orders_preserved_in_order(self):
        orders = [
            OrderResult("AAA", "buy",  1, "id-1", True,  None),
            OrderResult("BBB", "sell", 2, None,   False, "err"),
        ]
        result = serialize_orders(orders)
        assert result[0]["symbol"] == "AAA"
        assert result[1]["symbol"] == "BBB"
