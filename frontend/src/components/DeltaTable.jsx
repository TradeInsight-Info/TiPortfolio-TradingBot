import { useDelta } from "../hooks/useDelta";

// Badge colour mapping for rebalance event status
const STATUS_STYLES = {
  success: "badge-success",
  partial: "badge-warning",
  failed:  "badge-error",
  no_change: "badge-neutral",
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

export default function DeltaTable() {
  const { events, loading, error } = useDelta();

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

    // Render a single summary row for no_change events
    if (event.orders.length === 0) {
      return [{
        date,
        symbol:    "—",
        direction: "—",
        shares:    "—",
        status:    event.status,
        rowSpan:   1,
      }];
    }

    return event.orders.map((order, idx) => ({
      date,
      symbol:    order.symbol,
      direction: order.direction,
      shares:    order.shares,
      status:    event.status,
      // Only render the date and status cells on the first order row of each event
      isFirstRow: idx === 0,
      orderCount: event.orders.length,
    }));
  });

  return (
    <div className="overflow-x-auto rounded-lg shadow max-w-5xl mx-auto">
      <table className="table table-zebra w-full">
        <thead>
          <tr className="bg-base-200 text-base-content text-sm uppercase tracking-wide">
            <th>Date</th>
            <th>Symbol</th>
            <th>Direction</th>
            <th>Shares</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="hover">
              {/* Date cell: only shown on first order row of each event */}
              {(row.isFirstRow || row.symbol === "—") && (
                <td
                  rowSpan={row.orderCount ?? 1}
                  className="text-sm text-gray-600 whitespace-nowrap align-top pt-3"
                >
                  {row.date}
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

              {/* Status badge: only shown on first order row */}
              {(row.isFirstRow || row.symbol === "—") && (
                <td rowSpan={row.orderCount ?? 1} className="align-top pt-3">
                  <span className={`badge ${STATUS_STYLES[row.status] ?? "badge-ghost"}`}>
                    {row.status}
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
