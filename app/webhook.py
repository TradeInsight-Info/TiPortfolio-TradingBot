"""
POST /webhook                    - receive a target-portfolio signal and execute a rebalance.
GET  /delta                      - return all rebalance records stored in the DB.
POST /delta/<event_id>/refresh   - re-poll Alpaca fill status for pending orders.

Processing choice: SYNCHRONOUS
  1. Validate the incoming weights payload.
  2. Fetch current Alpaca positions.
  3. Fetch current prices via Alpaca latest-trade endpoint.
  4. Fetch account equity.
  5. Calculate share deltas.
  6. Submit orders to Alpaca (includes initial fill poll inside OrderExecutor).
  7. Save the full rebalance record to DB.
  8. Return the saved record in the response so the caller sees it immediately.

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
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.alpaca_client import AlpacaClient, AlpacaError
from app.calculator import calculate_deltas
from app.order_executor import OrderExecutor
from app.portfolio_config import PortfolioConfigRepository
from app.rebalance import RebalanceRepository

logger = logging.getLogger(__name__)
bp = Blueprint("webhook", __name__)

WEIGHT_SUM_TOLERANCE = 0.01

# Alpaca order lifecycle statuses that indicate a fill state
_TERMINAL_FILL_STATUSES = frozenset({
    "filled",
    "partially_filled",
    "canceled",
    "expired",
    "rejected",
    "done_for_day",
})

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
    portfolio_value: float | None = None,
) -> list[dict]:
    """
    Build the list that gets stored in the DB 'orders' JSON column.

    Each element follows the schema:
        {
            "symbol":           str,         # ticker
            "delta_shares":     int,         # signed: positive=buy, negative=sell
            "direction":        str,         # "buy" | "sell"
            "alpaca_order_id":  str | None,
            "status":           str,         # "accepted" | "failed"
            "fill_status":      str | None,  # Alpaca lifecycle status after initial poll
            "filled_qty":       float | None,
            "filled_avg_price": float | None,
            "portfolio_value":  float | None,
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
            # Fill fields populated by OrderExecutor._poll_fill() after submission
            "fill_status":      result.fill_status if result else None,
            "filled_qty":       result.filled_qty if result else None,
            "filled_avg_price": result.filled_avg_price if result else None,
            "portfolio_value":  portfolio_value,
        })
    return rows

def _event_to_dict(event) -> dict:
    """
    Serialise a RebalanceEvent ORM object to a plain dict for JSON responses.
    """
    return {
        "id":             event.id,
        "timestamp":      event.timestamp.isoformat(),
        "target_weights": event.target_weights,
        "orders":         event.orders,
        "status":         event.status,
        "error_message":  event.error_message,
    }

# Public-facing helpers for GET /delta
def _format_order_public(order: dict) -> dict:
    """
    Remove internal fields from a stored order dict for public use.

    Exposes only symbol, direction, and the absolute share count.
    Omits alpaca_order_id and per-order status (internal audit fields).

    Update: Includes fill fields so the frontend can show confirmed 
    execution details and identify orders that are still pending.
    """
    return {
        "symbol":    order["symbol"],
        "direction": order["direction"],
        "shares":    abs(order["delta_shares"]),  # always a positive integer
        "status":           order.get("status"),
        # Fill fields - may be None until the order reaches a terminal state
        "fill_status":      order.get("fill_status"),
        "filled_qty":       order.get("filled_qty"),
        "filled_avg_price": order.get("filled_avg_price"),
        "portfolio_value":  order.get("portfolio_value"), 
    }

def _event_to_public_dict(event) -> dict:
    """
    Serialise a RebalanceEvent for the public GET /delta and refresh response.

    Includes 'id' so the frontend can call POST /delta/<id>/refresh 
    on pending events.
    
    Deliberately omits:
      - target_weights
      - error_message
    """
    return {
        "id":        event.id,
        "timestamp": event.timestamp.isoformat(),
        "status":    event.status,
        "orders":    [_format_order_public(o) for o in event.orders],
    }


@bp.route("/webhook", methods=["POST"])
def receive_signal():
    """
    Accept a target-portfolio signal, execute the rebalance, and persist the
    full audit record to the database.

    Authentication:
        Requires 'Authorization: Bearer <token>' header.
        Token must match WEBHOOK_SECRET env var.
        The secret is never logged or included in any response body.
    
    Expected body:
        {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}}

    Responses:
        202 Accepted - rebalance attempted; record saved; record returned in body.
        400 Bad Request - payload is malformed or weights are invalid.
        401 Unauthorized - WEBHOOK_SECRET configured and Authorization header is missing or wrong.
        502 Bad Gateway - Alpaca API is unreachable.
    """
    secret = current_app.config.get("WEBHOOK_SECRET")
    if secret and request.headers.get("Authorization") != f"Bearer {secret}":
        return jsonify({"error": "Unauthorized"}), 401

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

    # 4. Fetch live account equity for delta calculation
    try:
        portfolio_value = alpaca.get_account_equity()
    except AlpacaError as exc:
        logger.error("Alpaca account fetch failed | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Failed to fetch account equity from Alpaca: {exc}"}), 502

    # Record starting equity once (audit trail only — not used for allocation math)
    config_repo = PortfolioConfigRepository(current_app.config["DB_SESSION"])
    if config_repo.get_initial_amount() is None:
        config_repo.set_initial_amount(Decimal(str(portfolio_value)))

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

    # 6. Submit orders to Alpaca (OrderExecutor also does a fill poll)
    executor = OrderExecutor(
        api_key=current_app.config["ALPACA_API_KEY"],
        api_secret=current_app.config["ALPACA_API_SECRET"],
        base_url=alpaca._base_url,
        alpaca_client=alpaca,           # used internally for fill polling
    )
    execution_result = executor.execute(deltas)

    # 7. Persist the full rebalance record to DB
    # This block runs AFTER order submission - whether orders succeeded or failed.
    # The record is always written so every decision is auditable.
    db_orders = _serialize_orders_for_db(deltas, execution_result.orders, portfolio_value)

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

    Query params:
        since (optional): ISO 8601 timestamp. When provided, only records
                          with timestamp after this value are returned.
                          e.g.: GET /delta?since=2026-04-01T00:00:00Z

    Responses:
        200 OK - JSON array of rebalance event objects.
        400    - 'since' param is present but not a valid ISO 8601 timestamp.
    """
    repo = RebalanceRepository(current_app.config["DB_SESSION"])

    since_param = request.args.get("since")
    if since_param is not None:
        # Parse the caller-supplied ISO 8601 timestamp
        try:
            since_dt = datetime.fromisoformat(since_param)
        except ValueError:
            return jsonify({
                "error": (
                    f"Invalid 'since' value: {since_param!r}. "
                    "Expected ISO 8601 format, e.g. 2026-04-01T00:00:00Z."
                )
            }), 400

        # Treat naive timestamps as UTC
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)

        events = repo.get_since(since_dt)
    else:
        events = repo.get_all()

    return jsonify({
        "count":  len(events),
        "events": [_event_to_public_dict(e) for e in events],
    }), 200

@bp.route("/delta/<int:event_id>/refresh", methods=["POST"])
def refresh_fill_status(event_id: int):
    """
    Re-poll Alpaca for the fill status of any pending orders in a rebalance event.

    Called by the frontend when the user clicks the retry button on an event
    that has orders still in 'pending' fill status.  The webhook flow is NOT
    repeated; only the fill status query (GET /v2/orders/{id}) is made.

    Responses:
        200 OK - updated event returned (orders may still be pending if Alpaca
                 hasn't reached a terminal state yet).
        404    - event_id not found in the database.
        502    - Alpaca API unreachable.
        500    - DB update failed.
    """
    repo = RebalanceRepository(current_app.config["DB_SESSION"])
    event = repo.get_by_id(event_id)

    if event is None:
        return jsonify({"error": f"Event {event_id} not found."}), 404

    # Find orders that still need a fill status update
    pending_orders = [
        o for o in event.orders
        if o.get("alpaca_order_id")
        and o.get("fill_status") not in _TERMINAL_FILL_STATUSES
    ]

    if not pending_orders:
        # Nothing to re-poll; return current state as-is
        logger.info("Refresh requested for event %s but no pending orders found.", event_id)
        return jsonify(_event_to_public_dict(event)), 200

    # Build Alpaca client for re-polling
    try:
        alpaca = AlpacaClient(
            api_key=current_app.config["ALPACA_API_KEY"],
            api_secret=current_app.config["ALPACA_API_SECRET"],
            mode=current_app.config["ALPACA_MODE"],
        )
    except Exception as exc:
        logger.error("Failed to create Alpaca client for refresh: %s", exc)
        return jsonify({"error": f"Failed to connect to Alpaca: {exc}"}), 502

    # Build a mutable copy of the orders list so we can update individual entries
    updated_orders = [dict(o) for o in event.orders]

    for i, order in enumerate(updated_orders):
        if not order.get("alpaca_order_id"):
            continue
        if order.get("fill_status") in _TERMINAL_FILL_STATUSES:
            continue

        order_id = order["alpaca_order_id"]
        try:
            body = alpaca.get_order(order_id)
        except AlpacaError as exc:
            # Leave this order as pending; log and continue to the next
            logger.warning(
                "Re-poll failed | event_id=%s order_id=%s symbol=%s error=%s",
                event_id, order_id, order["symbol"], exc,
            )
            continue

        alpaca_status = body.get("status", "unknown")
        updated_orders[i]["fill_status"] = alpaca_status

        if alpaca_status in _TERMINAL_FILL_STATUSES:
            raw_qty   = body.get("filled_qty")
            raw_price = body.get("filled_avg_price")
            updated_orders[i]["filled_qty"]       = float(raw_qty) if raw_qty else None
            updated_orders[i]["filled_avg_price"] = float(raw_price) if raw_price else None

            logger.info(
                "Fill confirmed via refresh | event_id=%s order_id=%s symbol=%s "
                "status=%s filled_qty=%s filled_avg_price=%s",
                event_id, order_id, order["symbol"],
                alpaca_status, updated_orders[i]["filled_qty"],
                updated_orders[i]["filled_avg_price"],
            )

    # Persist the updated orders back to DB
    try:
        event = repo.update_orders(event_id, updated_orders)
    except SQLAlchemyError as exc:
        logger.error("DB update failed for event %s: %s", event_id, exc)
        return jsonify({"error": "Failed to update rebalance record."}), 500

    return jsonify(_event_to_public_dict(event)), 200


@bp.route("/config", methods=["GET"])
def get_config():
    """
    Return the stored initial portfolio amount.

    Responses:
        200 - {"initial_amount": <value>, "recorded_at": <iso>} when set
        200 - {"initial_amount": null} when not yet recorded
    """
    config_repo = PortfolioConfigRepository(current_app.config["DB_SESSION"])
    row = config_repo.get()
    if row is None:
        return jsonify({"initial_amount": None}), 200
    return jsonify({
        "initial_amount": float(row.initial_amount),
        "recorded_at":    row.recorded_at.isoformat(),
    }), 200
