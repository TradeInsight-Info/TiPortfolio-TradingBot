export default function IntroSection() {
  return (
    <div className="text-center max-w-2xl px-4">
      <h1 className="text-5xl font-bold mb-4">TiPortfolio Demo</h1>
      <p className="text-xl text-gray-500 mb-6">
        Can an ETF-based portfolio optimisation strategy beat the market?
      </p>
      <p className="text-base text-gray-600 mb-10 leading-relaxed">
        This is a live paper-trading bot that runs weekly rebalances driven by
        the TiPortfolio optimisation library. It holds a basket of ETFs,
        rebalances when the algorithm signals a change, and records every trade.
        Results are shown below.
      </p>
      <div className="flex gap-4 justify-center flex-wrap">
        <a
          href="https://github.com/TradeInsight-Info/TiPortfolio-TradingBot"
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary"
        >
          View bot on GitHub
        </a>
        <a
          href="https://github.com/TradeInsight-Info/TiPortfolio"
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-outline"
        >
          TiPortfolio library
        </a>
      </div>
    </div>
  );
}
