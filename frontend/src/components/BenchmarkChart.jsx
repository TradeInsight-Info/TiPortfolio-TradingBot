import { useBenchmark } from "../hooks/useBenchmark";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";

// Benchmark selector options
const TICKERS = ["SPY", "QQQ", "QQQ+GLD+BIL"];

// Format decimal cumulative return as percentage string for tooltip
function formatPct(value) {
  if (value == null) return "—";
  return `${((value - 1) * 100).toFixed(2)}%`;
}

// Merge bot and benchmark series into a single array keyed by date
function mergeSeries(botArr, benchArr) {
  const map = {};

  for (const point of botArr) {
    map[point.date] = { date: point.date, bot: point.value };
  }
  for (const point of benchArr) {
    if (map[point.date]) {
      map[point.date].benchmark = point.value;
    } else {
      map[point.date] = { date: point.date, benchmark: point.value };
    }
  }

  // Sort by date ascending
  return Object.values(map).sort((a, b) => (a.date > b.date ? 1 : -1));
}

export default function BenchmarkChart({ ticker, onTickerChange }) {
  const { data, loading, error } = useBenchmark(ticker);

  // --- Loading state ---
  if (loading) {
    return (
      <div className="flex justify-center items-center py-16">
        <span className="loading loading-spinner loading-lg text-primary" />
        <span className="ml-3 text-gray-500">Loading performance data…</span>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="alert alert-error max-w-xl mx-auto mt-8">
        <span>Failed to load chart: {error}</span>
      </div>
    );
  }

  // --- No data state ---
  if (!data || data.no_data) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <p className="text-lg font-medium">No performance data yet</p>
        <p className="text-sm mt-1">
          Chart will appear once the bot completes its first rebalance.
        </p>
      </div>
    );
  }

  const chartData = mergeSeries(data.bot, data.benchmark);

  return (
    <div>
      {/* Benchmark selector - switches between tickers without page reload */}
      <div className="flex gap-2 mb-6">
        {TICKERS.map((t) => (
          <button
            key={t}
            onClick={() => onTickerChange(t)}
            className={`btn btn-sm ${ticker === t ? "btn-primary" : "btn-ghost border"}`}
          >
            {t}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />

          {/* X-axis: show only a subset of dates to prevent overload */}
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12 }}
            tickFormatter={(d) => d.slice(5)} // Show "MM-DD" only
            interval="preserveStartEnd"
          />

          {/* Y-axis: formatted as cumulative return % */}
          <YAxis
            tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`}
            tick={{ fontSize: 12 }}
            width={55}
          />

          <Tooltip
            formatter={(value, name) => [formatPct(value), name === "bot" ? "Bot" : ticker]}
            labelFormatter={(label) => `Date: ${label}`}
          />

          <Legend
            formatter={(value) => (value === "bot" ? "Bot" : ticker)}
          />

          {/* Bot equity curve */}
          <Line
            type="monotone"
            dataKey="bot"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />

          {/* Benchmark curve */}
          <Line
            type="monotone"
            dataKey="benchmark"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={false}
            strokeDasharray="5 5"
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>

      <p className="text-xs text-gray-400 mt-2 text-right">
        Indexed to 1.0 at first rebalance ({data.first_rebalance_date}).
        Y-axis shows cumulative return (%).
      </p>
    </div>
  );
}