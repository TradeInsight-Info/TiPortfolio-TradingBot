from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class RebalanceEvent(Base):
    __tablename__ = "rebalance_events"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    target_weights  = Column(JSONB, nullable=False)   # e.g. {"AAPL": 0.5, "INTC": -0.5}
    orders          = Column(JSONB, nullable=False)   # e.g. [{"symbol": "AAPL", "qty": 10, "side": "buy"}]
    status          = Column(String(10), nullable=False)  # "success" / "failed" / "partial"
    error_message   = Column(Text, nullable=True)

    # Index for date range queries
    __table_args__ = (
        Index("ix_rebalance_events_timestamp", "timestamp"),
    )

