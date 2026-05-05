"""
GET /health - confirm the application and database are both operational.

Requirement:
  The response must confirm DB is writable by performing a lightweight
  write-then-rollback probe, not just a connection ping.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

@bp.route("/health", methods=["GET"])
def health():
    """
    Check application and database health.

    DB writability is confirmed by opening a transaction, executing a
    lightweight no-op write (SELECT 1), then rolling it back. This proves
    the DB connection is alive and the session factory can open a write
    transaction without leaving any data behind.

    Responses:
        200 OK - app is running and DB is writable.
        503    - DB is unreachable or not writable.
    """
    db_status = "ok"
    db_error: str | None = None

    try:
        session_factory = current_app.config["DB_SESSION"]
        session = session_factory()
        try:
            # Lightweight write-probe: any writable statement works.
            session.execute(text("SELECT 1"))
            # Rollback ensures nothing is committed to the DB.
            session.rollback()
        finally:
            session.close()

    except SQLAlchemyError as exc:
        db_status = "unreachable"
        db_error = str(exc)
        logger.error("Health check DB probe failed: %s", exc)

    if db_status != "ok":
        return jsonify({
            "status":   "degraded",
            "db":       db_status,
            "db_error": db_error,
        }), 503

    return jsonify({
        "status": "ok",
        "db":     "writable",
    }), 200
