// A finance word that explains itself on hover or keyboard focus.
export const GLOSSARY = {
  volatility:
    "How much your portfolio's value swings up and down. 20% yearly volatility means a normal year can be about 20% above or below average.",
  drawdown: "The biggest fall from a high point to a later low point. Example: ₹100 → ₹70 is a 30% drawdown.",
  var: "Value at Risk (95%). On 19 out of 20 days, your loss should be smaller than this. On the worst 1 in 20 days, it can be bigger.",
  cvar: "Expected shortfall: the average loss on those worst 1-in-20 days. It tells you how bad bad days usually are.",
  beta: "How much you move when the market moves. Beta 1.2 means: NIFTY falls 1%, you tend to fall about 1.2%.",
  sharpe: "Return per unit of risk, above what a safe government bond pays. Above 1 is good. Below 0 means a bond would have done better.",
  correlation: "Do two stocks move together? +1 = always together. 0 = unrelated. Stocks that move together don't protect each other.",
  diversification:
    "Diversification ratio: how much your stocks cancel out each other's swings. 1.0 = no help at all. Higher is better.",
  effective: "Effective number of stocks. 10 equal holdings = 10. One huge holding plus nine tiny ones ≈ close to 1.",
  ewma:
    "EWMA volatility: a volatility estimate that gives recent days more weight, so it reacts fast when markets get jumpy. Banks use the same method (RiskMetrics).",
  montecarlo:
    "Monte Carlo: we build 10,000 possible next months from random real past days, rescaled to today's volatility, and look at the spread of outcomes.",
  backtest:
    "Backtest: we checked our bad-day estimate on each day of the past year, using only data from before that day, and counted how often the real loss was bigger. About 1 in 20 is right.",
  risk_share:
    "Share of risk: how much of your portfolio's ups and downs comes from this stock. Volatile stocks that move with your other big holdings take a bigger share.",
};

export default function Term({ k, children }) {
  return (
    <span className="term" tabIndex={0}>
      {children}
      <span className="tip" role="tooltip">
        {GLOSSARY[k]}
      </span>
    </span>
  );
}
