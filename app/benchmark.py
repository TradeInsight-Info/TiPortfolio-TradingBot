"""
GET /benchmark - equity curve API.

Returns two normalised time series indexed from the first rebalance date:
  1. bot       - portfolio equity curve reconstructed from DB rebalance records
  2. benchmark - cumulative return of the requested market index

Supported tickers:
  SPY          - S&P 500 ETF
  QQQ          - Nasdaq-100 ETF
  QQQ+GLD+BIL  - Equal-weight composite of three ETFs (1/3 each)

Caching:
  yfinance price data is stored in a module-level dict keyed by sorted symbol
  list + fetch date. The cache is invalidated at midnight so prices are never
  more than one calendar day stale.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from flask import Blueprint, current_app, jsonify, request

from app.rebalance import RebalanceRepository

logger = logging.getLogger(__name__)
bp = Blueprint("benchmark", __name__)

# Supported tickers
SUPPORTED_TICKERS = {"SPY", "QQQ", "QQQ+GLD+BIL"}

# Equal-weight 1/3 each for the composite benchmark
COMPOSITE_COMPONENTS: dict[str, float] = {
    "QQQ": 1 / 3,
    "GLD": 1 / 3,
    "BIL": 1 / 3,
}

# In-memory price cache
# Keyed by sorted-symbol string; value is (fetch_date, full DataFrame).
_price_cache: dict[str, tuple[date, pd.DataFrame]] = {}

def _download_prices(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """
    Download adjusted closing prices from yfinance.

    Args:
        symbols: Ticker symbols, e.g. ["SPY"] or ["QQQ", "GLD", "BIL"].
        start:   First date (inclusive).
        end:     Last date (inclusive).

    Returns:
        DataFrame indexed by date with one column per symbol (closing prices).
        Returns an empty DataFrame when yfinance returns nothing.
    """
    tickers_str = " ".join(symbols)
    raw = yf.download(
        tickers_str,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
    )

    if raw.empty:
        return pd.DataFrame()

    # Extract closing prices regardless of yfinance column format.
    # Newer yfinance versions return MultiIndex columns even for a single ticker,
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
        # Single ticker case: Close is a Series, convert to DataFrame
        if isinstance(close, pd.Series):
            close = close.to_frame(name=symbols[0])
    else:
        # Older yfinance: single ticker returns flat column named "Close"
        close = raw[["Close"]].rename(columns={"Close": symbols[0]})

    close.index = pd.to_datetime(close.index).normalize()
    return close.sort_index()

def _get_prices(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """
    Return closing prices, fetching from yfinance only when the cache is stale.

    Cache key = sorted symbol list joined by commas.
    Cache is invalidated when the calendar date changes.
    """
    # end must be at least one day after start
    if end <= start:
        end = start + timedelta(days=1)

    today = date.today()
    cache_key = ",".join(sorted(symbols))

    if cache_key in _price_cache:
        cached_date, cached_df = _price_cache[cache_key]
        if cached_date == today and not cached_df.empty:
            return cached_df.loc[
                (cached_df.index >= pd.Timestamp(start))
                & (cached_df.index <= pd.Timestamp(end))
            ]

    df = _download_prices(symbols, start, end)
    _price_cache[cache_key] = (today, df)
    return df

def _nearest_trading_day(d: date) -> date:
    """
    Roll back a date to the most recent weekday (Mon-Fri).
    Saturday -> Friday, Sunday -> Friday, weekday -> unchanged.
    """
    # weekday(): Mon=0 ... Fri=4, Sat=5, Sun=6
    if d.weekday() == 5:   # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:   # Sunday
        return d - timedelta(days=2)
    return d

def _benchmark_curve(ticker: str, prices: pd.DataFrame, first_date: date) -> pd.Series:
    """
    Build the benchmark cumulative-return series, normalised to 1.0 at the start.

    For the composite ticke, an equal-weight daily return is computed from
    all three components before cumulating.
    """
    if ticker in ("SPY", "QQQ"):
        if ticker not in prices.columns:
            return pd.Series(dtype=float)
        series = prices[ticker].dropna()
        # Only use data from first rebalance date onwards
        series = series.loc[series.index >= pd.Timestamp(first_date)]
        if series.empty or series.iloc[0] == 0:
            return pd.Series(dtype=float)
        return series / series.iloc[0]

    # Composite: equal-weight daily returns, re-normalised if a component is missing
    available = [s for s in COMPOSITE_COMPONENTS if s in prices.columns]
    if not available:
        return pd.Series(dtype=float)

    total_weight = sum(COMPOSITE_COMPONENTS[s] for s in available)
    daily_returns = prices[available].pct_change()
    composite_daily = sum(
        daily_returns[s] * (COMPOSITE_COMPONENTS[s] / total_weight)
        for s in available
    )
    cum_returns = (1 + composite_daily.fillna(0)).cumprod()
    if cum_returns.empty or cum_returns.iloc[0] == 0:
        return pd.Series(dtype=float)
    return cum_returns / cum_returns.iloc[0]

def _bot_equity_curve(events: list, prices: pd.DataFrame) -> pd.Series:
    """
    Reconstruct the bot's normalised equity curve from rebalance events.

    Algorithm:
      For every trading day in `prices` on or after the first rebalance,
      look up the most-recent rebalance event and weight the symbols'
      daily returns by that event's target_weights.
      Cumulatively product the resulting daily portfolio returns to produce
      a curve that starts at 1.0 on the first rebalance date.
    """
    if not events or prices.empty:
        return pd.Series(dtype=float)

    events_asc = sorted(events, key=lambda e: e.timestamp)
    first_ts = pd.Timestamp(events_asc[0].timestamp.date())

    # To prevent cached data or yfinance from returning data beyond the expected range.
    prices_from_start = prices.loc[prices.index >= first_ts]
    if prices_from_start.empty:
        return pd.Series(dtype=float)

    daily_returns = prices_from_start.pct_change().fillna(0)

    portfolio_daily: list[float] = []

    for row_date in daily_returns.index:
        # Find the most-recent rebalance event on or before this trading day
        active_event = None
        for ev in reversed(events_asc):
            if pd.Timestamp(ev.timestamp.date()) <= row_date:
                active_event = ev
                break

        if active_event is None or not active_event.target_weights:
            portfolio_daily.append(0.0)
            continue

        weights: dict[str, float] = active_event.target_weights
        portfolio_returns = 0.0
        for sym, w in weights.items():
            if sym in daily_returns.columns:
                portfolio_returns += w * float(daily_returns.loc[row_date, sym])
        portfolio_daily.append(portfolio_returns)

    returns_series = pd.Series(portfolio_daily, index=daily_returns.index)
    cumulative = (1 + returns_series).cumprod()

    # Normalise so the curve starts at exactly 1.0
    if not cumulative.empty and cumulative.iloc[0] != 0:
        cumulative = cumulative / cumulative.iloc[0]

    return cumulative


@bp.route("/benchmark", methods=["GET"])
def get_benchmark():
    """
    Return bot equity curve and benchmark cumulative return.

    Query params:
        ticker (required): SPY | QQQ | QQQ+GLD+BIL

    Responses:
        200 { no_data: true }
        200 { no_data: false, ticker, first_rebalance_date, bot: [...], benchmark: [...] }
        400 { error: "..." }   unsupported ticker
        502 { error: "..." }   yfinance fetch failed
    """
    # URL query strings encode '+' as space (application/x-www-form-urlencoded)
    # or '%2B'. Normalise both to '+'.
    raw_ticker = request.args.get("ticker", "").upper().replace(" ", "+")

    if raw_ticker not in SUPPORTED_TICKERS:
        return jsonify({
            "error": (
                f"Unsupported ticker {raw_ticker!r}. "
                "Supported values: SPY, QQQ, QQQ+GLD+BIL."
            )
        }), 400

    repo = RebalanceRepository(current_app.config["DB_SESSION"])
    events = repo.get_all()  # newest-first

    if not events:
        return jsonify({"no_data": True}), 200

    events_asc = sorted(events, key=lambda e: e.timestamp)
    first_date = _nearest_trading_day(events_asc[0].timestamp.date())
    today      = _nearest_trading_day(date.today())
    # end must be at least one day after start so yfinance has a valid range
    end_date   = today + timedelta(days=1)

    # Collect every symbol the bot has ever traded
    bot_symbols: set[str] = set()
    for ev in events_asc:
        if ev.target_weights:
            bot_symbols.update(ev.target_weights.keys())

    bench_symbols = (
        list(COMPOSITE_COMPONENTS.keys())
        if raw_ticker == "QQQ+GLD+BIL"
        else [raw_ticker]
    )

    # Fetch all symbols together in one yfinance call (cached)
    all_symbols = sorted(bot_symbols | set(bench_symbols))
    try:
        prices = _get_prices(all_symbols, first_date, end_date)
    except Exception as exc:
        logger.error("yfinance price fetch failed: %s", exc)
        return jsonify({"error": f"Failed to fetch price data: {exc}"}), 502

    if prices.empty:
        return jsonify({"no_data": True}), 200

    bench = _benchmark_curve(raw_ticker, prices, first_date)
    bot   = _bot_equity_curve(events_asc, prices)

    def _to_list(series: pd.Series) -> list[dict]:
        return [
            {"date": idx.strftime("%Y-%m-%d"), "value": round(float(val), 6)}
            for idx, val in series.items()
            if pd.notna(val)
        ]

    return jsonify({
        "no_data":              False,
        "ticker":               raw_ticker,
        "first_rebalance_date": first_date.isoformat(),
        "bot":                  _to_list(bot),
        "benchmark":            _to_list(bench),
    }), 200