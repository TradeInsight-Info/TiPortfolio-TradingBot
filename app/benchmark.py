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

from app.alpaca_client import AlpacaClient, AlpacaError
from app.portfolio_config import PortfolioConfigRepository
from app.rebalance import RebalanceRepository

logger = logging.getLogger(__name__)
bp = Blueprint("benchmark", __name__)

# Cache Alpaca portfolio history per (fetch_date, start_date) to avoid
# hitting the Alpaca API on every chart load.
_portfolio_hist_cache: dict[tuple, list] = {}

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

def _portfolio_value_curve(events: list, prices: pd.DataFrame) -> pd.Series:
    """
    Compute daily portfolio value in USD as sum(held_qty * close_price).

    Walks rebalance events chronologically to build a running position for
    each symbol. For each trading day the most-recent snapshot is applied.

    filled_qty is used when available; falls back to abs(delta_shares) for
    older records that pre-date fill tracking.
    """
    if not events or prices.empty:
        return pd.Series(dtype=float)

    events_asc = sorted(events, key=lambda e: e.timestamp)
    first_ts = pd.Timestamp(events_asc[0].timestamp.date())
    prices_from_start = prices.loc[prices.index >= first_ts]
    if prices_from_start.empty:
        return pd.Series(dtype=float)

    # Build a list of (event_date, cumulative_positions) snapshots
    positions: dict[str, float] = {}
    snapshots: list[tuple[pd.Timestamp, dict[str, float]]] = []

    for ev in events_asc:
        for order in (ev.orders or []):
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
        snapshots.append((pd.Timestamp(ev.timestamp.date()), dict(positions)))

    if not snapshots:
        return pd.Series(dtype=float)

    values: list[float] = []
    for row_date in prices_from_start.index:
        # Most-recent snapshot on or before this date
        current_pos: dict[str, float] = {}
        for ts, pos in snapshots:
            if ts <= row_date:
                current_pos = pos
            else:
                break

        day_value = sum(
            qty * float(prices_from_start.loc[row_date, sym])
            for sym, qty in current_pos.items()
            if qty > 0 and sym in prices_from_start.columns
            and pd.notna(prices_from_start.loc[row_date, sym])
        )
        values.append(day_value if day_value > 0 else float("nan"))

    return pd.Series(values, index=prices_from_start.index).dropna()


def _alpaca_equity_curve(first_date: date) -> pd.Series:
    """
    Fetch Alpaca portfolio history and return a Series normalised to 1.0
    at the first data point. Used when no rebalance events exist.
    Returns an empty Series if the fetch fails or returns no data.
    """
    cache_key = (date.today(), first_date)
    if cache_key not in _portfolio_hist_cache:
        try:
            client = AlpacaClient(
                api_key=current_app.config["ALPACA_API_KEY"],
                api_secret=current_app.config["ALPACA_API_SECRET"],
                mode=current_app.config["ALPACA_MODE"],
            )
            _portfolio_hist_cache[cache_key] = client.get_portfolio_history(first_date)
        except AlpacaError as exc:
            logger.warning("Alpaca portfolio history unavailable: %s", exc)
            return pd.Series(dtype=float)

    history = _portfolio_hist_cache[cache_key]
    if not history or history[0]["equity"] == 0:
        return pd.Series(dtype=float)

    return pd.Series(
        [h["equity"] for h in history],
        index=pd.to_datetime([h["date"] for h in history]),
    )


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
    events_asc = sorted(events, key=lambda e: e.timestamp)

    if events_asc:
        first_date = _nearest_trading_day(events_asc[0].timestamp.date())
    else:
        config_repo = PortfolioConfigRepository(current_app.config["DB_SESSION"])
        config_row = config_repo.get()
        if config_row is None:
            return jsonify({"no_data": True}), 200
        first_date = _nearest_trading_day(config_row.recorded_at.date())
    today      = _nearest_trading_day(date.today())
    # end must be at least one day after start so yfinance has a valid range
    end_date   = today + timedelta(days=2)

    bench_symbols = (
        list(COMPOSITE_COMPONENTS.keys())
        if raw_ticker == "QQQ+GLD+BIL"
        else [raw_ticker]
    )

    try:
        prices = _get_prices(bench_symbols, first_date, end_date)
    except Exception as exc:
        logger.error("yfinance price fetch failed: %s", exc)
        return jsonify({"error": f"Failed to fetch price data: {exc}"}), 502

    if prices.empty:
        return jsonify({"no_data": True}), 200

    bot   = _alpaca_equity_curve(first_date)

    # Align benchmark normalisation to bot's first actual data date so all
    # series start from the same point on the chart.
    if not bot.empty:
        bench = _benchmark_curve(raw_ticker, prices, bot.index[0].date())
    else:
        bench = _benchmark_curve(raw_ticker, prices, first_date)

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