import { usePositions } from "../hooks/usePositions";

function formatCurrency(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

function formatPct(value, equity) {
  if (!equity) return "—";
  return `${((value / equity) * 100).toFixed(1)}%`;
}

export default function PositionSummary() {
  const { data, loading, error } = usePositions();

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm py-2">
        <span className="animate-spin inline-block h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
        Loading positions…
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-destructive py-2">
        Could not load live positions: {error}
      </div>
    );
  }

  if (!data) return null;

  const { positions = [], equity, cash, stale } = data;

  return (
    <div className="rounded-lg border border-border bg-card p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Current Holdings
        </h3>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {stale && (
            <span className="text-yellow-600 dark:text-yellow-400 font-medium">
              <span aria-hidden="true">⚠ </span>stale
            </span>
          )}
          <span>Equity: {formatCurrency(equity)}</span>
          <span>·</span>
          <span>Cash: {formatCurrency(cash)}</span>
        </div>
      </div>

      {positions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open positions.</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {positions.map((p) => (
            <div
              key={p.symbol}
              className="flex flex-col rounded-md bg-muted/40 px-3 py-2 text-sm min-w-[110px]"
            >
              <span className="font-mono font-semibold">{p.symbol}</span>
              <span className="text-muted-foreground text-xs">
                {p.qty} shares
              </span>
              <span className="tabular-nums">
                {formatCurrency(p.market_value)}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatPct(p.market_value, equity)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
