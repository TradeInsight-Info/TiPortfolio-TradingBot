from sqlalchemy import text

from app.database import ensure_strategy_id_column


def test_ensure_strategy_id_column_idempotent(db_engine):
    # Runs against the real Postgres test engine (conftest db_engine fixture).
    ensure_strategy_id_column(db_engine)   # first run
    ensure_strategy_id_column(db_engine)   # must not raise (idempotent)
    with db_engine.connect() as c:
        cols = [r[0] for r in c.execute(text(
            "select column_name from information_schema.columns "
            "where table_name='rebalance_events'"
        ))]
    assert "strategy_id" in cols
