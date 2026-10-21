import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyPortfolio } from "../components/Layout";
import { inr, signedInr, signedPct, tone } from "../format";

const KINDS = [
  ["sector", "A sector falls"],
  ["market", "The market falls"],
  ["historical", "A past crash"],
  ["custom", "My own moves"],
];

export default function Scenarios() {
  const [holdings, setHoldings] = useState(null);
  const [events, setEvents] = useState([]);
  const [kind, setKind] = useState("sector");
  const [sector, setSector] = useState("");
  const [drop, setDrop] = useState(15);
  const [event, setEvent] = useState("covid_2020");
  const [custom, setCustom] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/portfolio/holdings").then((h) => {
      setHoldings(h);
      if (h.length) setSector(mostCommonSector(h));
    }).catch((e) => setError(e.message));
    api("/scenarios/events").then(setEvents).catch(() => {});
  }, []);

  const sectors = useMemo(() => [...new Set((holdings ?? []).map((h) => h.sector))].sort(), [holdings]);

  if (holdings && holdings.length === 0) return <EmptyPortfolio />;

  async function run(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let res;
      if (kind === "sector") res = await api("/scenarios/sector", { method: "POST", body: { sector, drop_pct: Number(drop) } });
      if (kind === "market") res = await api("/scenarios/market", { method: "POST", body: { drop_pct: Number(drop) } });
      if (kind === "historical") res = await api("/scenarios/historical", { method: "POST", body: { event } });
      if (kind === "custom") {
        const shocks = Object.fromEntries(Object.entries(custom).filter(([, v]) => v !== "" && !Number.isNaN(Number(v))).map(([k, v]) => [k, Number(v)]));
        if (!Object.keys(shocks).length) throw new Error("Enter a move for at least one stock.");
        res = await api("/scenarios/custom", { method: "POST", body: { shocks } });
      }
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>What if?</h1>
          <p className="muted">Pick something that could happen. See roughly how much your portfolio would gain or lose.</p>
        </div>
      </header>

      <div className="scenario-layout">
        <form className="panel stack" onSubmit={run} style={{ "--stack": "16px" }}>
          <div className="segmented" role="group" aria-label="Scenario type">
            {KINDS.map(([k, label]) => (
              <button type="button" key={k} aria-pressed={kind === k} onClick={() => { setKind(k); setResult(null); }}>
                {label}
              </button>
            ))}
          </div>

          {kind === "sector" && (
            <>
              <label className="field">Sector
                <select value={sector} onChange={(e) => setSector(e.target.value)}>
                  {sectors.map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
              <DropInput value={drop} onChange={setDrop} />
              <p className="small muted">Other stocks that usually move with this sector are pulled down too, based on the past year.</p>
            </>
          )}

          {kind === "market" && (
            <>
              <DropInput value={drop} onChange={setDrop} label="NIFTY 50 falls by" />
              <p className="small muted">Each stock falls by its beta times this. A beta-1.3 stock falls 13% when NIFTY falls 10%.</p>
            </>
          )}

          {kind === "historical" && (
            <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="stack">
              <legend className="small muted" style={{ marginBottom: 8 }}>Replay a real market fall on what you hold today</legend>
              {events.map((ev) => (
                <label key={ev.key} style={{ display: "flex", gap: 10, alignItems: "flex-start", cursor: "pointer" }}>
                  <input type="radio" name="event" value={ev.key} checked={event === ev.key}
                    onChange={() => setEvent(ev.key)} style={{ width: "auto", marginTop: 5 }} />
                  <span><strong>{ev.name}</strong><br /><span className="small muted">{ev.description}</span></span>
                </label>
              ))}
            </fieldset>
          )}

          {kind === "custom" && (
            <div className="stack" style={{ "--stack": "8px" }}>
              <p className="small muted">Type a % move for any stock. Use a minus sign for a fall, like −20.</p>
              {(holdings ?? []).map((h) => (
                <label key={h.symbol} style={{ display: "grid", gridTemplateColumns: "1fr 90px", alignItems: "center", gap: 8 }}>
                  <span>{h.symbol}</span>
                  <input inputMode="decimal" placeholder="0" value={custom[h.symbol] ?? ""}
                    onChange={(e) => setCustom({ ...custom, [h.symbol]: e.target.value })} aria-label={`${h.symbol} move in percent`} />
                </label>
              ))}
            </div>
          )}

          <button className="btn" disabled={busy || !holdings}>{busy ? "Working it out…" : "See the impact"}</button>
          {error && <div className="notice error">{error}</div>}
        </form>

        <div aria-live="polite">
          {result ? <Result r={result} /> : (
            <p className="muted" style={{ paddingTop: 8 }}>Your result shows up here.</p>
          )}
        </div>
      </div>
    </>
  );
}

function DropInput({ value, onChange, label = "Falls by" }) {
  return (
    <label className="field">{label}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <input type="range" min="1" max="60" value={value} onChange={(e) => onChange(e.target.value)} aria-label={`${label} percent`} />
        <strong style={{ minWidth: 48, font: "700 1.3rem var(--font-display)" }}>{value}%</strong>
      </div>
    </label>
  );
}

function Result({ r }) {
  const affected = r.rows.filter((x) => x.impact !== 0);
  const maxAbs = Math.max(...affected.map((x) => Math.abs(x.move_pct)), 1);
  const losing = r.total_impact < 0;
  return (
    <div className="stack" style={{ "--stack": "20px" }}>
      <p className="muted">{r.name}</p>
      <p className="result-sentence">
        You would {losing ? "lose" : "gain"} about{" "}
        <strong className={tone(r.total_impact)}>{inr(Math.abs(r.total_impact))}</strong>{" "}
        ({signedPct(r.total_impact_pct)}). Your {inr(r.current_value)} would become {inr(r.new_value)}.
      </p>

      <div>
        {affected.map((x) => (
          <div className="impact-row" key={x.symbol}>
            <strong>{x.symbol}</strong>
            <div className="impact-track" aria-hidden="true">
              <span style={{
                background: x.move_pct < 0 ? "var(--loss)" : "var(--gain)",
                width: `${(Math.abs(x.move_pct) / maxAbs) * 50}%`,
                ...(x.move_pct < 0 ? { right: "50%" } : { left: "50%" }),
              }} />
            </div>
            <span className={`num ${tone(x.impact)}`} style={{ textAlign: "right" }}>{signedInr(x.impact)}</span>
            <span className="method">{signedPct(x.move_pct)} · {x.method}</span>
          </div>
        ))}
      </div>

      <div className="notice">
        {r.notes.map((n) => <p key={n}>{n}</p>)}
        <p style={{ marginTop: 6 }}>These are estimates from past prices, not predictions.</p>
      </div>
    </div>
  );
}

function mostCommonSector(holdings) {
  const counts = {};
  holdings.forEach((h) => { counts[h.sector] = (counts[h.sector] || 0) + 1; });
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
}
