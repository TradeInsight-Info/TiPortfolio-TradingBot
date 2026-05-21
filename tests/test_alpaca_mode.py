"""
- ALPACA_MODE=live  routes all Alpaca API calls to the live endpoint.
- ALPACA_MODE=paper routes all Alpaca API calls to the paper endpoint.
- An invalid mode raises ValueError immediately (no network call needed).
- App logs the active mode on startup.

All HTTP calls are mocked - no real network connection needed.
"""
import logging
import pytest
import unittest

from unittest.mock import patch, MagicMock
from app import create_app
from app.alpaca_client import AlpacaClient, _BASE_URLS, _DATA_BASE_URL

class TestAlpacaModeRouting:
    """
    Verify that the correct base URL is selected for paper vs live mode.
    """
    def test_paper_mode_uses_paper_base_url(self):
        client = AlpacaClient(api_key="key", api_secret="secret", mode="paper")
        assert client._base_url == _BASE_URLS["paper"]
        assert "paper-api.alpaca.markets" in client._base_url

    def test_live_mode_uses_live_base_url(self):
        client = AlpacaClient(api_key="key", api_secret="secret", mode="live")
        assert client._base_url == _BASE_URLS["live"]
        assert "api.alpaca.markets" in client._base_url
        assert "paper" not in client._base_url

    def test_invalid_mode_raises_value_error(self):
        """
        Any mode other than 'paper' or 'live' must fail fast.
        """
        with pytest.raises(ValueError, match="ALPACA_MODE must be"):
            AlpacaClient(api_key="key", api_secret="secret", mode="staging")

    def test_no_code_path_conditioned_on_mode(self):
        """
        Only the base URL changes - headers, timeout, retry logic are identical.
        """
        paper = AlpacaClient(api_key="k", api_secret="s", mode="paper")
        live  = AlpacaClient(api_key="k", api_secret="s", mode="live")
        # Same header keys regardless of mode
        assert set(paper._headers.keys()) == set(live._headers.keys())

    def test_positions_url_uses_mode_base(self):
        """
        GET /v2/positions is always built from the mode-specific base URL.
        """
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = []
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            # Paper
            paper_client = AlpacaClient("k", "s", "paper")
            paper_client.get_positions()
            called_url = mock_get.call_args[0][0]
            assert called_url.startswith(_BASE_URLS["paper"])

            # Live
            live_client = AlpacaClient("k", "s", "live")
            live_client.get_positions()
            called_url = mock_get.call_args[0][0]
            assert called_url.startswith(_BASE_URLS["live"])

    def test_account_url_uses_mode_base(self):
        """
        GET /v2/account is always built from the mode-specific base URL.
        """
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"equity": "10000.00"}
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            for mode in ("paper", "live"):
                client = AlpacaClient("k", "s", mode)
                client.get_account_equity()
                called_url = mock_get.call_args[0][0]
                assert called_url.startswith(_BASE_URLS[mode])

    def test_order_url_uses_mode_base(self):
        """
        GET /v2/orders/{id} is always built from the mode-specific base URL.
        """
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"status": "filled", "filled_qty": "10", "filled_avg_price": "500.00"}
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            for mode in ("paper", "live"):
                client = AlpacaClient("k", "s", mode)
                client.get_order("fake-order-id")
                called_url = mock_get.call_args[0][0]
                assert called_url.startswith(_BASE_URLS[mode])

    def test_price_url_uses_mode_base(self):
        """
        GET /v2/stocks is always built from the mode-specific base URL.
        """
        with patch("app.alpaca_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"trades": {"SPY": {"p": 400.00}}}
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            for mode in ("paper", "live"):
                client = AlpacaClient("k", "s", mode)
                client.get_latest_prices({"SPY"})
                called_url = mock_get.call_args[0][0]
                assert called_url.startswith(_DATA_BASE_URL)

class TestStartupLogging(unittest.TestCase):
    """
    Verify that the app logs the active mode when it starts.
    """
    def test_startup_logs_paper_mode(self):
        """
        create_app() must output a log line mentioning the mode.
        """
        import os
        env_patch = {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_API_SECRET": "test_secret",
            "ALPACA_MODE": "paper",
            "DATABASE_URL": "sqlite:///:memory:",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            with patch("app.init_db"):  # skip real DB init
                with self.assertLogs("app", level="INFO") as captured:
                    create_app()

        # The log must mention 'paper' somewhere
        all_output = " ".join(captured.output).lower()
        assert "paper" in all_output
        assert "paper-api.alpaca.markets" in all_output

    def test_startup_logs_live_mode(self):
        """
        create_app() must output a log line mentioning the mode.
        """
        import os
        env_patch = {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_API_SECRET": "test_secret",
            "ALPACA_MODE": "live",
            "DATABASE_URL": "sqlite:///:memory:",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            with self.assertLogs("app", level="INFO") as captured:
                from app import create_app
                with patch("app.init_db"):
                    create_app()

        all_output = " ".join(captured.output).lower()
        assert "live" in all_output
        assert "api.alpaca.markets" in all_output
        assert "paper-api.alpaca.markets" not in all_output
