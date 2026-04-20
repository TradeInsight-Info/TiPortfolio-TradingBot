"""
Thin wrapper around the Alpaca REST API.

Responsibilities:
  - Pick the correct base URL from ALPACA_MODE (paper / live)
  - Fetch /v2/positions and return {symbol: float(qty)}
  - Fill 0.0 for any target symbol not currently held
  - Wrap every network/HTTP failure into AlpacaError so callers
    only need to catch one exception type
"""

from __future__ import annotations

import logging
import requests
from typing import Set

logger = logging.getLogger(__name__)

# Alpaca base URLs — selected at runtime by ALPACA_MODE
_BASE_URLS: dict[str, str] = {
    "paper": "https://paper-api.alpaca.markets",
    "live":  "https://api.alpaca.markets",
}

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
        mode:       "paper" or "live" — controls which base URL is used.
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
            "APCA-API-KEY-SECRET": api_secret,
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
            dict mapping symbol → current share quantity (float).
            Example: {"SPY": 10.5, "QQQ": 0.0, "GLD": 3.0}

        Raises:
            AlpacaError: on authentication failure, network timeout, or
                         any other Alpaca API error. The rebalance pipeline
                         should treat this as fatal and abort.
        """
        url = f"{self._base_url}/v2/positions"
        logger.info("Fetching positions from Alpaca (%s) → %s", self._mode, url)

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

    # Internal helpers
    def _get(self, url: str) -> list:
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
            # response is still available here — extract status code
            status = response.status_code
            msg = f"Alpaca API returned HTTP {status}: {response.text}"
            logger.error(msg)
            raise AlpacaError(msg, status_code=status) from exc

        return response.json()
