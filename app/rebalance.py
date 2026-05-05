"""
All DB operations on rebalance_events.

Atomic guarantee:
  Every save() runs inside one SQLAlchemy session.  If anything raises
  (validation error, DB constraint, network blip ...) the session is rolled
  back before the exception propagates, so the table never ends up with a
  half-written row.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.models import RebalanceEvent

# add 'no_change' for portfolio already matches target
VALID_STATUSES = {"success", "failed", "partial", "no_change"}


class RebalanceRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # Internal helpers
    @contextmanager
    def _tx(self) -> Generator[Session, None, None]:
        """
        Open a session, commit on success, rollback on any exception.
        """
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Write
    def save(
        self,
        *,
        target_weights: dict[str, float],
        orders: list[dict],
        status: str,
        error_message: str | None = None,
        timestamp: datetime | None = None,
    ) -> RebalanceEvent:
        """
        Persist one rebalance event atomically.

        Args:
            target_weights: e.g. {"SPY": 0.6, "GLD": 0.4}
            orders:          list of order dicts serialized by `_serialize_orders_for_db`
            status:         "success" | "failed" | "partial" | "no_change"
            error_message:  populated when status != "success"
            timestamp:      defaults to now(UTC)

        Returns:
            The persisted RebalanceEvent (detached from the session).

        Raises:
            ValueError: invalid status string
            SQLAlchemyError: DB error - the transaction is rolled back before
                             this propagates, so the table stays consistent.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Must be one of {VALID_STATUSES}."
            )

        event = RebalanceEvent(
            timestamp=timestamp or datetime.now(timezone.utc),
            target_weights=target_weights,
            orders=orders,
            status=status,
            error_message=error_message,
        )

        with self._tx() as session:
            session.add(event)
            session.flush()         # materialise id before commit
            session.expunge(event)  # detach so the object lives after close()

        return event

    # Read - used by GET /delta to return records immediately after webhook
    def get_all(self) -> list[RebalanceEvent]:
        """
        Return all rebalance events ordered by timestamp descending (newest first).

        Called by GET /delta. Because POST /webhook commits the record before
        returning its 202 response, the new record is always visible here
        immediately after the webhook call completes.

        Returns:
            List of detached RebalanceEvent objects, newest first.
        """
        with self._tx() as session:
            events = (
                session.query(RebalanceEvent)
                .order_by(RebalanceEvent.timestamp.desc())
                .all()
            )
            session.expunge_all()   # detach before session closes
        return events

    # Read - existing method kept for date-range queries
    def query_by_date_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[RebalanceEvent]:
        """
        Return events where start <= timestamp <= end, ordered by timestamp asc.
        Uses the ix_rebalance_events_timestamp index defined in models.py.
        """
        with self._tx() as session:
            events = (
                session.query(RebalanceEvent)
                .filter(
                    RebalanceEvent.timestamp >= start,
                    RebalanceEvent.timestamp <= end,
                )
                .order_by(RebalanceEvent.timestamp)
                .all()
            )
            session.expunge_all()   # detach before session closes
        return events
