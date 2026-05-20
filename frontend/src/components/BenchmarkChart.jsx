import { useBenchmark } from "../hooks/useBenchmark";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const LABEL = { bot: "Bot", spy: "SPY", qqq: "QQQ" };

function formatPct(value) {
  if (value == null) return "—";
  return `${((value - 1) * 100).toFixed(2)}%`;
}

// Merge bot + two benchmark series into a single array keyed by date
function mergeSeries(botArr, spyArr, qqqArr) {
  const map = {};
  for (const p of botArr) {
    map[p.date] = { date: p.date, bot: p.value };
  }
  for (const p of spyArr) {
    if (map[p.date]) map[p.date].spy = p.value;
    else map[p.date] = { date: p.date, spy: p.value };
  }
  for (const p of qqqArr) {
    if (map[p.date]) map[p.date].qqq = p.value;
    else map[p.date] = { date: p.date, qqq: p.value };
  }
  return Object.values(map).sort((a, b) => (a.date > b.date ? 1 : -1));
}

export default function BenchmarkChart() {
  const spy = useBenchmark("SPY");
  const qqq = useBenchmark("QQQ");

  const loading = spy.loading || qqq.loading;
  const error = spy.error || qqq.error;
  const noData = spy.data?.no_data || qqq.data?.no_data;

  if (loading) {
    return (
      <div className="flex justify-center items-center py-16">
        <span className="loading loading-spinner loading-lg text-primary" />
        <span className="ml-3 text-gray-500">Loading performance data…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-error max-w-xl mx-auto mt-8">
        <span>Failed to load chart: {error}</span>
      </div>
    );
  }

  if (noData || !spy.data || !qqq.data) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <p className="text-lg font-medium">No performance data yet</p>
        <p className="text-sm mt-1">
          Chart will appear once the bot completes its first rebalance.
        </p>
      </div>
    );
  }

  const chartData = mergeSeries(spy.data.bot, spy.data.benchmark, qqq.data.benchmark);

  return (
    <div>
      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartData} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />

          <XAxis
            dataKey="date"
            tick={{ fontSize: 12 }}
            tickFormatter={(d) => d.slice(5)}
            interval="preserveStartEnd"
          />

          <YAxis
            tickFormatter={(v) => `${((v - 1) * 100).toFixed(0)}%`}
            tick={{ fontSize: 12 }}
            width={55}
          />

          <Tooltip
            formatter={(value, name) => [formatPct(value), LABEL[name] ?? name]}
            labelFormatter={(label) => `Date: ${label}`}
          />

          <Legend formatter={(value) => LABEL[value] ?? value} />

          <Line
            type="monotone"
            dataKey="bot"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="spy"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={false}
            strokeDasharray="5 5"
            activeDot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="qqq"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
            strokeDasharray="3 3"
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>

      <p className="text-xs text-gray-400 mt-2 text-right">
        Indexed to 1.0 at first rebalance ({spy.data.first_rebalance_date}).
        Y-axis shows cumulative return (%).
      </p>
    </div>
  );
}
