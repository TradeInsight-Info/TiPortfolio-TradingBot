"""
Local-only substitute for AlpacaClient used when TIPORTFOLIO_MODE=simulated.

Derives positions and equity from prior simulated rebalance records in the DB
and fetches historical closing prices from yfinance.  No Alpaca credentials
are needed.

Selected in webhook.py when:
  - TIPORTFOLIO_MODE=simulated (env var)
  - webhook payload includes a "date" field (YYYY-MM-DD)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Generator, Set

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session, sessionmaker

from app.models import RebalanceEvent

logger = logging.getLogger(__name__)


class SimulatedDataError(Exception):
    """Raised when yfinance has no data for the requested date/symbol."""


class SimulatedAlpacaClient:
    """
    Drop-in substitute for AlpacaClient sourcing data from yfinance + local DB.

    Call order expected by webhook.py:
        1. get_positions()      — reads DB
        2. get_latest_prices()  — fetches yfinance, caches on instance
        3. get_account_equity() — cash + market_value using cached prices
    """

    def __init__(
        self,
        session_factory: sessionmaker,
        simulation_date: date,
        initial_amount: float,
    ) -> None:
        self._session_factory = session_factory
        self._simulation_date = simulation_date
        self._initial_amount = initial_amount
        self._cached_prices: dict[str, float] = {}

    @contextmanager
    def _tx(self) -> Generator[Session, None, None]:
        session: Session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def get_positions(self, target_symbols: Set[str] | None = None) -> dict[str, float]:
        """
        Build current positions by summing fills from all prior simulated events
        on or before simulation_date.
        """
        with self._tx() as session:
            events = (
                session.query(RebalanceEvent)
                .filter(
                    RebalanceEvent.source == "simulated",
                    RebalanceEvent.simulation_date <= self._simulation_date,
                )
                .order_by(RebalanceEvent.simulation_date)
                .all()
            )

        positions: dict[str, float] = {}
        for event in events:
            for order in (event.orders or []):
                symbol = order.get("symbol")
                if not symbol:
                    continue
                qty = order.get("filled_qty")
                if qty is None:
                    qty = abs(order.get("delta_shares") or 0)
                qty = float(qty)
                if order.get("direction") == "sell":
                    qty = -qty
                positions[symbol] = positions.get(symbol, 0.0) + qty

        # Clamp to non-negative (sells can't exceed holdings)
        positions = {k: max(0.0, v) for k, v in positions.items() if v > 0.0}

        if target_symbols:
            for sym in target_symbols:
                positions.setdefault(sym, 0.0)

        logger.info("Simulated positions on %s: %s", self._simulation_date, positions)
        return positions

    def get_latest_prices(self, symbols: Set[str]) -> dict[str, float]:
        """
        Fetch closing prices from yfinance for simulation_date.
        Cached on the instance so get_account_equity() can reuse them.
        """
        prices = _fetch_yf_close(symbols, self._simulation_date)
        self._cached_prices.update(prices)
        return prices

    def get_account_equity(self) -> float:
        """
        Compute equity as cash + market value of current positions.

        cash         = initial_amount - net spend from all prior simulated trades
        market_value = sum(qty * close_price[simulation_date])

        Requires get_latest_prices() to have been called first.
        """
        positions = self.get_positions()

        with self._tx() as session:
            prior_events = (
                session.query(RebalanceEvent)
                .filter(
                    RebalanceEvent.source == "simulated",
                    RebalanceEvent.simulation_date <= self._simulation_date,
                )
                .all()
            )

        net_cash_spent: float = 0.0
        for event in prior_events:
            for order in (event.orders or []):
                qty = float(order.get("filled_qty") or 0.0)
                price = float(order.get("filled_avg_price") or 0.0)
                if order.get("direction") == "buy":
                    net_cash_spent += qty * price
                else:
                    net_cash_spent -= qty * price

        cash = self._initial_amount - net_cash_spent
        market_value = sum(
            qty * self._cached_prices.get(sym, 0.0)
            for sym, qty in positions.items()
        )
        equity = max(cash + market_value, 0.0)
        logger.info(
            "Simulated equity on %s: cash=%.2f market_value=%.2f equity=%.2f",
            self._simulation_date, cash, market_value, equity,
        )
        return equity


def _fetch_yf_close(symbols: Set[str], trading_date: date) -> dict[str, float]:
    """
    Return closing prices for each symbol on trading_date.

    Rolls back up to 5 calendar days when the exact date has no data
    (weekend / holiday).  Raises SimulatedDataError if still empty.
    """
    end = trading_date + timedelta(days=1)  # yfinance end is exclusive
    tickers_str = " ".join(sorted(symbols))

    raw = pd.DataFrame()
    for days_back in range(6):
        start = trading_date - timedelta(days=days_back)
        raw = yf.download(tickers_str, start=start, end=end, progress=False, auto_adjust=True)
        if not raw.empty:
            break

    if raw.empty:
        raise SimulatedDataError(
            f"No price data found for {symbols} around {trading_date}."
        )

    # Normalise to a DataFrame with one column per symbol
    if isinstance(raw.columns, pd.MultiIndex):
        close_df = raw["Close"]
        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame(name=next(iter(symbols)))
    else:
        sym = next(iter(symbols))
        close_df = raw[["Close"]].rename(columns={"Close": sym})

    last_row = close_df.iloc[-1]
    prices: dict[str, float] = {}
    for sym in symbols:
        val = last_row.get(sym)
        if val is None or pd.isna(val):
            raise SimulatedDataError(f"No price for {sym} on {trading_date}.")
        prices[sym] = float(val)

    logger.info("yfinance prices on %s (actual): %s", trading_date, prices)
    return prices
