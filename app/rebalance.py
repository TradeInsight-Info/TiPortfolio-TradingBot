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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import RebalanceEvent

# add 'no_change' for portfolio already matches target
VALID_STATUSES = {"success", "failed", "partial", "no_change", "pending"}


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
        strategy_id: str = "vix",
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
            strategy_id=strategy_id,
        )

        with self._tx() as session:
            session.add(event)
            session.flush()         # materialise id before commit
            session.expunge(event)  # detach so the object lives after close()

        return event


    def save_pending(
        self,
        *,
        target_weights: dict[str, float],
        payload_hash: str,
        timestamp: datetime | None = None,
        strategy_id: str = "vix",
    ) -> tuple[int, bool]:
        """
        Write a "pending" row before order submission.

        Returns (event_id, created). If a non-pending row with the same hash
        already exists (duplicate call), created=False and event_id belongs to
        the existing row. Callers should short-circuit when created=False.
        """
        if not payload_hash:
            raise ValueError("payload_hash must be non-empty")

        event = RebalanceEvent(
            timestamp=timestamp or datetime.now(timezone.utc),
            target_weights=target_weights,
            orders=[],
            status="pending",
            payload_hash=payload_hash,
            strategy_id=strategy_id,
        )
        try:
            with self._tx() as session:
                session.add(event)
                session.flush()
                session.expunge(event)
            return event.id, True
        except IntegrityError:
            # A row with this hash already exists — return it.
            existing = self.find_by_hash(payload_hash)
            if existing is None:
                raise  # unexpected: integrity error but row not found
            return existing.id, False

    def finalise(
        self,
        event_id: int,
        *,
        orders: list[dict],
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update a pending event with execution results."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}.")
        with self._tx() as session:
            event = session.get(RebalanceEvent, event_id)
            if event is None:
                raise ValueError(f"RebalanceEvent id={event_id} not found.")
            if event.status != "pending":
                raise ValueError(
                    f"RebalanceEvent id={event_id} already finalised (status={event.status!r}).",
                )
            event.orders = list(orders)
            event.status = status
            event.error_message = error_message
            session.flush()

    def find_by_hash(self, payload_hash: str) -> RebalanceEvent | None:
        """Return the event matching this hash, or None."""
        with self._tx() as session:
            event = (
                session.query(RebalanceEvent)
                .filter(RebalanceEvent.payload_hash == payload_hash)
                .first()
            )
            if event is not None:
                session.expunge(event)
        return event

    def update_orders(
        self,
        event_id: int,
        orders: list[dict],
    ) -> RebalanceEvent:
        """
        Replace the orders JSON column of an existing rebalance event.

        Called by the re-poll endpoint after fetching updated fill status
        from Alpaca.  The event's top-level status field is NOT changed here
        because a partial or failed execution status reflects order submission,
        not fill outcome.

        Args:
            event_id: Primary key of the RebalanceEvent row to update.
            orders:   Full replacement list for the orders JSON column.

        Returns:
            The updated RebalanceEvent (detached from the session).

        Raises:
            ValueError:       event_id not found in the database.
            SQLAlchemyError:  DB error - transaction is rolled back automatically.
        """
        with self._tx() as session:
            event = session.get(RebalanceEvent, event_id)
            if event is None:
                raise ValueError(f"RebalanceEvent with id={event_id} not found.")

            # SQLAlchemy does not detect in-place mutations to JSON columns;
            # assign a new list so the ORM marks the column as dirty.
            event.orders = list(orders)

            session.flush()
            session.expunge(event)

        return event

    # Read - used by GET /delta/{id} to return a single event
    def get_by_id(self, event_id: int) -> RebalanceEvent | None:
        """
        Return a single RebalanceEvent by primary key, or None if not found.

        Used by the re-poll endpoint to load the event before querying Alpaca.

        Returns:
            Detached RebalanceEvent, or None.
        """
        with self._tx() as session:
            event = session.get(RebalanceEvent, event_id)
            if event is not None:
                session.expunge(event)
        return event

    # Read - used by GET /delta to return records immediately after webhook
    def get_all(self, strategy_id: str | None = None) -> list[RebalanceEvent]:
        """
        Return all rebalance events ordered by timestamp descending (newest first).

        Called by GET /delta. Because POST /webhook commits the record before
        returning its 202 response, the new record is always visible here
        immediately after the webhook call completes.

        Args:
            strategy_id: When provided, only events for that strategy are returned.

        Returns:
            List of detached RebalanceEvent objects, newest first.
        """
        with self._tx() as session:
            q = session.query(RebalanceEvent)
            if strategy_id is not None:
                q = q.filter(RebalanceEvent.strategy_id == strategy_id)
            events = q.order_by(RebalanceEvent.timestamp.desc()).all()
            session.expunge_all()   # detach before session closes
        return events

    # Read - used by GET /delta?since=<ISO timestamp>
    def get_since(self, since: datetime, strategy_id: str | None = None) -> list[RebalanceEvent]:
        """
        Return events strictly newer than `since`, ordered by timestamp descending.

        Args:
            since:       Timezone-aware datetime; only records with timestamp > since
                         are included.
            strategy_id: When provided, only events for that strategy are returned.

        Returns:
            List of detached RebalanceEvent objects, newest first.
        """
        with self._tx() as session:
            q = (
                session.query(RebalanceEvent)
                .filter(RebalanceEvent.timestamp > since)
            )
            if strategy_id is not None:
                q = q.filter(RebalanceEvent.strategy_id == strategy_id)
            events = q.order_by(RebalanceEvent.timestamp.desc()).all()
            session.expunge_all()
        return events

    def get_last_successful(self) -> RebalanceEvent | None:
        """
        Return the most recent event with status="success", or None if none exists.
        """
        with self._tx() as session:
            event = (
                session.query(RebalanceEvent)
                .filter(RebalanceEvent.status == "success")
                .order_by(RebalanceEvent.timestamp.desc())
                .first()
            )
            if event is not None:
                session.expunge(event)
        return event

    # Delete - dev-only reset helper
    def delete_all(self) -> int:
        """Delete every rebalance event. Returns number of rows deleted."""
        with self._tx() as session:
            count = session.query(RebalanceEvent).delete(synchronize_session=False)
        return count

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
