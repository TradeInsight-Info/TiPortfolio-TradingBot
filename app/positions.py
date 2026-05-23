"""
GET /positions — return live Alpaca portfolio positions with a 1-hour cache.

Alpaca is authoritative for position state; this endpoint is the ONLY
place in the app that answers "what do we hold right now."
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from app.alpaca_client import AlpacaClient, AlpacaError

logger = logging.getLogger(__name__)
bp = Blueprint("positions", __name__)

_CACHE_TTL_SECONDS = 3600
_cache: dict = {}  # keys: "data" (response dict), "fetched_at" (datetime)


@bp.get("/positions")
def get_positions():
    now = datetime.now(timezone.utc)

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
        if _cache:
            return jsonify({**_cache["data"], "stale": True}), 200
        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 503

    data = {
        "positions": positions,
        "equity":    account["equity"],
        "cash":      account["cash"],
        "as_of":     now.isoformat(),
    }
    _cache["data"]       = data
    _cache["fetched_at"] = now
    return jsonify(data), 200
