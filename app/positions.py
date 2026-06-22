"""
GET /positions — return live Alpaca portfolio positions with a 1-hour cache.

Alpaca is authoritative for position state; this endpoint is the ONLY
place in the app that answers "what do we hold right now."
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from app.alpaca_client import AlpacaClient, AlpacaError
from app import strategies_registry as reg

logger = logging.getLogger(__name__)
bp = Blueprint("positions", __name__)

_CACHE_TTL_SECONDS = 3600
# Keyed by strategy_id (str) or None for the default account.
# Each entry: {"data": response_dict, "fetched_at": datetime}
_cache: dict = {}
_cache_lock = threading.Lock()


@bp.get("/positions")
def get_positions():
    """
    Return live Alpaca positions, equity, and cash.

    Query params:
        strategy_id (optional): Scope positions to this strategy's Alpaca
                                account. Unknown id → 400. When absent, uses
                                default config creds (backward compat).

    Cached per strategy_id for 1 hour. Serves stale data with ``"stale": true``
    if Alpaca is unreachable but a prior response exists. Returns 503 only when
    Alpaca is down and no cached response exists.

    Response shape::

        {
            "positions": [{"symbol", "qty", "market_value", "avg_entry_price"}],
            "equity":    float,
            "cash":      float,
            "as_of":     ISO 8601 timestamp of last successful fetch
        }
    """
    strategy_id = request.args.get("strategy_id")
    if strategy_id is not None:
        try:
            strategy = reg.get_strategy(strategy_id)
        except (KeyError, TypeError):
            return jsonify({"error": f"Unknown strategy_id: {strategy_id!r}."}), 400
    else:
        strategy = None

    cache_entry = _cache.get(strategy_id)
    now = datetime.now(timezone.utc)

    if cache_entry and (now - cache_entry["fetched_at"]).total_seconds() < _CACHE_TTL_SECONDS:
        return jsonify(cache_entry["data"]), 200

    if strategy is not None:
        api_key    = os.getenv(strategy["alpaca_key_env"], "")
        api_secret = os.getenv(strategy["alpaca_secret_env"], "")
    else:
        api_key    = current_app.config["ALPACA_API_KEY"]
        api_secret = current_app.config["ALPACA_API_SECRET"]

    try:
        alpaca = AlpacaClient(
            api_key=api_key,
            api_secret=api_secret,
            mode=current_app.config["ALPACA_MODE"],
        )
        positions = alpaca.list_positions_full()
        account   = alpaca.get_account()
    except AlpacaError as exc:
        logger.error("Alpaca positions fetch failed: %s", exc)
        with _cache_lock:
            if cache_entry:
                return jsonify({**cache_entry["data"], "stale": True}), 200
        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 503

    data = {
        "positions": positions,
        "equity":    account["equity"],
        "cash":      account["cash"],
        "as_of":     now.isoformat(),
    }
    with _cache_lock:
        _cache[strategy_id] = {"data": data, "fetched_at": now}
    return jsonify(data), 200
