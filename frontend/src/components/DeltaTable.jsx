import { useState } from "react";
import { useDelta } from "../hooks/useDelta";

// Badge variant → utility class mapping (replaces daisyUI badge-*)
const BADGE_VARIANTS = {
  success: "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
  warning: "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200",
  error:   "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
  primary: "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-primary/10 text-primary",
  info:    "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
};

// Event-level rebalance status → badge variant
const STATUS_VARIANT = {
  success:   "success",
  partial:   "warning",
  failed:    "error",
  no_change: "primary",
};

// Labels for order directions
const DIRECTION_LABEL = {
  buy:  "BUY",
  sell: "SELL",
};

// Direction text colour (semantic, not daisyUI)
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
  if (!raw) return "—";
  const map = {
    filled:          "Filled",
    partiallyfilled: "Partially Filled",
    canceled:        "Canceled",
    rejected:        "Rejected",
    pending:         "Pending",
    accepted:        "Accepted",
    expired:         "Expired",
    doneforday:      "Done For Day",
    success:         "Success",
    failed:          "Failed",
    partial:         "Partial",
    nochange:        "No Change",
  };
  return map[raw.toLowerCase()] ?? raw;
};


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

function hasPendingOrders(event) {
  return event.orders.some(
    (o) => !FILL_STATUS.includes(o.fill_status) && o.status === "accepted"
  );
}

function formatPrice(value) {
  if (value == null) return "—";
  const n = Number(value);
  if (!isFinite(n)) return "~";
  return `$${n.toFixed(2)}`;
}

function formatQty(value) {
  if (value == null) return "—";
  const n = Number(value);
  if (!isFinite(n)) return "~";
  return Number.isInteger(n) ? String(n) : n.toFixed(4).replace(/\.?0+$/, "");
}

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
        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs border border-yellow-500 text-yellow-600 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 transition-colors disabled:opacity-50"
        onClick={handleClick}
        disabled={busy}
      >
        {busy ? (
          <>
            <span className="animate-spin inline-block h-3 w-3 border-2 border-current border-t-transparent rounded-full" />
            Checking…
          </>
        ) : (
          "Retry polling"
        )}
      </button>
      {retryError && (
        <span className="text-xs text-destructive">{retryError}</span>
      )}
    </div>
  );
}

export default function DeltaTable() {
  const { events, loading, error, refreshEvent } = useDelta();

  if (loading) {
    return (
      <div className="flex justify-center items-center py-16">
        <span className="animate-spin inline-block h-8 w-8 border-4 border-primary border-t-transparent rounded-full" />
        <span className="ml-3 text-muted-foreground">Loading trade records…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-destructive bg-destructive/10 text-destructive px-4 py-3 max-w-xl mx-auto mt-8">
        <span>Failed to load trade records: {error}</span>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
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

  const rows = events.flatMap((event) => {
    const date = new Date(event.timestamp).toLocaleString("en-NZ", {
      timeZone: "Pacific/Auckland",
      year:   "numeric",
      month:  "short",
      day:    "numeric",
      hour:   "2-digit",
      minute: "2-digit",
    });

    const pending = hasPendingOrders(event);

    if (event.orders.length === 0) {
      return [{
        eventId:    event.id,
        date,
        symbol:     "—",
        direction:  "—",
        shares:     "—",
        filledAvg:  null,
        status:     event.status,
        pending:    false,
        isFirstRow: true,
        orderCount: 1,
      }];
    }

    return event.orders.map((order, idx) => ({
      eventId:        event.id,
      date,
      symbol:         order.symbol,
      direction:      order.direction,
      shares:         order.shares,
      filledAvg:      order.filled_avg_price,
      status:         event.status,
      pending,
      isFirstRow:     idx === 0,
      orderCount:     event.orders.length,
      portfolioValue: idx === 0 ? (order.portfolio_value ?? null) : null,
    }));
  });

  return (
    <div className="overflow-x-auto rounded-lg shadow w-full">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted text-muted-foreground text-xs uppercase tracking-wide text-center">
            <th className="px-3 py-3 font-medium">Date</th>
            <th className="px-3 py-3 font-medium">Symbol</th>
            <th className="px-3 py-3 font-medium">Direction</th>
            <th className="px-3 py-3 font-medium">Shares</th>
            <th className="px-3 py-3 font-medium">Avg Price</th>
            <th className="px-3 py-3 font-medium">Portfolio Value</th>
            <th className="px-3 py-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="odd:bg-muted/20 hover:bg-accent/40 transition-colors border-t border-border">
              {row.isFirstRow && (
                <td
                  rowSpan={row.orderCount}
                  className="px-3 py-3 text-sm text-muted-foreground whitespace-nowrap align-top"
                >
                  <div>{row.date}</div>
                  {row.pending && (
                    <RetryButton eventId={row.eventId} onRefresh={refreshEvent} />
                  )}
                </td>
              )}

              <td className="px-3 py-3 font-mono font-medium">{row.symbol}</td>
              <td className="px-3 py-3">
                <span className={DIRECTION_STYLES[row.direction] ?? ""}>
                  {DIRECTION_LABEL[row.direction] ?? row.direction}
                </span>
              </td>
              <td className="px-3 py-3 tabular-nums">{formatQty(row.shares)}</td>
              <td className="px-3 py-3 tabular-nums">{formatPrice(row.filledAvg)}</td>

              {row.isFirstRow && (
                <td rowSpan={row.orderCount} className="px-3 py-3 align-top tabular-nums">
                  {row.portfolioValue != null
                    ? `$${Number(row.portfolioValue).toLocaleString("en-US", { minimumFractionDigits: 2 })}`
                    : "—"}
                </td>
              )}
              {row.isFirstRow && (
                <td rowSpan={row.orderCount} className="px-3 py-3 align-top text-center">
                  {row.status === "no_change" ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <span className={BADGE_VARIANTS[STATUS_VARIANT[row.status] ?? "primary"]}>
                      {formatStatus(row.status)}
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
