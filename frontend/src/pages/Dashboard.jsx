import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import { EmptyPortfolio } from "../components/Layout";
import { Heatmap, OutcomeChart, RideChart, RiskBars, SectorBars, VolChart } from "../components/Charts";
import Term from "../components/Term";
import { inr, num, pct, shortDate, signedInr, signedPct, tone } from "../format";

export default function Dashboard() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [empty, setEmpty] = useState(false);
  const [busy, setBusy] = useState(false);

  async function downloadExcel() {
    setBusy(true);
    try {
      await download("/portfolio/report.xlsx", "risk-report.xlsx");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    api("/portfolio/risk")
      .then(setReport)
      .catch((e) => (e.status === 404 ? setEmpty(true) : setError(e.message)));
  }, []);

  if (empty) return <EmptyPortfolio />;
  if (error) return <div className="notice error">{error}</div>;
  if (!report) return <p className="spinner">Loading prices and working out your risk…</p>;

  const m = report.metrics;
  const c = report.concentration;
  const riskHog = [...report.holdings]
    .filter((h) => h.risk_share != null)
    .sort((a, b) => b.risk_share - b.weight - (a.risk_share - a.weight))[0];

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Your portfolio, in plain words</h1>
          <p className="muted">
            Based on prices up to {shortDate(report.as_of)}. Risk numbers assume you held today's mix of stocks for
            the past {report.lookback_days} trading days.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn secondary" onClick={downloadExcel} disabled={busy}>
            {busy ? "Preparing…" : "Download Excel report"}
          </button>
          <Link to="/scenarios" className="btn secondary">Try a what-if</Link>
        </div>
      </header>

      {report.warnings.length > 0 && (
        <div className="notice" style={{ marginBottom: 24 }}>
          Some numbers are incomplete:
          <ul>{report.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}

      <section className="summary" aria-label="Summary">
        <div className="summary-grid">
          <div>
            <p className="line">Your portfolio is worth <strong>{inr(report.total_value)}</strong></p>
            <p className="line-note">
              You put in {inr(report.total_cost)}, so you're{" "}
              <span className={tone(report.total_pnl)}>{signedInr(report.total_pnl)} ({signedPct(report.total_pnl_pct)})</span>.
            </p>
          </div>
          {m && (
            <>
              <div>
                <p className="line">On a bad day, you could lose <strong className="loss">{inr(m.var_95_amount)}</strong> or more</p>
                <p className="line-note">
                  That's your <Term k="var">1-day Value at Risk</Term>: roughly 1 day in 20 is worse. When it is, the
                  average loss is {inr(m.cvar_95_amount)} (<Term k="cvar">expected shortfall</Term>).
                </p>
              </div>
              <div>
                <p className="line">In the last year it fell <strong className="loss">{pct(Math.abs(m.max_drawdown))}</strong> from a high</p>
                <p className="line-note">
                  That's the biggest <Term k="drawdown">drawdown</Term>: from {shortDate(m.drawdown_peak)} to{" "}
                  {shortDate(m.drawdown_trough)}.{" "}
                  {m.drawdown_recovered ? `It climbed back by ${shortDate(m.drawdown_recovered)}.` : "It hasn't fully climbed back yet."}
                </p>
              </div>
              {riskHog && (
                <div>
                  <p className="line">
                    {riskHog.symbol} is <strong>{pct(riskHog.weight, 0)}</strong> of your money but{" "}
                    <strong>{pct(riskHog.risk_share, 0)}</strong> of your risk
                  </p>
                  <p className="line-note">
                    It swings {pct(riskHog.annual_volatility, 0)} a year and moves with your other holdings, so it drives
                    more of your ups and downs than its size suggests.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      {m && (
        <section className="section">
          <div className="section-head">
            <h2>More numbers</h2>
            <p className="small muted">Hover or tap an underlined word to see what it means.</p>
          </div>
          <dl className="summary-grid" style={{ margin: 0 }}>
            <Stat label={<Term k="volatility">Yearly swing (volatility)</Term>}
              value={pct(m.annual_volatility)} note={`NIFTY 50: ${pct(m.market_annual_volatility)}`} />
            <Stat label={<Term k="beta">Beta vs NIFTY 50</Term>} value={num(m.beta)}
              note={m.beta == null ? "" : m.beta > 1 ? "You move more than the market." : "You move less than the market."} />
            <Stat label="Return over the past year" value={pct(m.annual_return)}
              note={`NIFTY 50: ${pct(m.market_annual_return)}`} />
            <Stat label={<Term k="sharpe">Sharpe ratio</Term>} value={num(m.sharpe)}
              note={`Compared with a ${pct(m.risk_free_rate)} safe return.`} />
            <Stat label={<Term k="effective">Spread like</Term>} value={`${num(c.effective_holdings)} equal stocks`}
              note={`You hold ${report.holdings.length}. Top 3 are ${pct(c.top3_weight, 0)} of your money.`} />
            <Stat label={<Term k="diversification">Diversification ratio</Term>} value={num(m.diversification_ratio)}
              note="1.0 means your stocks don't cancel each other's swings at all." />
          </dl>
        </section>
      )}

      {m && report.outlook && <Outlook o={report.outlook} history={report.history} />}

      {m && (
        <section className="section">
          <div className="section-head">
            <h2>The past year with today's mix</h2>
            <p className="small muted">What ₹100 would have become, compared with the NIFTY 50.</p>
          </div>
          <RideChart history={report.history} />
        </section>
      )}

      {m && (
        <section className="section two-col">
          <div>
            <div className="section-head"><h2>Where your risk comes from</h2></div>
            <RiskBars holdings={report.holdings} />
          </div>
          <div>
            <div className="section-head"><h2>Sectors</h2></div>
            <SectorBars sectors={c.sector_weights} />
            <div className="section-head" style={{ marginTop: 36 }}>
              <h2><Term k="correlation">Which stocks move together</Term></h2>
            </div>
            <Heatmap matrix={report.correlation_matrix} />
          </div>
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2>Holdings</h2>
          <Link to="/holdings" className="small">Edit holdings</Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th><th>Sector</th><th className="num">Value</th><th className="num">Weight</th>
                <th className="num">Profit/loss</th><th className="num">Today</th>
                <th className="num">Yearly swing</th><th className="num">Beta</th>
              </tr>
            </thead>
            <tbody>
              {report.holdings.map((h) => (
                <tr key={h.symbol}>
                  <td><strong>{h.symbol}</strong> <span className="muted small">{h.name !== h.symbol ? h.name : ""}</span></td>
                  <td>{h.sector}</td>
                  <td className="num">{inr(h.value)}</td>
                  <td className="num">{pct(h.weight)}</td>
                  <td className={`num ${tone(h.pnl)}`}>{signedPct(h.pnl_pct)}</td>
                  <td className={`num ${tone(h.day_change_pct)}`}>{signedPct(h.day_change_pct, 2)}</td>
                  <td className="num">{pct(h.annual_volatility)}</td>
                  <td className="num">{num(h.beta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Stat({ label, value, note }) {
  return (
    <div>
      <dt className="small muted">{label}</dt>
      <dd style={{ margin: "2px 0 0", font: "700 1.5rem var(--font-display)" }}>{value}</dd>
      {note && <dd className="small muted" style={{ margin: 0 }}>{note}</dd>}
    </div>
  );
}

function Outlook({ o, history }) {
  const v = o.volatility;
  const mo = o.month;
  const bt = o.var_backtest;
  return (
    <section className="section">
      <div className="section-head">
        <h2>Looking ahead</h2>
        <p className="small muted">Based on {o.days_used} trading days. Simulations, not predictions.</p>
      </div>
      <div className="two-col">
        <div className="stack">
          {v && (
            <p className="line" style={{ maxWidth: "38ch" }}>
              Right now your portfolio is swinging{" "}
              <strong className={v.level === "high" || v.level === "elevated" ? "loss" : ""}>{v.text}</strong>
            </p>
          )}
          {v && (
            <p className="line-note">
              <Term k="ewma">Recent volatility</Term> is {pct(v.now)} a year. Its usual level over the past year is {pct(v.typical)}.
            </p>
          )}
          <VolChart history={history} typical={v?.typical} />
        </div>
        <div className="stack">
          {mo && (
            <>
              <p className="line" style={{ maxWidth: "38ch" }}>
                In a bad month, you could be down <strong className="loss">{pct(Math.abs(mo.bad_month))}</strong>
              </p>
              <p className="line-note">
                That's about {inr(Math.abs(mo.bad_month_amount))}: only 1 in 20 of the {mo.paths.toLocaleString("en-IN")}{" "}
                <Term k="montecarlo">simulated months</Term> was worse. Chance of losing more than 10% in a month:{" "}
                {pct(mo.prob_loss_over_10)}.
              </p>
              <OutcomeChart histogram={mo.histogram} badMonth={mo.bad_month} />
            </>
          )}
          {bt && (
            <p className="line-note">
              <Term k="backtest">Checked on past data</Term>: the bad-day estimate was beaten on {bt.breaches} of {bt.days_tested}{" "}
              days ({bt.expected.toFixed(1)} expected). {bt.passed ? "That's within normal luck, so the estimate holds up." :
                "That's too far from expected, so treat the bad-day number with caution."}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
