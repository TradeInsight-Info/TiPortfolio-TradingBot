from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Index, Text, JSON, text
from app.database import Base

class RebalanceEvent(Base):
    __tablename__ = "rebalance_events"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    target_weights  = Column(JSON, nullable=False)   # e.g. {"AAPL": 0.5, "INTC": -0.5}

    # Each element in the orders list carries fill confirmation fields:
    #   {
    #     "symbol":            str,        # ticker, e.g. "SPY"
    #     "delta_shares":      int,        # signed: positive=buy, negative=sell
    #     "direction":         str,        # "buy" | "sell"
    #     "alpaca_order_id":   str | None, # Alpaca UUID; None if submission failed
    #     "status":            str,        # "accepted" | "failed"
    #     "fill_status":       str | None, # Alpaca order lifecycle status after polling
    #                                      # e.g. "filled", "partially_filled",
    #                                      # "canceled", "rejected", "pending" (poll timeout)
    #                                      # None when order submission itself failed
    #     "filled_qty":        float | None, # shares actually executed; None if not filled
    #     "filled_avg_price":  float | None  # average execution price; None if not filled
    #   }
    orders          = Column(JSON, nullable=False)

    status          = Column(String(10), nullable=False)  # "success" / "failed" / "partial" / "no_change" / "pending"
    error_message   = Column(Text, nullable=True)
    payload_hash    = Column(String(64), nullable=True)   # SHA-256 of canonical weights JSON; NULL for legacy rows

    # Index for date range queries; partial unique index prevents duplicate executions
    __table_args__ = (
        Index("ix_rebalance_events_timestamp", "timestamp"),
        Index(
            "uq_rebalance_events_payload_hash",
            "payload_hash",
            unique=True,
            postgresql_where=text("payload_hash IS NOT NULL"),
        ),
    )
