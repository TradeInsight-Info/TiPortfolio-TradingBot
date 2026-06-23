import { useState, useEffect } from "react";
import BenchmarkChart from "./components/BenchmarkChart";
import DeltaTable from "./components/DeltaTable";
import IntroSection from "./components/IntroSection";
import PerformanceMetrics from "./components/PerformanceMetrics";
import PositionSummary from "./components/PositionSummary";
import { useTheme } from "./hooks/useTheme";
import { StrategyProvider, useStrategy } from "./context/StrategyContext";

function AppContent() {
  useTheme(); // sync OS preference → html.dark class

  const [activeSection, setActiveSection] = useState("intro");
  const { strategies, strategyId, setStrategyId, loading: strategiesLoading, error: strategiesError } = useStrategy();

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
        {strategies.length > 1 && (
          <div className="flex flex-wrap gap-2 mb-6">
            {strategies.map((s) => (
              <button
                key={s.id}
                aria-pressed={strategyId === s.id}
                onClick={() => setStrategyId(s.id)}
                className={
                  strategyId === s.id
                    ? "font-semibold text-primary border border-primary rounded px-3 py-1"
                    : "text-foreground hover:text-primary transition-colors border border-border rounded px-3 py-1"
                }
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        {strategiesLoading ? null : strategies.length === 0 ? (
          <p className="text-muted-foreground py-8">
            {strategiesError ? `Could not load strategies: ${strategiesError}` : "No strategies available."}
          </p>
        ) : (
          <>
            <BenchmarkChart />
            <PerformanceMetrics />
          </>
        )}
      </section>

      <section id="trades" className="max-w-7xl mx-auto px-4 py-16">
        <h2 className="text-2xl font-bold mb-2">Trade Records</h2>
        <p className="text-muted-foreground mb-6">
          All rebalance decisions made by the algorithm, sorted by most recent
          first.
        </p>
        <PositionSummary />
        {!strategiesLoading && strategies.length === 0 ? (
          <p className="text-muted-foreground py-8">
            {strategiesError ? `Could not load strategies: ${strategiesError}` : "No strategies available."}
          </p>
        ) : (
          <DeltaTable />
        )}
      </section>

      <footer className="border-t border-border mt-16 px-6 py-8 text-sm text-muted-foreground">
        <p>
          Built by{" "}
          <a
            href="https://www.linkedin.com/in/vicky-chang-vc95/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground hover:text-primary transition-colors"
          >
            Vicky
          </a>{" "}
          &amp;{" "}
          <a
            href="https://github.com/tim-hub"
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground hover:text-primary transition-colors"
          >
            Tim
          </a>
        </p>
      </footer>
    </>
  );
}

function App() {
  return (
    <StrategyProvider>
      <AppContent />
    </StrategyProvider>
  );
}

export default App;
