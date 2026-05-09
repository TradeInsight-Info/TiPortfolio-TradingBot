import { useState } from "react";
import BenchmarkChart from "../components/BenchmarkChart";

export default function BenchmarkPage() {
  // Ticker state lifted here so both the selector and chart share the same value
  const [ticker, setTicker] = useState("SPY");

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-2">Performance</h1>
      <p className="text-gray-500 mb-6">
        Cumulative return of the bot vs. a market benchmark, indexed from the
        first rebalance date.
      </p>

      <BenchmarkChart ticker={ticker} onTickerChange={setTicker} />
    </main>
  );
}