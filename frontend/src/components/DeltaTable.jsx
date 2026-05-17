import { useState } from "react";
import { useDelta } from "../hooks/useDelta";

// Badge colour mapping for rebalance event status
const STATUS_STYLES = {
  success: "badge-success",
  partial: "badge-warning",
  failed:  "badge-error",
  no_change: "badge-primary",
};

// Labels for order directions
const DIRECTION_LABEL = {
  buy:  "BUY",
  sell: "SELL",
};

// Badge colour for direction
const DIRECTION_STYLES = {
  buy:  "text-green-600 font-semibold",
  sell: "text-red-500 font-semibold",
};

const FILL_STATUS = [
  "filled",
  "partially_filled",
  "pending",
  "canceled",
  "rejected",
];

const formatStatus = (raw) => {
  if (!raw) return '—';
  const map = {
    // fill_status
    filled:          'Filled',
    partiallyfilled: 'Partially Filled',
    canceled:        'Canceled',
    rejected:        'Rejected',
    pending:         'Pending',
    accepted:        'Accepted',
    expired:         'Expired',
    doneforday:      'Done For Day',
    // event status
    success:         'Success',
    failed:          'Failed',
    partial:         'Partial',
    nochange:        'No Change',
  };
  return map[raw.toLowerCase()] ?? raw;
};

// Alpaca fill status badge colour
// "pending"  → orange warning  (initial poll window expired before fill confirmed)
// "filled"   → green success
// everything else (partially_filled, canceled, rejected, …) → primary
function fillStatusBadge(fillStatus) {
  if (!fillStatus) return null;
  const styles = {
    filled:           "badge-success",
    partially_filled: "badge-warning",
    pending:          "badge-warning",
    canceled:         "badge-primary",
    rejected:         "badge-error",
  };
  return styles[fillStatus] ?? "badge-info";
}

// WarningIcon shown next to the retry button when a fill is still pending
function WarningIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-4 w-4 inline-block text-orange-500 mr-1 shrink-0"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53
           0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1
           1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
        clipRule="evenodd"
      />
    </svg>
  );
}

// Check whether any order in an event needs a fill status refresh.
function hasPendingOrders(event) {
  return event.orders.some(
    (o) =>
      !FILL_STATUS.includes(o.fill_status) && o.status === "accepted");
}

// Format a number as a dollar price string (e.g. 153.42 → "$153.42")
function formatPrice(value) {
  if (value == null) return "—";
  return `$${Number(value).toFixed(2)}`;
}

// Format a quantity, stripping unnecessary trailing zeros (e.g. 10.0 → "10")
function formatQty(value) {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, "");
}

// RetryButton - isolated so each event row manages its own loading state
function RetryButton({ eventId, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [retryError, setRetryError] = useState(null);

  async function handleClick() {
    setBusy(true);
    setRetryError(null);
    const result = await onRefresh(eventId);
    if (!result.ok) {
      setRetryError(result.error ?? "Refresh failed.");
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-col items-start gap-1 mt-1">
      <div className="flex items-center gap-1">
        <WarningIcon />
        <span className="text-xs text-orange-500">Fill unconfirmed</span>
      </div>
      <button
        className="btn btn-xs btn-outline btn-warning"
        onClick={handleClick}
        disabled={busy}
      >
        {busy ? (
          <>
            <span className="loading loading-spinner loading-xs mr-1" />
            Checking…
          </>
        ) : (
          "Retry polling"
        )}
      </button>
      {retryError && (
        <span className="text-xs text-error">{retryError}</span>
      )}
    </div>
  );
}

export default function DeltaTable() {
  const { events, loading, error, refreshEvent } = useDelta();

  // --- Loading state ---
  if (loading) {
    return (
      <div className="flex justify-center items-center py-16">
        <span className="loading loading-spinner loading-lg text-primary" />
        <span className="ml-3 text-gray-500">Loading trade records…</span>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="alert alert-error max-w-xl mx-auto mt-8">
        <span>Failed to load trade records: {error}</span>
      </div>
    );
  }

  // --- Empty state ---
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-16 w-16 mb-4 opacity-40"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 17v-2a4 4 0 014-4h4M9 7h.01M15 7h.01M12 17h.01"
          />
        </svg>
        <p className="text-lg font-medium">No trade records yet</p>
        <p className="text-sm mt-1">Records will appear here once the bot executes its first rebalance.</p>
      </div>
    );
  }

  // Each event may contain multiple orders (one per symbol traded).
  // Render one row per order, merging the event-level date and status.
  const rows = events.flatMap((event) => {
    const date = new Date(event.timestamp).toLocaleString("en-NZ", {
      timeZone: "Pacific/Auckland",  // Display in NZ local time
      year:  "numeric",
      month: "short",
      day:   "numeric",
      hour:  "2-digit",
      minute:"2-digit",
    });
    
    const pending = hasPendingOrders(event);

    // Render a single summary row for no_change events
    if (event.orders.length === 0) {
      return [{
        eventId:    event.id,
        date,
        symbol:    "—",
        direction: "—",
        shares:    "—",
        status:    event.status,
        pending:    false,
        fillStatus: null,
        filledQty:  null,
        filledAvg:  null,
        isFirstRow: true,
        orderCount: 1,
      }];
    }

    return event.orders.map((order, idx) => ({
      eventId:   event.id,
      date,
      symbol:    order.symbol,
      direction: order.direction,
      shares:    order.shares,
      status:    event.status,
      pending,
      fillStatus: order.fill_status,
      filledQty:  order.filled_qty,
      filledAvg:  order.filled_avg_price,
      // Only render the date and status cells on the first order row of each event
      isFirstRow: idx === 0,
      orderCount: event.orders.length,
      portfolioValue: idx === 0 ? (order.portfolio_value ?? null) : null,
    }));
  });

  return (
    <div className="overflow-x-auto rounded-lg shadow w-full">
      <table className="table table-zebra w-full">
        <thead>
          <tr className="bg-base-200 text-base-content text-sm uppercase tracking-wide text-center text-wrap">
            <th>Date</th>
            <th>Symbol</th>
            <th>Direction</th>
            <th>Shares</th>
            {/* Fill columns */}
            <th>Fill Status</th>
            <th>Filled Qty</th>
            <th>Avg Price</th>
            <th>Portfolio Value</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="hover">
              {/* Date + retry button: only on the first order row of each event */}
              {row.isFirstRow && (
                <td
                  rowSpan={row.orderCount}
                  className="text-sm text-gray-600 whitespace-nowrap align-top pt-3"
                >
                  <div>{row.date}</div>
                  {row.pending && (
                    <RetryButton eventId={row.eventId} onRefresh={refreshEvent} />
                  )}
                </td>
              )}

              {/* Per-order columns */}
              <td className="font-mono font-medium">{row.symbol}</td>
              <td>
                <span className={DIRECTION_STYLES[row.direction] ?? ""}>
                  {DIRECTION_LABEL[row.direction] ?? row.direction}
                </span>
              </td>
              <td className="tabular-nums">{row.shares}</td>

              {/* Fill status badge */}
              <td className="text-center font-bold">
                {row.fillStatus ? (
                  <span className={`badge badge-sm badge-soft ${fillStatusBadge(row.fillStatus)}`}>
                    {formatStatus(row.fillStatus)}
                  </span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </td>

              {/* Filled quantity */}
              <td className="tabular-nums">{formatQty(row.filledQty)}</td>

              {/* Average fill price */}
              <td className="tabular-nums">{formatPrice(row.filledAvg)}</td>

              {row.isFirstRow && (
                <td rowSpan={row.orderCount} className="align-top pt-3 tabular-nums">
                  {row.portfolioValue != null
                    ? `$${Number(row.portfolioValue).toLocaleString("en-US", { minimumFractionDigits: 2 })}`
                    : "—"}
                </td>
              )}
              {/* Event-level status badge: only on the first row */}
              {row.isFirstRow && (
                <td rowSpan={row.orderCount} className="align-top text-center pt-3 font-bold">
                  <span className={`badge badge-sm badge-soft ${STATUS_STYLES[row.status] ?? "badge-primary"}`}>
                    {formatStatus(row.status)}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
