"""
GET /positions — return live Alpaca portfolio positions with a 1-hour cache.

Alpaca is authoritative for position state; this endpoint is the ONLY
place in the app that answers "what do we hold right now."
"""

from __future__ import annotations

import logging
import threadingfrom datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from app.alpaca_client import AlpacaClient, AlpacaError

logger = logging.getLogger(__name__)
bp = Blueprint("positions", __name__)

_CACHE_TTL_SECONDS = 3600
_cache: dict = {}       # keys: "data" (response dict), "fetched_at" (datetime)
_cache_lock = threading.Lock()

@bp.get("/positions")
def get_positions():
    """
    Return live Alpaca positions, equity, and cash.

    Cached for 1 hour. Serves stale data with ``"stale": true`` if Alpaca
    is unreachable but a prior response exists. Returns 503 only when
    Alpaca is down and no cached response exists.

    Response shape::

        {
            "positions": [{"symbol", "qty", "market_value", "avg_entry_price"}],
            "equity":    float,
            "cash":      float,
            "as_of":     ISO 8601 timestamp of last successful fetch
        }
    """    now = datetime.now(timezone.utc)

    if _cache and (now - _cache["fetched_at"]).total_seconds() < _CACHE_TTL_SECONDS:
        return jsonify(_cache["data"]), 200

    try:
        alpaca = AlpacaClient(
            api_key=current_app.config["ALPACA_API_KEY"],
            api_secret=current_app.config["ALPACA_API_SECRET"],
            mode=current_app.config["ALPACA_MODE"],
        )
        positions = alpaca.list_positions_full()
        account   = alpaca.get_account()
    except AlpacaError as exc:
        logger.error("Alpaca positions fetch failed: %s", exc)
        with _cache_lock:
            if _cache:
                return jsonify({**_cache["data"], "stale": True}), 200        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 503

    data = {
        "positions": positions,
        "equity":    account["equity"],
        "cash":      account["cash"],
        "as_of":     now.isoformat(),
    }
    with _cache_lock:
        _cache.update({"data": data, "fetched_at": now})    return jsonify(data), 200
