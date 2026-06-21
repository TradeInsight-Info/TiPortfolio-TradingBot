import os
from sqlalchemy import create_engine, text as _text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

class Base(DeclarativeBase):
    pass

def get_engine():
    # DATABASE_URL overrides individual parts (useful for tests / local dev)
    url = os.getenv("DATABASE_URL") or (
        "postgresql://{user}:{password}@{host}:{port}/{name}".format(
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            name=os.getenv("DB_NAME", "bot"),
        )
    )
    return create_engine(url)

def ensure_strategy_id_column(engine):
    """Add rebalance_events.strategy_id to a pre-existing DB and backfill to 'vix'.
    create_all() won't ALTER an existing table, so do it explicitly + idempotently."""
    with engine.begin() as conn:
        conn.execute(_text(
            "ALTER TABLE rebalance_events "
            "ADD COLUMN IF NOT EXISTS strategy_id VARCHAR(32) NOT NULL DEFAULT 'vix'"
        ))
        # Guard for a partial/legacy migration where the column was added nullable;
        # on the normal ADD-COLUMN-NOT-NULL-DEFAULT path this matches zero rows.
        conn.execute(_text(
            "UPDATE rebalance_events SET strategy_id = 'vix' WHERE strategy_id IS NULL"
        ))
        conn.execute(_text(
            "CREATE INDEX IF NOT EXISTS ix_rebalance_events_strategy_id "
            "ON rebalance_events (strategy_id)"
        ))


def init_db(app):
    """
    Create all tables on first startup.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    ensure_strategy_id_column(engine)
    app.config["DB_ENGINE"] = engine
    app.config["DB_SESSION"] = sessionmaker(bind=engine)