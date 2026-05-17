"""
Market VIX Rebalance — Run VIX#2 Ratio Strategy and POST Target Weights to TradingBot Webhook
==============================================================================================

Runs the *winner* from the VIX-regime parameter sweep (see Plans.md Archive)
and ships the latest target weights to the TiPortfolio-TradingBot webhook so
the broker side can rebalance against them.

Strategy recap (VIX#2 Ratio · unleveraged):
  parent: Signal.Monthly + Signal.VIX(high=30, low=20)
    ├── low_vol  → Weigh.Ratio({QQQ: 0.75, BIL: 0.15, GLD: 0.10})
    └── high_vol → Weigh.Ratio({QQQ: 0.20, BIL: 0.60, GLD: 0.20})

  Sharpe 0.786 (2014–2024), MaxDD -17%, leverage 1.0x — beats QQQ buy-hold
  on risk-adjusted return and beats every Hybrid HV-target variant tested.

Webhook contract (TiPortfolio-TradingBot/app/webhook.py):
  POST {webhook}/webhook
  Body:    {"weights": {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}}
  Returns: 202 Accepted (or 400 / 502 with `error`)

Usage:
  uv run python scheduler/strategies/market_vix_rebalance.py            # live → webhook
  uv run python scheduler/strategies/market_vix_rebalance.py --dry-run  # print only

Env:
  TRADING_BOT_WEBHOOK_URL  base URL of the bot, default http://localhost:5000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import requests
import tiportfolio as ti

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("strategy_runner")

TICKERS: list[str] = ["QQQ", "BIL", "GLD"]
LOW_VOL_RATIO: dict[str, float] = {"QQQ": 0.75, "BIL": 0.15, "GLD": 0.10}
HIGH_VOL_RATIO: dict[str, float] = {"QQQ": 0.20, "BIL": 0.60, "GLD": 0.20}
VIX_HIGH = 30
VIX_LOW = 20

DEFAULT_LOOKBACK_YEARS = 2  # plenty of history for the VIX gate to settle
DEFAULT_WEBHOOK_BASE = "http://localhost:5000"


@dataclass(frozen=True)
class StrategyOutput:
    """Latest rebalance signal extracted from the backtest result."""

    rebalance_date: pd.Timestamp
    weights: dict[str, float]


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


def build_portfolio(vix_data: dict) -> ti.Portfolio:
    """Construct the VIX#2 Ratio parent/child tree."""
    low_vol = ti.Portfolio(
        "low_vol_ratio",
        [
            ti.Select.All(),
            ti.Weigh.Ratio(LOW_VOL_RATIO),
            ti.Action.Rebalance(),
        ],
        TICKERS,
    )
    high_vol = ti.Portfolio(
        "high_vol_ratio",
        [
            ti.Select.All(),
            ti.Weigh.Ratio(HIGH_VOL_RATIO),
            ti.Action.Rebalance(),
        ],
        TICKERS,
    )
    return ti.Portfolio(
        "vix2_ratio",
        [
            ti.Signal.Monthly(),
            ti.Signal.VIX(high=VIX_HIGH, low=VIX_LOW, data=vix_data),
            ti.Action.Rebalance(),
        ],
        [low_vol, high_vol],
    )


def run_strategy(start: str, end: str) -> StrategyOutput:
    """Backtest the strategy and return the most recent target weights."""
    logger.info("Fetching market data %s → %s", start, end)
    data = ti.fetch_data(TICKERS, start=start, end=end)
    vix_data = ti.fetch_data(["^VIX"], start=start, end=end)

    portfolio = build_portfolio(vix_data)
    result = ti.run(ti.Backtest(portfolio, data))

    summary = result.summary()
    logger.info(
        "Backtest done | Sharpe=%.3f CAGR=%.1f%% MaxDD=%.1f%%",
        float(summary.loc["sharpe", "value"]),
        float(summary.loc["cagr", "value"]) * 100,
        float(summary.loc["max_drawdown", "value"]) * 100,
    )

    return _latest_weights(result)


def _latest_weights(result) -> StrategyOutput:
    """Extract the most recent rebalance weights from the parent's history."""
    history = result._results[0]._weight_history  # noqa: SLF001 — library internal
    if not history:
        raise RuntimeError("Backtest produced no weight history; cannot ship signal.")

    df = pd.DataFrame(history)
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date]

    weights = {str(t): float(w) for t, w in zip(latest["ticker"], latest["weight"])}
    return StrategyOutput(rebalance_date=pd.Timestamp(latest_date), weights=weights)


# ---------------------------------------------------------------------------
# Pre-flight check  ←  USER CONTRIBUTION POINT
# ---------------------------------------------------------------------------


def validate_target_weights(weights: dict[str, float]) -> str | None:
    """Pre-flight sanity check before sending weights to the live broker.

    Return ``None`` if the weights look safe, or a human-readable error string
    that aborts the webhook call.

    The webhook itself already enforces:
      • all values are numeric
      • non-empty mapping
      • sum within ±0.01 of 1.0

    This function is the *client-side* guard. It exists because once we go
    live, a buggy strategy update could ship dangerous weights (e.g. 100%
    leveraged into one ticker, or a negative weight on a long-only account).

    Trade-offs to consider:
      - Strict guards = safer but may reject legitimate regime shifts
      - Loose guards = trust the backtest fully; rely on the broker to refuse
      - Concentration cap (e.g. 90%): protects against a runaway strategy bug
      - Negative weight reject: aligns with long-only Alpaca account intent
      - Universe match: refuse if the strategy emits an unexpected ticker

    """
    if any(w < 0 for w in weights.values()):
        return f"Negative weight detected — this account is long-only: {weights}"
    if max(weights.values()) > 0.90:
        return f"Single position > 90% — refusing to ship to avoid concentration risk: {weights}"
    if set(weights) != set(TICKERS):
        return f"Unexpected ticker universe: got {set(weights)}, expected {set(TICKERS)}"
    return None


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def send_webhook(base_url: str, weights: dict[str, float], timeout: float = 10.0) -> dict:
    """POST weights to the TradingBot webhook and return the parsed JSON response."""
    url = base_url.rstrip("/") + "/webhook"
    payload = {"weights": weights}

    secret = os.environ.get("WEBHOOK_SECRET", "")
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    logger.info("POST %s | payload=%s", url, payload)
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)

    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}

    if resp.status_code != 202:
        raise RuntimeError(
            f"Webhook rejected the signal: HTTP {resp.status_code} | {body}"
        )

    logger.info("Webhook accepted | status=%s body=%s", resp.status_code, body)
    return body


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    today = date.today()
    default_start = today - timedelta(days=365 * DEFAULT_LOOKBACK_YEARS)

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default=default_start.isoformat(), help="Backtest start date (YYYY-MM-DD)")
    p.add_argument("--end", default=today.isoformat(), help="Backtest end date (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true", help="Run strategy and print weights, but don't POST")
    p.add_argument(
        "--webhook",
        default=os.environ.get("TRADING_BOT_WEBHOOK_URL", DEFAULT_WEBHOOK_BASE),
        help="Base URL of TiPortfolio-TradingBot (default: %(default)s)",
    )
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args()

    output = run_strategy(start=args.start, end=args.end)

    print()
    print(f"Latest rebalance date : {output.rebalance_date.date()}")
    print("Target weights        :")
    for t, w in output.weights.items():
        print(f"  {t:>6} : {w:7.4f}")
    print(f"  sum   : {sum(output.weights.values()):7.4f}")
    print()

    error = validate_target_weights(output.weights)
    if error:
        logger.error("Pre-flight check failed: %s", error)
        return 2

    if args.dry_run:
        logger.info("Dry run — not sending webhook.")
        return 0

    try:
        send_webhook(args.webhook, output.weights)
    except (requests.RequestException, RuntimeError) as exc:
        logger.error("Webhook delivery failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
