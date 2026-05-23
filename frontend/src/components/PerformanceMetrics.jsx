import { useBenchmark } from "../hooks/useBenchmark";

function computeMetrics(dateSeries) {
  if (!dateSeries || dateSeries.length < 3) return null;

  const first = dateSeries[0].value;
  if (!first || first <= 0) return null;

  const normalized = dateSeries.map((d) => d.value / first);
  const last = normalized[normalized.length - 1];

  const startMs = new Date(dateSeries[0].date).getTime();
  const endMs = new Date(dateSeries[dateSeries.length - 1].date).getTime();
  const years = (endMs - startMs) / (365.25 * 24 * 60 * 60 * 1000);
  const cagr = years > 0 ? Math.pow(last, 1 / years) - 1 : null;

  const returns = [];
  for (let i = 1; i < normalized.length; i++) {
    if (normalized[i - 1] > 0) returns.push(normalized[i] / normalized[i - 1] - 1);
  }
  if (returns.length === 0) return null;

  const DAILY_RF = 0.04 / 252;
  const excessReturns = returns.map((r) => r - DAILY_RF);
  const mean = excessReturns.reduce((a, b) => a + b, 0) / excessReturns.length;
  const variance = excessReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / excessReturns.length;
  const std = Math.sqrt(variance);
  const sharpe = std === 0 ? null : (mean / std) * Math.sqrt(252);

  let peak = normalized[0];
  let maxDD = 0;
  for (const v of normalized) {
    if (v > peak) peak = v;
    const dd = (peak - v) / peak;
    if (dd > maxDD) maxDD = dd;
  }

  const mar = cagr != null && maxDD > 0 ? cagr / maxDD : null;

  return { cagr, sharpe, maxDD, mar };
}

function pct(v) {
  if (v == null || !isFinite(v)) return "~";
  return `${(v * 100).toFixed(1)}%`;
}

function decimal(v, places = 2) {
  if (v == null || !isFinite(v)) return "~";
  return v.toFixed(places);
}

function MetricCell({ value, formatter, colorize = false }) {
  const display = formatter(value);
  if (!colorize || value == null || !isFinite(value)) {
    return <td className="px-4 py-3 tabular-nums text-center">{display}</td>;
  }
  const positive = value >= 0;
  return (
    <td className={`px-4 py-3 tabular-nums text-center font-medium ${positive ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
      {display}
    </td>
  );
}

const METRICS = [
  {
    label: "CAGR",
    key: "cagr",
    fmt: pct,
    colorize: true,
    hint: "Compound annual growth rate from first rebalance date",
  },
  {
    label: "Sharpe Ratio",
    key: "sharpe",
    fmt: (v) => decimal(v),
    colorize: true,
    hint: "Annualised risk-adjusted return (risk-free rate = 4%)",
  },
  {
    label: "Max Drawdown",
    key: "maxDD",
    fmt: (v) => (v == null || !isFinite(v) ? "~" : `-${pct(v)}`),
    colorize: false,
    hint: "Largest peak-to-trough decline",
  },
  {
    label: "MAR Ratio",
    key: "mar",
    fmt: (v) => decimal(v),
    colorize: true,
    hint: "CAGR ÷ Max Drawdown — reward per unit of worst-case loss",
  },
];

export default function PerformanceMetrics() {
  const spy = useBenchmark("SPY");
  const qqq = useBenchmark("QQQ");

  if (spy.loading || qqq.loading) return null;
  if (spy.data?.no_data || qqq.data?.no_data) return null;
  if (!spy.data || !qqq.data) return null;

  const botSeries = spy.data.bot ?? [];
  const spySeries = spy.data.benchmark ?? [];
  const qqqSeries = qqq.data.benchmark ?? [];

  const botMetrics = computeMetrics(botSeries);
  const spyMetrics = computeMetrics(spySeries);
  const qqqMetrics = computeMetrics(qqqSeries);

  const hasBot = botMetrics != null;

  return (
    <div className="mt-6 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted text-muted-foreground text-xs uppercase tracking-wide">
            <th className="px-4 py-3 font-medium text-left">Metric</th>
            {hasBot && <th className="px-4 py-3 font-medium text-center text-indigo-500">TiPortfolio Strategy</th>}
            <th className="px-4 py-3 font-medium text-center text-amber-500">SPY</th>
            <th className="px-4 py-3 font-medium text-center text-emerald-500">QQQ</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map(({ label, key, fmt, colorize, hint }) => (
            <tr key={key} className="odd:bg-muted/20 border-t border-border" title={hint}>
              <td className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">
                {label}
              </td>
              {hasBot && (
                <MetricCell value={botMetrics?.[key]} formatter={fmt} colorize={colorize} />
              )}
              <MetricCell value={spyMetrics?.[key]} formatter={fmt} colorize={colorize} />
              <MetricCell value={qqqMetrics?.[key]} formatter={fmt} colorize={colorize} />
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-4 py-2 text-xs text-muted-foreground border-t border-border">
        Metric calculations use 4% as the risk-free rate. ~ means insufficient data.
      </p>
    </div>
  );
}
