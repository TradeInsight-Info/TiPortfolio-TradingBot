# Entity Relationship Diagram

```mermaid
erDiagram
    REBALANCE_EVENTS {
        integer     id                PK  "auto-increment"
        timestamptz timestamp             "UTC, indexed"
        json        target_weights        "e.g. {SPY: 0.6, GLD: 0.4}"
        json        orders                "array of ORDER_ENTRY (see below)"
        varchar10   status                "success | partial | failed | no_change"
        text        error_message         "null on success"
    }

    ORDER_ENTRY {
        string      symbol
        integer     delta_shares          "signed: positive=buy, negative=sell"
        string      direction             "buy | sell"
        string      alpaca_order_id       "null if submission failed"
        string      status                "accepted | failed"
        string      fill_status           "filled | partially_filled | canceled | rejected | pending | null"
        float       filled_qty            "null until filled"
        float       filled_avg_price      "null until filled"
        float       portfolio_value       "account equity at rebalance time"
    }

    PORTFOLIO_CONFIG {
        integer     id                PK  "auto-increment"
        numeric124  initial_amount        "starting equity, recorded once"
        timestamptz recorded_at           "when first set"
    }

    REBALANCE_EVENTS ||--o{ ORDER_ENTRY : "orders[ ] (JSON array)"
```

## Notes

- `ORDER_ENTRY` is not a physical table — it is stored as a JSON array in `rebalance_events.orders`.
- `PORTFOLIO_CONFIG` is a single-row table used as the baseline for the performance chart.
- No foreign key between `REBALANCE_EVENTS` and `PORTFOLIO_CONFIG` — both are read independently by the `/benchmark` endpoint to reconstruct the bot equity curve.
