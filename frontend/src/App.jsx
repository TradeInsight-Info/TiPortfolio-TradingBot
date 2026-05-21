import { useState, useEffect } from "react";
import BenchmarkChart from "./components/BenchmarkChart";
import DeltaTable from "./components/DeltaTable";
import IntroSection from "./components/IntroSection";
import PerformanceMetrics from "./components/PerformanceMetrics";
import { useTheme } from "./hooks/useTheme";

function App() {
  useTheme(); // sync OS preference → html.dark class

  const [activeSection, setActiveSection] = useState("intro");

  useEffect(() => {
    const sections = ["intro", "performance", "trades"];
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
      : "text-foreground hover:text-primary transition-colors";

  return (
    <>
      <nav className="flex items-center bg-card border-b border-border shadow-sm px-6 gap-4 sticky top-0 z-50 h-16">
        <a href="#intro" className="flex items-center gap-2 mr-6">
          <img src="/logo.svg" alt="" className="h-8 w-8 rounded-md" aria-hidden="true" />
          <span className="text-lg font-bold">TiPortfolio</span>
        </a>
        <a href="#intro" className={navClass("intro")}>
          About
        </a>
        <a href="#performance" className={navClass("performance")}>
          Performance
        </a>
        <a href="#trades" className={navClass("trades")}>
          Trades
        </a>
      </nav>

      <section
        id="intro"
        className="min-h-screen flex items-center justify-center px-4 py-16"
      >
        <IntroSection />
      </section>

      <section id="performance" className="max-w-7xl mx-auto px-4 py-16">
        <h2 className="text-2xl font-bold mb-2">Performance vs Market</h2>
        <p className="text-muted-foreground mb-6">
          Cumulative return of the bot vs. market benchmarks, indexed from the
          first rebalance date.
        </p>
        <BenchmarkChart />
        <PerformanceMetrics />
      </section>

      <section id="trades" className="max-w-7xl mx-auto px-4 py-16">
        <h2 className="text-2xl font-bold mb-2">Trade Records</h2>
        <p className="text-muted-foreground mb-6">
          All rebalance decisions made by the algorithm, sorted by most recent
          first.
        </p>
        <DeltaTable />
      </section>
    </>
  );
}

export default App;
