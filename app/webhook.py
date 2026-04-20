"""
POST /webhook - receive a target-portfolio signal from the algorithm.

Processing choice: SYNCHRONOUS
    Validation runs inside the request/response cycle.
Return:
    202 - with event ID if validation passes and the event is logged.
    400 - with descriptive error if payload is malformed or weights are invalid
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

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

@bp.route("/webhook", methods=["POST"])
def receive_signal():
    """
    Accept a target-portfolio signal.

    Expected body:
        {"weights": {"SPY": 0.5, "QQQ": 0.3, "GLD": 0.2}}

    Responses:
        202 Accepted - signal is valid, logged, and queued for execution.
        400 Bad Request - payload is malformed or weights are invalid.
    """
    received_at = datetime.now(timezone.utc)

    # Parse JSON
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
        "Webhook received | timestamp=%s hash=%s payload=%s",
        received_at.isoformat(),
        payload_hash,
        body,
    )

    # Fetch current positions from Alpaca
    try:
        alpaca = AlpacaClient(
            api_key=current_app.config["ALPACA_API_KEY"],
            api_secret=current_app.config["ALPACA_API_SECRET"],
            mode=current_app.config["ALPACA_MODE"],
        )
        current_positions = alpaca.get_positions(
            target_symbols=set(body["weights"].keys())
        )
    except AlpacaError as exc:
        logger.error("Alpaca error | hash=%s error=%s", payload_hash, exc)
        return jsonify({"error": f"Failed to fetch positions from Alpaca: {exc}"}), 502 

    return jsonify({
        "status": "accepted",
        "received_at": received_at.isoformat(),
        "payload_hash": payload_hash,
        "current_positions": current_positions, 
    }), 202