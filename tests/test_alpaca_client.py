"""
Unit tests for AlpacaClient.get_positions().

All HTTP calls are mocked — no real network connection needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
import requests
from app.alpaca_client import AlpacaClient, AlpacaError

# Fixtures
def make_client(mode: str = "paper") -> AlpacaClient:
    return AlpacaClient(api_key="test-key", api_secret="test-secret", mode=mode)

def mock_response(json_data: list | dict, status_code: int = 200) -> MagicMock:
    """
    Build a fake requests.Response.
    
    Args:
        json_data: The JSON data to return from the response
        status_code: The HTTP status code to return
        
    Returns:
        MagicMock: A mock requests.Response object
    """
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.text = str(json_data)
    resp.raise_for_status.return_value = None  # no action for 2xx
    return resp

# Constructor
class TestAlpacaClientInit:
    def test_paper_mode_accepted(self):
        client = make_client("paper")
        assert "paper-api.alpaca.markets" in client._base_url

    def test_live_mode_accepted(self):
        client = make_client("live")
        assert client._base_url == "https://api.alpaca.markets"

    def test_invalid_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="ALPACA_MODE"):
            AlpacaClient("k", "s", "sandbox")

# Happy path
class TestGetPositionsHappyPath:
    def test_returns_dict_of_symbol_to_float(self):
        resp = mock_response([
            {"symbol": "SPY", "qty": "10.5"},
            {"symbol": "AAPL", "qty": "3"},
        ])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions()
        assert result == {"SPY": 10.5, "AAPL": 3.0}

    def test_qty_string_is_cast_to_float(self):
        resp = mock_response([{"symbol": "GLD", "qty": "7"}])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions()
        assert isinstance(result["GLD"], float)

    def test_empty_portfolio_returns_empty_dict_without_targets(self):
        resp = mock_response([])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions()
        assert result == {}

    def test_target_symbols_not_held_filled_with_zero(self):
        resp = mock_response([{"symbol": "SPY", "qty": "10"}])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions(
                target_symbols={"SPY", "QQQ", "GLD"}
            )
        assert result["SPY"] == 10.0
        assert result["QQQ"] == 0.0
        assert result["GLD"] == 0.0

    def test_empty_portfolio_all_targets_return_zero(self):
        resp = mock_response([])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions(target_symbols={"SPY", "QQQ"})
        assert result == {"SPY": 0.0, "QQQ": 0.0}

    def test_held_symbols_outside_targets_are_included(self):
        """Positions Alpaca reports are always included, even if not in targets."""
        resp = mock_response([
            {"symbol": "SPY", "qty": "5"},
            {"symbol": "TSLA", "qty": "2"},  # not in target_symbols
        ])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            result = make_client().get_positions(target_symbols={"SPY"})
        assert "TSLA" in result
        assert result["TSLA"] == 2.0

# Correct URL for mode
class TestEndpointUrl:
    def _get_called_url(self, mock_get):
        return mock_get.call_args[0][0]

    def test_paper_mode_calls_paper_endpoint(self):
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_get.return_value = mock_response([])
            make_client("paper").get_positions()
            assert "paper-api.alpaca.markets" in self._get_called_url(mock_get)

    def test_live_mode_calls_live_endpoint(self):
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_get.return_value = mock_response([])
            make_client("live").get_positions()
            url = self._get_called_url(mock_get)
            assert "api.alpaca.markets" in url
            assert "paper" not in url

    def test_positions_path_is_v2_positions(self):
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_get.return_value = mock_response([])
            make_client().get_positions()
            assert "/v2/positions" in self._get_called_url(mock_get)

# Error handling → AlpacaError
class TestAlpacaErrors:
    def test_timeout_raises_alpaca_error(self):
        with patch("app.alpaca_client.requests.get",
                   side_effect=requests.exceptions.Timeout):
            with pytest.raises(AlpacaError, match="timed out"):
                make_client().get_positions()

    def test_connection_error_raises_alpaca_error(self):
        with patch("app.alpaca_client.requests.get",
                   side_effect=requests.exceptions.ConnectionError("DNS failure")):
            with pytest.raises(AlpacaError, match="Network error"):
                make_client().get_positions()

    def test_401_raises_alpaca_error_with_status_code(self):
        resp = mock_response([], status_code=401)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
        with patch("app.alpaca_client.requests.get", return_value=resp):
            with pytest.raises(AlpacaError) as exc_info:
                make_client().get_positions()
        assert exc_info.value.status_code == 401
        assert "401" in str(exc_info.value)

    def test_403_raises_alpaca_error_with_status_code(self):
        resp = mock_response([], status_code=403)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
        with patch("app.alpaca_client.requests.get", return_value=resp):
            with pytest.raises(AlpacaError) as exc_info:
                make_client().get_positions()
        assert exc_info.value.status_code == 403

    def test_500_raises_alpaca_error(self):
        resp = mock_response([], status_code=500)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
        with patch("app.alpaca_client.requests.get", return_value=resp):
            with pytest.raises(AlpacaError) as exc_info:
                make_client().get_positions()
        assert exc_info.value.status_code == 500

    def test_alpaca_error_is_subclass_of_exception(self):
        """
        AlpacaError must be catchable as a generic Exception.
        """
        err = AlpacaError("test", status_code=401)
        assert isinstance(err, Exception)
        assert err.status_code == 401


class TestListPositionsFull:
    def test_returns_list_of_position_dicts(self):
        resp = mock_response([
            {"symbol": "QQQ", "qty": "10.0", "market_value": "7175.40",
             "avg_entry_price": "700.75"},
            {"symbol": "BIL", "qty": "16.0", "market_value": "1465.44",
             "avg_entry_price": "91.54"},
        ])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            client = AlpacaClient("key", "secret", "paper")
            result = client.list_positions_full()
        assert result == [
            {"symbol": "QQQ", "qty": 10.0, "market_value": 7175.40, "avg_entry_price": 700.75},
            {"symbol": "BIL", "qty": 16.0, "market_value": 1465.44, "avg_entry_price": 91.54},
        ]

    def test_returns_empty_list_when_no_positions(self):
        resp = mock_response([])
        with patch("app.alpaca_client.requests.get", return_value=resp):
            client = AlpacaClient("key", "secret", "paper")
            assert client.list_positions_full() == []


class TestGetAccount:
    def test_returns_equity_and_cash(self):
        resp = mock_response({"equity": "10067.79", "cash": "0.00", "buying_power": "20135.58"})
        with patch("app.alpaca_client.requests.get", return_value=resp):
            client = AlpacaClient("key", "secret", "paper")
            result = client.get_account()
        assert result == {"equity": 10067.79, "cash": 0.0}
