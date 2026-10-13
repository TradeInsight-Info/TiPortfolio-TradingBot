"""
POST /webhook                    - receive a target-portfolio signal and execute a rebalance.
GET  /delta                      - return all rebalance records stored in the DB.

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
import hmac
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app import limiter, PUBLIC_READ_LIMIT
from app.alpaca_client import AlpacaClient, AlpacaError
from app.calculator import calculate_deltas
from app import strategies_registry as reg
from app.order_executor import ExecutionResult, OrderExecutor, OrderResult
from app.portfolio_config import PortfolioConfigRepository
from app.rebalance import RebalanceRepository

logger = logging.getLogger(__name__)
bp = Blueprint("webhook", __name__)

WEIGHT_SUM_TOLERANCE = 0.01

# Statuses after which Alpaca will fill no more of the order. partially_filled is
# deliberately absent: such an order can still progress to filled, and counting it
# as done froze the stored record at whatever chunk Alpaca had reported so far.
_SETTLED_FILL_STATUSES = frozenset({
    "filled",
    "canceled",
    "expired",
    "rejected",
    "done_for_day",
})
# Statuses whose response carries a real filled_qty / filled_avg_price worth storing.
_FILL_DATA_STATUSES = _SETTLED_FILL_STATUSES | {"partially_filled"}

_RECONCILE_WINDOW = timedelta(days=7)
_RECONCILE_COOLDOWN_S = 60.0
_reconcile_cooldown: dict[int, float] = {}   # event_id -> monotonic ts of last re-poll
_reconcile_lock = threading.Lock()


def _reconcile_event(event, repo) -> None:
    """Re-poll this event's pending orders via its strategy account; persist updates.
    Swallows per-order Alpaca errors. No-op if no creds / no pending orders."""
    updated = [dict(o) for o in event.orders]
    pending_idx = [i for i, o in enumerate(updated)
                   if o.get("alpaca_order_id") and o.get("fill_status") not in _SETTLED_FILL_STATUSES]
    if not pending_idx:
        return
    try:
        strategy = reg.get_strategy(event.strategy_id)
    except (KeyError, TypeError):
        return
    key = os.getenv(strategy["alpaca_key_env"], "")
    secret = os.getenv(strategy["alpaca_secret_env"], "")
    if not key or not secret:
        return
    try:
        alpaca = AlpacaClient(api_key=key, api_secret=secret, mode=current_app.config["ALPACA_MODE"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconcile: client build failed event=%s err=%s", event.id, exc)
        return
    changed = False
    for i in pending_idx:
        order = updated[i]
        try:
            body = alpaca.get_order(order["alpaca_order_id"])
        except AlpacaError as exc:
            logger.warning("reconcile: re-poll failed event=%s order=%s err=%s",
                           event.id, order["alpaca_order_id"], exc)
            continue
        status = body.get("status", "unknown")
        if status != order.get("fill_status"):
            changed = True
        updated[i]["fill_status"] = status
        if status in _FILL_DATA_STATUSES:
            rq, rp = body.get("filled_qty"), body.get("filled_avg_price")
            updated[i]["filled_qty"] = float(rq) if rq else None
            updated[i]["filled_avg_price"] = float(rp) if rp else None
    if changed:
        try:
            repo.update_orders(event.id, updated)
            event.orders = updated   # reflect in the current /delta response, not just the next
        except SQLAlchemyError as exc:
            logger.error("reconcile: DB update failed event=%s err=%s", event.id, exc)
    with _reconcile_lock:
        if all(o.get("fill_status") in _SETTLED_FILL_STATUSES for o in updated):
            _reconcile_cooldown.pop(event.id, None)


def reconcile_pending(events, repo) -> None:
    """Reconcile recent events with pending fills, bounded by a per-event cooldown."""
    now_wall = datetime.now(timezone.utc)
    now_mono = time.monotonic()
    for event in events:
        if (now_wall - event.timestamp) > _RECONCILE_WINDOW:
            continue
        if not any(o.get("alpaca_order_id") and o.get("fill_status") not in _SETTLED_FILL_STATUSES
                   for o in (event.orders or [])):
            continue
        with _reconcile_lock:
            last = _reconcile_cooldown.get(event.id, 0.0)
            if now_mono - last < _RECONCILE_COOLDOWN_S:
                continue
            _reconcile_cooldown[event.id] = now_mono
        _reconcile_event(event, repo)


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
        "strategy_id":    event.strategy_id,
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
        "shares":    abs(order["delta_shares"]),
        "status":           order.get("status"),
        # Fill fields - may be None until the order reaches a terminal state
        "fill_status":      order.get("fill_status"),
        "filled_qty":       order.get("filled_qty"),
        "filled_avg_price": order.get("filled_avg_price"),
        "portfolio_value":  order.get("portfolio_value"), 
    }

def _event_to_public_dict(event) -> dict:
    """
    Serialise a RebalanceEvent for the public GET /delta response.

    Includes 'id' for client reference.

    Deliberately omits:
      - target_weights
      - error_message
    """
    return {
        "id":          event.id,
        "timestamp":   event.timestamp.isoformat(),
        "status":      event.status,
        "strategy_id": event.strategy_id,
        "orders":      [_format_order_public(o) for o in event.orders],
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

    Query params:
        dry_run (optional): "true" | "1" | "yes" — fetch live Alpaca state and compute
            deltas, but skip order submission and DB write. Returns 200 with delta preview.

    Expected body:
        {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}}

    Responses:
        200 OK    - dry_run=true; delta preview returned, nothing persisted.
        202 Accepted - rebalance attempted; record saved; record returned in body.
        400 Bad Request - payload is malformed or weights are invalid.
        401 Unauthorized - WEBHOOK_SECRET configured and Authorization header is missing or wrong.
        502 Bad Gateway - Alpaca API is unreachable.
    """
    secret = current_app.config.get("WEBHOOK_SECRET")
    if not secret or not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {secret}"):
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

    # Validate strategy_id
    strategy_id = body.get("strategy_id")
    try:
        strategy = reg.get_strategy(strategy_id) if strategy_id else None
    except (KeyError, TypeError):
        strategy = None
    if strategy is None:
        return jsonify({"error": "Unknown or missing strategy_id."}), 400

    universe = strategy["universe"]
    if universe:
        extra = set(body["weights"]) - set(universe)
        if extra:
            return jsonify({
                "error": (
                    f"Weights contain tickers outside the "
                    f"'{strategy_id}' universe: {sorted(extra)}"
                )
            }), 400

    # Log (timestamp + payload hash)
    payload_hash = _payload_hash(body)
    logger.info(
        "Webhook received | timestamp=%s hash=%s",
        received_at.isoformat(), payload_hash,
    )

    target_weights: dict[str, float] = body["weights"]

    _read_repo = RebalanceRepository(current_app.config["DB_SESSION"])
    # Idempotency: if we've already processed this exact payload, return the existing record
    _existing = _read_repo.find_by_hash(payload_hash)
    if _existing and _existing.status != "pending":
        logger.info("Duplicate webhook | hash=%s returning existing event_id=%s", payload_hash, _existing.id)
        return jsonify({
            "status":          _existing.status,
            "received_at":     received_at.isoformat(),
            "payload_hash":    payload_hash,
            "rebalance_event": _event_to_dict(_existing),
        }), 202
    _last_event = _read_repo.get_last_successful(strategy_id)
    if _last_event and _last_event.target_weights:
        prev_symbols = {s for s, w in _last_event.target_weights.items() if w > 0}
        new_symbols  = set(target_weights.keys())
        if prev_symbols != new_symbols:
            logger.warning(
                "symbol_universe_changed | prev=%s new=%s last_event_id=%s",
                sorted(prev_symbols), sorted(new_symbols), _last_event.id,
            )

    alpaca: AlpacaClient | None = None

    is_simulated = current_app.config.get("APP_MODE") == "simulated"
    simulation_date: date | None = None

    if is_simulated:
        # 2-4. Simulated: derive positions/prices/equity from DB + yfinance
        raw_date = body.get("date")
        if raw_date:
            try:
                simulation_date = date.fromisoformat(raw_date)
            except ValueError:
                return jsonify({"error": f"Invalid 'date': {raw_date!r}. Expected YYYY-MM-DD."}), 400
        else:
            simulation_date = date.today()

        from app.simulated_client import SimulatedAlpacaClient, SimulatedDataError

        config_repo = PortfolioConfigRepository(current_app.config["DB_SESSION"])
        initial_amount = float(config_repo.get_initial_amount() or 10000)

        sim_client = SimulatedAlpacaClient(
            session_factory=current_app.config["DB_SESSION"],
            simulation_date=simulation_date,
            initial_amount=initial_amount,
        )
        try:
            current_positions = sim_client.get_positions(target_symbols=set(target_weights.keys()))
            current_prices    = sim_client.get_latest_prices(set(target_weights.keys()))
            portfolio_value   = sim_client.get_account_equity()
        except SimulatedDataError as exc:
            logger.error("Simulated price fetch failed | hash=%s error=%s", payload_hash, exc)
            return jsonify({"error": f"Simulated price fetch failed: {exc}"}), 502

    else:
        # 2. Fetch current positions from Alpaca (use per-strategy account creds)
        strat_key    = os.getenv(strategy["alpaca_key_env"], "")
        strat_secret = os.getenv(strategy["alpaca_secret_env"], "")
        try:
            alpaca = AlpacaClient(
                api_key=strat_key,
                api_secret=strat_secret,
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

    # Fix 3: position drift — warn if non-zero symbol set diverges from last successful event
    if _last_event and _last_event.target_weights:
        expected_symbols = {s for s, w in _last_event.target_weights.items() if w > 0}
        actual_symbols   = {sym for sym, qty in current_positions.items() if qty > 0}
        drifted          = expected_symbols.symmetric_difference(actual_symbols)
        if drifted:
            logger.warning(
                "position_drift_detected | expected=%s actual=%s last_event_id=%s",
                sorted(expected_symbols), sorted(actual_symbols), _last_event.id,
            )

    # 5. Calculate share deltas (same for both modes)
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

    # Dry-run: return computed deltas without submitting orders or writing to DB
    if request.args.get("dry_run", "").lower() in ("1", "true", "yes"):
        logger.info("Dry-run mode | hash=%s deltas=%d", payload_hash, len(deltas))
        return jsonify({
            "dry_run":         True,
            "received_at":     received_at.isoformat(),
            "payload_hash":    payload_hash,
            "portfolio_value": portfolio_value,
            "deltas": [
                {
                    "symbol":         d.symbol,
                    "direction":      "buy" if d.delta > 0 else "sell",
                    "delta_shares":   d.delta,
                    "current_shares": d.current_shares,
                    "target_shares":  d.target_shares,
                }
                for d in deltas
            ],
        }), 200

    # Record starting equity once, on the first real (non-dry-run) execution
    if not is_simulated:
        config_repo = PortfolioConfigRepository(current_app.config["DB_SESSION"])
        if config_repo.get_initial_amount() is None:
            config_repo.set_initial_amount(Decimal(str(portfolio_value)))

    # 5.5. Check if no deltas (portfolio already matches target)
    if not deltas:
        logger.info("No deltas — portfolio already matches target | hash=%s", payload_hash)
        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        if simulation_date is not None:
            event_ts = datetime(simulation_date.year, simulation_date.month, simulation_date.day, tzinfo=timezone.utc)
        else:
            event_ts = received_at
        saved_event = repo.save(
            target_weights=target_weights,
            orders=[],
            status="no_change",
            error_message=None,
            timestamp=event_ts,
            strategy_id=strategy_id,
        )
        return jsonify({
            "status": "no_change",
            "received_at": received_at.isoformat(),
            "payload_hash": payload_hash,
            "rebalance_event": _event_to_dict(saved_event),
        }), 202

    # 6. Execute orders
    if is_simulated:
        # Simulated: immediately mark all orders as filled at yfinance close price
        order_results = [
            OrderResult(
                symbol=d.symbol,
                side="buy" if d.delta > 0 else "sell",
                qty=abs(d.delta),
                success=True,
                fill_status="filled",
                filled_qty=float(abs(d.delta)),
                filled_avg_price=current_prices[d.symbol],
            )
            for d in deltas
        ]
        execution_result = ExecutionResult(orders=order_results, status="success")
    else:
        # Live: write pending row before submitting orders so a crash is auditable
        assert alpaca is not None  # guaranteed when not is_simulated
        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        event_id: int | None = None
        event_id, created = repo.save_pending(
            target_weights=target_weights,
            payload_hash=payload_hash,
            timestamp=received_at,
            strategy_id=strategy_id,
        )
        if not created:
            # Race: another request already claimed this hash
            _existing = repo.find_by_hash(payload_hash)
            logger.info("Duplicate in-flight webhook | hash=%s event_id=%s", payload_hash, event_id)
            return jsonify({
                "status":          _existing.status if _existing else "pending",
                "received_at":     received_at.isoformat(),
                "payload_hash":    payload_hash,
            }), 202

        executor = OrderExecutor(
            api_key=strat_key,
            api_secret=strat_secret,
            base_url=alpaca._base_url,
            alpaca_client=alpaca,
        )
        try:
            execution_result = executor.execute(deltas, signal_hash=payload_hash)
        except Exception as exc:
            logger.error("Order execution failed | hash=%s event_id=%s error=%s", payload_hash, event_id, exc)
            repo.finalise(event_id, orders=[], status="failed", error_message=str(exc))
            return jsonify({"error": f"Order execution failed: {exc}"}), 502

    # 7. Persist the full rebalance record to DB
    db_orders = _serialize_orders_for_db(deltas, execution_result.orders, portfolio_value)
    if simulation_date is not None:
        event_ts = datetime(simulation_date.year, simulation_date.month, simulation_date.day, tzinfo=timezone.utc)
    else:
        event_ts = received_at

    try:
        if is_simulated:
            repo = RebalanceRepository(current_app.config["DB_SESSION"])
            saved_event = repo.save(
                target_weights=target_weights,
                orders=db_orders,
                status=execution_result.status,
                error_message=execution_result.error_message,
                timestamp=event_ts,
                strategy_id=strategy_id,
            )
        else:
            repo.finalise(
                event_id,
                orders=db_orders,
                status=execution_result.status,
                error_message=execution_result.error_message,
            )
            saved_event = repo.get_by_id(event_id)
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

@bp.route("/strategies", methods=["GET"])
@limiter.limit(PUBLIC_READ_LIMIT)
def list_strategies():
    """
    Return all registered trading strategies.

    Responses:
        200 OK - JSON array of {id, name} objects.
    """
    return jsonify(reg.list_strategies()), 200


@bp.route("/delta", methods=["GET"])
@limiter.limit(PUBLIC_READ_LIMIT)
def get_delta():
    """
    Return all rebalance records from the database, newest first.

    The record written by POST /webhook is included in this response
    immediately after the webhook call completes.

    Query params:
        since       (optional): ISO 8601 timestamp. When provided, only records
                                with timestamp after this value are returned.
                                e.g.: GET /delta?since=2026-04-01T00:00:00Z
        strategy_id (optional): Filter results to a single strategy.
                                Unknown strategy_id → 400.

    Responses:
        200 OK - JSON array of rebalance event objects.
        400    - 'since' param is invalid ISO 8601, or strategy_id is unknown.
    """
    repo = RebalanceRepository(current_app.config["DB_SESSION"])

    # Validate optional strategy_id filter
    strategy_id = request.args.get("strategy_id")
    if strategy_id is not None:
        try:
            reg.get_strategy(strategy_id)
        except KeyError:
            return jsonify({"error": f"Unknown strategy_id: {strategy_id!r}."}), 400

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

        events = repo.get_since(since_dt, strategy_id)
    else:
        events = repo.get_all(strategy_id)

    reconcile_pending(events, repo)
    events = [e for e in events if e.orders]
    return jsonify({
        "count":  len(events),
        "events": [_event_to_public_dict(e) for e in events],
    }), 200

@bp.route("/config", methods=["GET"])
@limiter.limit(PUBLIC_READ_LIMIT)
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
        return jsonify({"initial_amount": 10000}), 200
    return jsonify({
        "initial_amount": float(row.initial_amount),
        "recorded_at":    row.recorded_at.isoformat(),
    }), 200


@bp.route("/market/clock", methods=["GET"])
@limiter.limit(PUBLIC_READ_LIMIT)
def market_clock():
    """
    Return Alpaca market clock. No auth required — read-only.

    Responses:
        200 - {is_open: bool, next_open: str, next_close: str, timestamp: str}
        502 - Alpaca unreachable
    """
    client = AlpacaClient(
        current_app.config["ALPACA_API_KEY"],
        current_app.config["ALPACA_API_SECRET"],
        current_app.config["ALPACA_MODE"],
    )
    try:
        clock = client.get_clock()
    except AlpacaError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(clock), 200
