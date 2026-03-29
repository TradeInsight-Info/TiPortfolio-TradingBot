"""
pytest configuration for integration tests against the real PostgreSQL DB.

Prerequisites:
  - Docker PostgreSQL is running
  - DATABASE_URL env var is set, OR the default
    postgresql://user:password@localhost:5432/bot is reachable.
"""

from __future__ import annotations
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.rebalance import RebalanceRepository

# Engine
@pytest.fixture(scope="session")
def db_engine():
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/bot",
    )
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

# Per-test rollback isolation
@pytest.fixture()
def db_session(db_engine):
    """
    Each test runs inside a SAVEPOINT that is rolled back when the test ends.
    Test data never reaches the real table.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()

# Repository fixture
@pytest.fixture()
def repo(db_session):
    """
    Return a RebalanceRepository wired to the isolated test session.
    """
    # Pass a factory that always returns the *same* already-open session
    # so the repo's _tx() context manager operates within our test savepoint.
    factory = sessionmaker()
    factory.configure(bind=db_session.bind)

    # override _session_factory to return db_session directly
    class _BoundRepo(RebalanceRepository):
        @property
        def _session_factory(self):
            return lambda: db_session

        @_session_factory.setter
        def _session_factory(self, _):
            pass  # ignore the __init__ assignment

    return _BoundRepo(None)

# Reusable test data
@pytest.fixture()
def sample_weights():
    return {"AAPL": 0.5, "INTC": -0.5}


@pytest.fixture()
def sample_orders():
    return [
        {"symbol": "AAPL", "qty": 10, "side": "buy"},
        {"symbol": "INTC", "qty": 5,  "side": "sell"},
    ]
