"""
Delta calculator for portfolio rebalancing.

Given the current Alpaca positions and a target weight signal, this module
computes the exact share delta (buy/sell quantity) for each symbol.

Formula:
    target_shares = round(portfolio_value * target_weight / current_price, 6)
    delta         = round(target_shares - current_shares, 6)

Rules:
  - Symbol in target but not held    -> positive delta (buy)
  - Symbol held but absent in target -> negative delta (full sell)
  - |delta| < MIN_TRADE_SHARES       -> excluded (noise suppression)
  - Delta == 0                       -> excluded from result
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_TRADE_SHARES = 0.001

@dataclass(frozen=True)
class OrderDelta:
    """
    Represents the share change required for one symbol.

    Attributes:
        symbol:        Stock symbol, e.g. "SPY"
        delta:         Signed fractional share change.
                       Positive -> buy, Negative -> sell.
        current_shares: Shares currently held.
        target_shares:  Fractional shares the portfolio should hold after rebalance.
    """
    symbol: str
    delta: float
    current_shares: float
    target_shares: float


def calculate_deltas(
    portfolio_value: float,
    target_weights: dict[str, float],
    current_positions: dict[str, float],
    current_prices: dict[str, float],
) -> list[OrderDelta]:
    """
    Calculate the share delta for every symbol that needs a trade.

    Args:
        portfolio_value:   Total account equity in dollars.
        target_weights:    Symbol -> weight from the algorithm signal.
                           e.g. {"SPY": 0.6, "GLD": 0.4}
        current_positions: Symbol -> shares currently held from Alpaca.
                           e.g. {"SPY": 10.0, "QQQ": 5.0}
        current_prices:    Symbol -> latest price per share in dollars.
                           Must contain an entry for every symbol that appears
                           in either target_weights or current_positions.

    Returns:
        List of OrderDelta objects where delta != 0.
        Symbols with a zero delta are excluded.

    Raises:
        ValueError: if portfolio_value <= 0, or if a required price is missing.
    """
    if portfolio_value <= 0:
        raise ValueError(
            f"portfolio_value must be positive, got {portfolio_value!r}."
        )

    # Collect every symbol that needs to be considered:
    #   - all symbols the algorithm wants  (target_weights)
    #   - all symbols currently held       (current_positions)
    all_symbols: set[str] = set(target_weights) | set(current_positions)

    deltas: list[OrderDelta] = []

    for symbol in sorted(all_symbols):           # sorted for deterministic output
        target_weight = target_weights.get(symbol, 0.0)
        current_shares = current_positions.get(symbol, 0.0)

        # Symbols absent from target_weights must be fully exited
        if target_weight == 0.0:
            target_shares = 0
        else:
            price = current_prices.get(symbol)
            if price is None:
                raise ValueError(
                    f"No price found for symbol {symbol!r}. "
                    "current_prices must contain every targeted symbol."
                )
            if price <= 0:
                raise ValueError(
                    f"Price for {symbol!r} must be positive, got {price!r}."
                )
            target_shares = round(portfolio_value * target_weight / price, 6)

        delta = round(target_shares - current_shares, 6)

        if abs(delta) < MIN_TRADE_SHARES:
            logger.debug("Skipping tiny delta for %s (delta=%g)", symbol, delta)
            continue

        logger.info(
            "Delta for %s: current=%g target=%g delta=%+g",
            symbol, current_shares, target_shares, delta,
        )
        
        deltas.append(
            OrderDelta(
                symbol=symbol,
                delta=delta,
                current_shares=current_shares,
                target_shares=target_shares,
            )
        )

    return deltas
