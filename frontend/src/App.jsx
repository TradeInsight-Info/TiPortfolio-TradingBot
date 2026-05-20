import { useState, useEffect } from "react";
import BenchmarkChart from "./components/BenchmarkChart";
import DeltaTable from "./components/DeltaTable";
import IntroSection from "./components/IntroSection";

function App() {
  const [ticker, setTicker] = useState("SPY");
  const [activeSection, setActiveSection] = useState("intro");

  useEffect(() => {
    const sections = ["intro", "trades", "performance"];
    const observers = sections.map((id) => {
      const el = document.getElementById(id);
      if (!el) return null;
      const obs = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActiveSection(id);
        },
        { rootMargin: "-40% 0px -55% 0px" }
      );
      obs.observe(el);
      return obs;
    });
    return () => observers.forEach((obs) => obs?.disconnect());
  }, []);

  const navClass = (id) =>
    activeSection === id
      ? "font-semibold text-primary"
      : "text-base-content hover:text-primary transition-colors";

  return (
    <>
      <nav className="navbar bg-base-100 shadow px-6 gap-4 sticky top-0 z-50">
        <span className="text-xl font-bold mr-6">TiPortfolio Demo</span>
        <a href="#intro" className={navClass("intro")}>
          About
        </a>
        <a href="#trades" className={navClass("trades")}>
          Trades
        </a>
        <a href="#performance" className={navClass("performance")}>
          Performance
        </a>
      </nav>

      <section
        id="intro"
        className="min-h-screen flex items-center justify-center px-4 py-16"
      >
        <IntroSection />
      </section>

      <section id="trades" className="max-w-7xl mx-auto px-4 py-16">
        <h2 className="text-2xl font-bold mb-2">Trade Records</h2>
        <p className="text-gray-500 mb-6">
          All rebalance decisions made by the algorithm, sorted by most recent
          first.
        </p>
        <DeltaTable />
      </section>

      <section id="performance" className="max-w-5xl mx-auto px-4 py-16">
        <h2 className="text-2xl font-bold mb-2">Performance vs Market</h2>
        <p className="text-gray-500 mb-6">
          Cumulative return of the bot vs. market benchmarks, indexed from the
          first rebalance date.
        </p>
        <BenchmarkChart ticker={ticker} onTickerChange={setTicker} />
      </section>
    </>
  );
}

export default App;
