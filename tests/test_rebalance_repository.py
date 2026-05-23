"""
Tests for RebalanceRepository.

1. atomic writes (failed order → no partial record)
2. queryable by date range
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models import RebalanceEvent
from app.rebalance import VALID_STATUSES

# Atomic writes
class TestAtomicWrites:
    def test_successful_save_returns_event_with_id(
        self, repo, sample_weights, sample_orders
    ):
        event = repo.save(
            target_weights=sample_weights,
            orders=sample_orders,
            status="success",
        )
        assert event.id is not None
        assert event.status == "success"
        assert event.target_weights == sample_weights
        assert event.orders == sample_orders
        assert event.error_message is None

    def test_failed_status_stores_error_message(
        self, repo, sample_weights, sample_orders
    ):
        event = repo.save(
            target_weights=sample_weights,
            orders=sample_orders,
            status="failed",
            error_message="Broker timeout",
        )
        assert event.status == "failed"
        assert event.error_message == "Broker timeout"

    def test_partial_status_accepted(self, repo, sample_weights, sample_orders):
        event = repo.save(
            target_weights=sample_weights,
            orders=sample_orders,
            status="partial",
            error_message="INTC order rejected",
        )
        assert event.status == "partial"

    def test_invalid_status_raises_before_db_write(
        self, repo, sample_weights, sample_orders
    ):
        """
        ValueError is raised before touching the DB — no partial record created.
        """
        with pytest.raises(ValueError, match="Invalid status"):
            repo.save(
                target_weights=sample_weights,
                orders=sample_orders,
                status="unknown",
            )

    def test_db_error_rolls_back_no_partial_record(
        self, repo, sample_weights, sample_orders, db_session
    ):
        """
        Simulate a DB error mid-write.
        The transaction must be rolled back — no half-written row survives.
        """
        count_before = db_session.query(RebalanceEvent).count()

        original_flush = db_session.flush

        def failing_flush(*args, **kwargs):
            raise SQLAlchemyError("Simulated DB failure")

        db_session.flush = failing_flush

        with pytest.raises(SQLAlchemyError, match="Simulated DB failure"):
            repo.save(
                target_weights=sample_weights,
                orders=sample_orders,
                status="success",
            )

        # Restore and verify no record was written
        db_session.flush = original_flush
        count_after = db_session.query(RebalanceEvent).count()
        assert count_after == count_before, (
            "A partial record was written despite the DB error — rollback failed"
        )

    @pytest.mark.parametrize("status", list(VALID_STATUSES))
    def test_all_valid_statuses_accepted(
        self, repo, sample_weights, sample_orders, status
    ):
        event = repo.save(
            target_weights=sample_weights,
            orders=sample_orders,
            status=status,
        )
        assert event.status == status

# Queryable by date range
class TestDateRangeQuery:
    def _save_at(self, repo, weights, orders, dt: datetime) -> RebalanceEvent:
        """
        Save a rebalance event at a specific timestamp.
        """
        return repo.save(
            target_weights=weights,
            orders=orders,
            status="success",
            timestamp=dt,
        )

    def test_returns_events_within_range(
        self, repo, sample_weights, sample_orders
    ):
        """
        Test that events within the specified date range are returned.
        
        e.g. 
        - Save 3 records for the last 2 days
        - Query the data for the last 1 day
        - Confirm that the 2 records will be returned
        """
        now = datetime.now(timezone.utc)
        e1 = self._save_at(repo, sample_weights, sample_orders, now - timedelta(days=2))
        e2 = self._save_at(repo, sample_weights, sample_orders, now - timedelta(days=1))
        e3 = self._save_at(repo, sample_weights, sample_orders, now)

        results = repo.query_by_date_range(
            start=now - timedelta(days=1, hours=1),
            end=now + timedelta(hours=1),
        )
        ids = {r.id for r in results}

        assert e2.id in ids
        assert e3.id in ids
        assert e1.id not in ids

    def test_excludes_events_outside_range(
        self, repo, sample_weights, sample_orders
    ):
        """
        Test that events within the specified date range are returned.
        
        e.g. 
        - Save the data for the last 10 days
        - Check the data for the last 3 days
        - Confirm that the record will not appear again
        """
        now = datetime.now(timezone.utc)
        outside = self._save_at(
            repo, sample_weights, sample_orders, now - timedelta(days=10)
        )

        results = repo.query_by_date_range(
            start=now - timedelta(days=3),
            end=now,
        )
        assert outside.id not in {r.id for r in results}

    def test_results_ordered_by_timestamp(
        self, repo, sample_weights, sample_orders
    ):
        """
        Test that results are ordered by timestamp.
        
        e.g. 
        - Save the data for the last 3 hours, 1 hour, and 2 hours ago
        - Check the data
        - Confirm that the record will be ordered by timestamp
        """
        now = datetime.now(timezone.utc)
        for delta in [3, 1, 2]:
            self._save_at(
                repo, sample_weights, sample_orders, now - timedelta(hours=delta)
            )

        results = repo.query_by_date_range(
            start=now - timedelta(hours=4),
            end=now,
        )
        timestamps = [r.timestamp for r in results]
        assert timestamps == sorted(timestamps)

    def test_empty_range_returns_empty_list(self, repo):
        """
        Test that an empty range returns an empty list.

        e.g.
        - Query for data in the future
        - Confirm that the result will return an empty list not crush
        """
        far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        results = repo.query_by_date_range(
            start=far_future,
            end=far_future + timedelta(days=1),
        )
        assert results == []


class TestGetLastSuccessful:
    def test_returns_none_when_no_events(self, repo):
        assert repo.get_last_successful() is None

    def test_returns_none_when_only_failed_events(self, repo, sample_weights, sample_orders):
        repo.save(target_weights=sample_weights, orders=sample_orders, status="failed")
        assert repo.get_last_successful() is None

    def test_returns_most_recent_success(self, repo, sample_weights, sample_orders):
        from datetime import datetime, timezone, timedelta
        repo.save(
            target_weights=sample_weights, orders=sample_orders, status="success",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        newer = repo.save(
            target_weights={"SPY": 1.0}, orders=[], status="success",
        )
        result = repo.get_last_successful()
        assert result.id == newer.id

    def test_ignores_no_change_events(self, repo, sample_weights, sample_orders):
        success = repo.save(
            target_weights=sample_weights, orders=sample_orders, status="success",
        )
        repo.save(target_weights=sample_weights, orders=[], status="no_change")
        result = repo.get_last_successful()
        assert result.id == success.id
