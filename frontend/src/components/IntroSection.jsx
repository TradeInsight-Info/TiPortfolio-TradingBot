export default function IntroSection() {
  return (
    <div className="text-center max-w-2xl px-4">
      <h1 className="text-5xl font-bold mb-4">TiPortfolio Demo</h1>
      <p className="text-xl text-muted-foreground mb-6">
        Can an ETF-based portfolio optimisation strategy beat the market?
      </p>
      <p className="text-base text-muted-foreground mb-10 leading-relaxed">
        This is a live paper-trading bot built on top of the TiPortfolio
        library that rebalances based on market volatility signals. It holds
        a basket of ETFs, rebalances when volatility signals a change, and
        records every trade. Currently running on a paper trading account —
        we plan to switch to live real-money trading within 3 to 12 months.
        Results are shown below.
      </p>
      <div className="flex gap-4 justify-center flex-wrap">
        <a
          href="https://github.com/TradeInsight-Info/TiPortfolio-TradingBot"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center justify-center rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          View bot on GitHub
        </a>
        <a
          href="https://github.com/TradeInsight-Info/TiPortfolio"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center justify-center rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground transition-colors"
        >
          TiPortfolio library
        </a>
      </div>
    </div>
  );
}
