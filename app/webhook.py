"""
POST /webhook - receive a target-portfolio signal and execute a rebalance.
GET  /delta   - return all rebalance records stored in the DB.

Processing choice: SYNCHRONOUS
  1. Validate the incoming weights payload.
  2. Fetch current Alpaca positions.
  3. Fetch current prices via Alpaca latest-trade endpoint.
  4. Calculate share deltas.
  5. Submit orders to Alpaca.
  6. Save the full rebalance record to DB.
  7. Return the saved record in the response so the caller sees it immediately.
Return:
    202 - with event ID if validation passes and the event is logged
    400 - with descriptive error if payload is malformed or weights are invalid
    502 - with descriptive error if Alpaca API is unreachable
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.alpaca_client import AlpacaClient, AlpacaError
from app.calculator import calculate_deltas
from app.order_executor import OrderExecutor
from app.rebalance import RebalanceRepository

logger = logging.getLogger(__name__)
bp = Blueprint("webhook", __name__)

WEIGHT_SUM_TOLERANCE = 0.01

def _payload_hash(data: dict) -> str:
    """
    Return the SHA-256 hex digest of the canonical JSON payload.
    """
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

def _validate_weights(weights: object) -> str | None:
    """
    Validate the weights value from the incoming payload.

    Returns:
        None - weights are valid.
        str  - human-readable error message describing the problem.
    """
    if not isinstance(weights, dict):
        return "'weights' must be a JSON object, e.g. {\"SPY\": 0.5, \"QQQ\": 0.5}."

    if not weights:
        return "'weights' must not be empty."

    for symbol, value in weights.items():
        if not isinstance(value, (int, float)):
            return (
                f"Weight for '{symbol}' must be a number, "
                f"got {type(value).__name__!r} instead."
            )

    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        return (
            f"Weights must sum to 1.0 (tolerance ±{WEIGHT_SUM_TOLERANCE}), "
            f"but the provided weights sum to {total:.6f}."
        )

    return None


def _serialize_orders_for_db(
    deltas,
    order_results,
) -> list[dict]:
    """
    Build the list that gets stored in the DB 'orders' JSON column.

    Each element follows the AC2 schema:
        {
            "symbol":          str,   # ticker
            "delta_shares":    int,   # signed: positive=buy, negative=sell
            "direction":       str,   # "buy" | "sell"
            "alpaca_order_id": str|None,
            "status":          str    # "accepted" | "failed"
        }

    Merges delta information (from calculator) with execution outcomes
    (from order_executor) by matching on symbol.
    """
    # Build a lookup: symbol -> OrderResult
    result_by_symbol = {r.symbol: r for r in order_results}

    rows = []
    for d in deltas:
        result = result_by_symbol.get(d.symbol)
        rows.append({
            "symbol":          d.symbol,
            "delta_shares":    d.delta,                          # signed int
            "direction":       "buy" if d.delta > 0 else "sell",
            "alpaca_order_id": result.alpaca_order_id if result else None,
            "status":          "accepted" if (result and result.success) else "failed",
        })
    return rows

def _event_to_dict(event) -> dict:
    """Serialise a RebalanceEvent ORM object to a plain dict for JSON responses."""
    return {
        "id":             event.id,
        "timestamp":      event.timestamp.isoformat(),
        "target_weights": event.target_weights,
        "orders":         event.orders,
        "status":         event.status,
        "error_message":  event.error_message,
    }


@bp.route("/webhook", methods=["POST"])
def receive_signal():
    """
    Accept a target-portfolio signal, execute the rebalance, and persist the
    full audit record to the database.

    Expected body:
        {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}}

    Responses:
        202 Accepted - rebalance attempted; record saved; record returned in body.
        400 Bad Request - payload is malformed or weights are invalid.
        502 Bad Gateway - Alpaca API is unreachable.
    """
    received_at = datetime.now(timezone.utc)

    # 1. Parse JSON
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Request body must be valid JSON with Content-Type: application/json."}), 400

    # Check required field
    if "weights" not in body:
        return jsonify({"error": "Missing required field: 'weights'."}), 400

    # Validate weights
    error = _validate_weights(body["weights"])
    if error:
        return jsonify({"error": error}), 400

    # Log (timestamp + payload hash)
    payload_hash = _payload_hash(body)
    logger.info(
        "Webhook received | timestamp=%s hash=%s",
        received_at.isoformat(), payload_hash,
    )

    # 2. Fetch current positions from Alpaca
    target_weights: dict[str, float] = body["weights"]
    try:
        alpaca = AlpacaClient(
            api_key=current_app.config["ALPACA_API_KEY"],
            api_secret=current_app.config["ALPACA_API_SECRET"],
            mode=current_app.config["ALPACA_MODE"],
        )
        current_positions = alpaca.get_positions(
            target_symbols=set(target_weights.keys())
        )
    except AlpacaError as exc:
        logger.error("Alpaca positions fetch failed | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 502

    # 3. Fetch current prices
    try:
        current_prices = alpaca.get_latest_prices(set(target_weights.keys()))
    except AlpacaError as exc:
        logger.error("Alpaca price fetch failed | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Failed to fetch prices from Alpaca: {exc}"}), 502

    # 4. Fetch account equity for delta calculation
    try:
        portfolio_value = alpaca.get_account_equity()
    except AlpacaError as exc:
        logger.error("Alpaca account fetch failed | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Failed to fetch account equity from Alpaca: {exc}"}), 502

    # 5. Calculate share deltas
    try:
        deltas = calculate_deltas(
            portfolio_value=portfolio_value,
            target_weights=target_weights,
            current_positions=current_positions,
            current_prices=current_prices,
        )
    except ValueError as exc:
        logger.error("Delta calculation error | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Delta calculation failed: {exc}"}), 400

    # 5.5. Check if no deltas (portfolio already matches target)
    if not deltas:
        logger.info("No deltas — portfolio already matches target | hash=%s", payload_hash)
        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        saved_event = repo.save(
            target_weights=target_weights,
            orders=[],
            status="no_change",
            error_message=None,
            timestamp=received_at,
        )
        return jsonify({
            "status": "no_change",
            "received_at": received_at.isoformat(),
            "payload_hash": payload_hash,
            "rebalance_event": _event_to_dict(saved_event),
        }), 202

    # 6. Submit orders to Alpaca
    executor = OrderExecutor(
        api_key=current_app.config["ALPACA_API_KEY"],
        api_secret=current_app.config["ALPACA_API_SECRET"],
        base_url=alpaca._base_url,
    )
    execution_result = executor.execute(deltas)

    # 7. Persist the full rebalance record to DB
    # This block runs AFTER order submission - whether orders succeeded or failed.
    # The record is always written so every decision is auditable.
    db_orders = _serialize_orders_for_db(deltas, execution_result.orders)

    try:
        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        saved_event = repo.save(
            target_weights=target_weights,
            orders=db_orders,
            status=execution_result.status,
            error_message=execution_result.error_message,
            timestamp=received_at,
        )
    except SQLAlchemyError as exc:
        logger.error("DB write failed | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": "Failed to persist rebalance record."}), 500

    logger.info(
        "Rebalance record saved | event_id=%s status=%s",
        saved_event.id, saved_event.status,
    )

    # 8. Respond with the saved record
    return jsonify({
        "status":          execution_result.status,
        "received_at":     received_at.isoformat(),
        "payload_hash":    payload_hash,
        "rebalance_event": _event_to_dict(saved_event),   # full record in response
    }), 202

@bp.route("/delta", methods=["GET"])
def get_delta():
    """
    Return all rebalance records from the database, newest first.

    The record written by POST /webhook is included in this response
    immediately after the webhook call completes.

    Responses:
        200 OK - JSON array of rebalance event objects.
    """
    repo = RebalanceRepository(current_app.config["DB_SESSION"])
    events = repo.get_all()

    return jsonify({
        "count":  len(events),
        "events": [_event_to_dict(e) for e in events],
    }), 200
