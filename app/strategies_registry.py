"""Registry of tradable strategies. Each strategy maps to its own Alpaca paper
account (separate credential env vars) so the three strategies never share
buying power. Adding a strategy = one entry here + its two account secrets."""

STRATEGIES: dict[str, dict] = {
    "vix": {
        "name": "VIX Regime (QQQ/BIL/GLD)",
        "universe": ["QQQ", "BIL", "GLD"],
        "alpaca_key_env": "ALPACA_KEY_VIX",
        "alpaca_secret_env": "ALPACA_SECRET_VIX",
        "benchmark": "QQQ",
    },
    "trend_broad": {
        "name": "Trend Following (13-asset GTAA)",
        "universe": ["SPY", "QQQ", "IWM", "IEF", "TLT", "GLD", "BIL",
                     "EFA", "EEM", "DBC", "LQD", "HYG", "VNQ"],
        "alpaca_key_env": "ALPACA_KEY_TREND",
        "alpaca_secret_env": "ALPACA_SECRET_TREND",
        "benchmark": "SPY",
    },
    "pit_top5": {
        "name": "S&P 500 Dual Momentum (top-5, point-in-time)",
        "universe": [],   # dynamic; empty => webhook skips the subset check
        "alpaca_key_env": "ALPACA_KEY_PIT",
        "alpaca_secret_env": "ALPACA_SECRET_PIT",
        "benchmark": "SPY",
    },
}


def get_strategy(strategy_id: str) -> dict:
    return STRATEGIES[strategy_id]


def list_strategies() -> list[dict]:
    return [{"id": sid, "name": s["name"]} for sid, s in STRATEGIES.items()]
