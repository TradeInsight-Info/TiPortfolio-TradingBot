"""
Thin wrapper around the Alpaca REST API.

Responsibilities:
- Pick the correct base URL from ALPACA_MODE (paper / live)
- Fetch /v2/positions and return {symbol: float(qty)}
- Fetch /v2/stocks/trades/latest and return {symbol: float(price)}
- Fetch /v2/account and return float(equity)
- Fill 0.0 for any target symbol not currently held
- Wrap every network/HTTP failure into AlpacaError so callers
  only need to catch one exception type
"""

from __future__ import annotations

import logging
import requests
from typing import Set

logger = logging.getLogger(__name__)

# Trading API base URLs - selected at runtime by ALPACA_MODE
_BASE_URLS: dict[str, str] = {
    "paper": "https://paper-api.alpaca.markets",
    "live":  "https://api.alpaca.markets",
}

# Market data API uses a single URL for both paper and live accounts
_DATA_BASE_URL = "https://data.alpaca.markets"
_REQUEST_TIMEOUT_SECONDS = 10

# Structured exception
class AlpacaError(Exception):
    """
    Raised whenever the Alpaca API is unreachable or returns an error.

    Attributes:
        status_code: HTTP status code returned by Alpaca (None for network errors).
    """
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

# Client
class AlpacaClient:
    """
    Minimal Alpaca API client.

    Args:
        api_key:    ALPACA_API_KEY from environment / Flask config.
        api_secret: ALPACA_API_SECRET from environment / Flask config.
        mode:       "paper" or "live" - controls which base URL is used.
    """
    def __init__(self, api_key: str, api_secret: str, mode: str) -> None:
        if mode not in _BASE_URLS:
            raise ValueError(
                f"ALPACA_MODE must be 'paper' or 'live', got {mode!r}."
            )
        self._base_url = _BASE_URLS[mode]
        self._mode = mode
        # Alpaca uses these two custom headers for authentication (not Bearer tokens)
        self._headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }

    # Public API
    def get_positions(
        self,
        target_symbols: Set[str] | None = None,
    ) -> dict[str, float]:
        """
        Fetch current portfolio positions from Alpaca.

        Args:
            target_symbols: Optional set of ticker symbols the algorithm
                            is targeting. Any symbol in this set that is
                            not currently held will appear in the result
                            with a value of 0.0.

        Returns:
            dict mapping symbol -> current share quantity (float).
            Example: {"SPY": 10.5, "QQQ": 0.0, "GLD": 3.0}

        Raises:
            AlpacaError: on authentication failure, network timeout, or
                         any other Alpaca API error. The rebalance pipeline
                         should treat this as fatal and abort.
        """
        url = f"{self._base_url}/v2/positions"
        logger.info("Fetching positions from Alpaca (%s) -> %s", self._mode, url)

        raw_positions = self._get(url)

        # Alpaca returns qty as a string, cast string to float
        positions: dict[str, float] = {
            p["symbol"]: float(p["qty"]) for p in raw_positions
        }

        # Ensure every target symbol is present, even if not currently held
        if target_symbols:
            for symbol in target_symbols:
                positions.setdefault(symbol, 0.0)

        logger.info("Positions resolved: %s", positions)
        return positions

    def get_latest_prices(self, symbols: Set[str]) -> dict[str, float]:
        """
        Fetch the most recent trade price for each requested symbol.

        Uses Alpaca's market-data endpoint:
            GET /v2/stocks/trades/latest?symbols=SPY,QQQ,...

        The data API base URL (data.alpaca.markets) is the same for both
        paper and live accounts - only the trading API differs.

        Args:
            symbols: Set of ticker symbols to price, e.g. {"SPY", "QQQ"}.

        Returns
            dict mapping symbol -> latest trade price (float).

        Raises:
            AlpacaError: if the request fails or if any requested symbol has
                         no trade data in the response (stale / halted ticker).
        """
        # Sort for a deterministic, reproducible query string
        symbols_param = ",".join(sorted(symbols))
        url = f"{_DATA_BASE_URL}/v2/stocks/trades/latest?symbols={symbols_param}"
        logger.info("Fetching latest prices for symbols: %s", symbols_param)

        body = self._get(url)
        # Response shape: {"trades": {"SPY": {"p": 510.23, "t": "2026-04-25T...", ...}, {"QQQ": ...}}}
        trades: dict = body.get("trades", {})

        prices: dict[str, float] = {}
        for symbol in symbols:
            trade = trades.get(symbol)
            if trade is None:
                # Symbol returned no data - treat as fatal so the rebalance
                # doesn't proceed with a missing price
                raise AlpacaError(
                    f"No latest trade data returned for symbol {symbol!r}. "
                    "The ticker may be halted or delisted."
                )
            prices[symbol] = float(trade["p"])  # "p" is the trade price field

        logger.info("Latest prices resolved: %s", prices)
        return prices

    def get_account_equity(self) -> float:
        """
        Fetch total account equity from Alpaca.

        Uses the trading API endpoint:
            GET /v2/account

        Equity is defined by Alpaca as cash + market value of all positions.
        This is the portfolio value used by the delta calculator.

        Returns:
            Account equity in USD as a float.

        Raises:
            AlpacaError: on authentication failure, network timeout, or any
                         other Alpaca API error. The rebalance pipeline should
                         treat this as fatal and abort.
        """
        url = f"{self._base_url}/v2/account"
        logger.info("Fetching account equity from Alpaca (%s)", self._mode)

        body = self._get(url)
        # Alpaca returns "equity" as a numeric string, e.g. "10432.75"
        equity = float(body["equity"])
        logger.info("Account equity: %.2f", equity)
        return equity

    # Internal helpers
    def _get(self, url: str) -> dict | list:
        """
        Perform a GET request and return the parsed JSON body.
        All network and HTTP errors are converted to AlpacaError.
        """
        try:
            response = requests.get(
                url,
                headers=self._headers,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            msg = f"Request to Alpaca timed out after {_REQUEST_TIMEOUT_SECONDS}s: {url}"
            logger.error(msg)
            raise AlpacaError(msg) from exc
        except requests.exceptions.ConnectionError as exc:
            msg = f"Network error connecting to Alpaca: {exc}"
            logger.error(msg)
            raise AlpacaError(msg) from exc
        except requests.exceptions.HTTPError as exc:
            # response is still available here - extract status code
            status = response.status_code
            msg = f"Alpaca API returned HTTP {status}: {response.text}"
            logger.error(msg)
            raise AlpacaError(msg, status_code=status) from exc

        return response.json()
