from datetime import datetime, timezone
from sqlalchemy import Column, Date, Integer, String, DateTime, Index, Text, JSON
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

    status          = Column(String(10), nullable=False)  # "success" / "failed" / "partial"
    error_message   = Column(Text, nullable=True)

    # "live" for real Alpaca trades; "simulated" for local backtest replays
    source          = Column(String(10), nullable=False, server_default="live")
    # Set only for simulated events — the trading date from the payload
    simulation_date = Column(Date, nullable=True)

    # Index for date range queries
    __table_args__ = (
        Index("ix_rebalance_events_timestamp", "timestamp"),
    )
