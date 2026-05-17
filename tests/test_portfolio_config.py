from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.portfolio_config  # noqa: F401 — registers PortfolioConfig with Base.metadata
from app.portfolio_config import PortfolioConfig, PortfolioConfigRepository


@pytest.fixture(scope="module")
def engine():
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return e


@pytest.fixture()
def repo(engine):
    factory = sessionmaker(bind=engine)
    r = PortfolioConfigRepository(factory)
    yield r
    # clean up between tests
    with factory() as s:
        s.query(PortfolioConfig).delete()
        s.commit()


def test_portfolio_config_table_exists(engine):
    inspector = inspect(engine)
    assert "portfolio_config" in inspector.get_table_names()
    columns = {col["name"] for col in inspector.get_columns("portfolio_config")}
    assert columns == {"id", "initial_amount", "recorded_at"}


def test_get_returns_none_on_empty_table(repo):
    assert repo.get_initial_amount() is None


def test_set_then_get_returns_stored_value(repo):
    repo.set_initial_amount(Decimal("10000.00"))
    assert repo.get_initial_amount() == Decimal("10000.00")


def test_set_twice_upserts_not_duplicates(repo, engine):
    repo.set_initial_amount(Decimal("10000.00"))
    repo.set_initial_amount(Decimal("12000.00"))
    assert repo.get_initial_amount() == Decimal("12000.00")
    with sessionmaker(bind=engine)() as s:
        assert s.query(PortfolioConfig).count() == 1
