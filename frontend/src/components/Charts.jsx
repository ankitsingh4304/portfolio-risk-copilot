import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { pct, shortDate } from "../format";
import Term from "./Term";

const axis = { stroke: "var(--muted)", fontSize: 12, tickLine: false, axisLine: false };
const tooltipStyle = {
  contentStyle: { background: "var(--surface)", border: "1px solid var(--rule-strong)", borderRadius: 6, fontSize: 13 },
  labelStyle: { color: "var(--muted)" },
};
const monthTick = (d) => new Date(d).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });

/** Growth of ₹100 for the portfolio vs NIFTY, with the drawdown underneath. */
export function RideChart({ history }) {
  return (
    <div>
      <div style={{ height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={history} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
            <CartesianGrid stroke="var(--rule)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={monthTick} minTickGap={40} {...axis} />
            <YAxis domain={["auto", "auto"]} {...axis} width={48} />
            <Tooltip {...tooltipStyle} labelFormatter={shortDate}
              formatter={(v, name) => [`₹${v.toFixed(1)}`, name]} />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 13 }} />
            <Line type="monotone" dataKey="portfolio" name="Your portfolio" stroke="var(--accent)" strokeWidth={2.2} dot={false} />
            <Line type="monotone" dataKey="market" name="NIFTY 50" stroke="var(--chart-market)" strokeWidth={1.5} dot={false} strokeDasharray="4 3" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="small muted" style={{ margin: "14px 0 4px" }}>
        <Term k="drawdown">Drawdown</Term>: how far below its last high your portfolio was on each day
      </p>
      <div style={{ height: 110 }}>
        <ResponsiveContainer>
          <AreaChart data={history} margin={{ top: 4, right: 8, left: -4, bottom: 0 }}>
            <CartesianGrid stroke="var(--rule)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={monthTick} minTickGap={40} {...axis} />
            <YAxis {...axis} width={48} tickFormatter={(v) => `${v}%`} domain={["dataMin", 0]} allowDecimals={false} />
            <Tooltip {...tooltipStyle} labelFormatter={shortDate} formatter={(v) => [`${v}%`, "Below last high"]} />
            <Area type="monotone" dataKey="drawdown" stroke="var(--loss)" fill="var(--loss-soft)" strokeWidth={1.5} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** For each stock: share of money vs share of risk. */
export function RiskBars({ holdings }) {
  const rows = holdings.filter((h) => h.risk_share != null).sort((a, b) => b.risk_share - a.risk_share);
  const max = Math.max(...rows.map((h) => Math.max(h.weight, h.risk_share)), 0.01);
  return (
    <div>
      <div className="legend" style={{ marginBottom: 14 }}>
        <span><i style={{ background: "var(--chart-market)" }} />Share of your money</span>
        <span><i style={{ background: "var(--accent)" }} /><Term k="risk_share">Share of your risk</Term></span>
        <span><i style={{ background: "var(--loss)" }} />Risk share much bigger than money share</span>
      </div>
      <div className="risk-rows">
        {rows.map((h) => {
          const over = h.risk_share > h.weight * 1.25 && h.risk_share - h.weight > 0.02;
          return (
            <div className="risk-row" key={h.symbol}>
              <span className="sym">{h.symbol}</span>
              <div className="bars" aria-hidden="true">
                <div className="bar money"><span style={{ width: `${(h.weight / max) * 100}%` }} /></div>
                <div className={`bar risk ${over ? "over" : ""}`}><span style={{ width: `${(Math.max(h.risk_share, 0) / max) * 100}%` }} /></div>
              </div>
              <span className="vals"><span>{pct(h.weight)} of money</span><span>{pct(h.risk_share)} of risk</span></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SectorBars({ sectors }) {
  const entries = Object.entries(sectors);
  return (
    <div className="risk-rows">
      {entries.map(([name, w]) => (
        <div className="sector-row" key={name}>
          <span>{name}</span>
          <div className="bar money"><span style={{ width: `${w * 100}%`, background: "var(--ink)" }} /></div>
          <span className="vals">{pct(w, 0)}</span>
        </div>
      ))}
    </div>
  );
}

export function Heatmap({ matrix }) {
  const { symbols, values } = matrix;
  const n = symbols.length;
  const color = (v) => {
    const strength = Math.round(Math.min(Math.abs(v), 1) * 85);
    const base = v >= 0 ? "var(--accent)" : "var(--loss)";
    return `color-mix(in srgb, ${base} ${strength}%, var(--surface))`;
  };
  return (
    <div className="table-wrap">
      <div className="heatmap" style={{ gridTemplateColumns: `84px repeat(${n}, minmax(28px, 1fr))`, minWidth: 84 + n * 30 }}
        role="table" aria-label="Correlation between your stocks">
        <span />
        {symbols.map((s) => <span key={s} className="lab collab" title={s}>{s}</span>)}
        {values.map((row, i) => [
          <span key={`l${i}`} className="lab" title={symbols[i]}>{symbols[i]}</span>,
          ...row.map((v, j) => (
            <span key={`${i}-${j}`} className="cell" title={`${symbols[i]} & ${symbols[j]}: ${v.toFixed(2)}`}
              style={{ background: color(v), color: Math.abs(v) > 0.55 ? "var(--accent-ink)" : "var(--ink)" }}>
              {i === j ? "" : v.toFixed(1)}
            </span>
          )),
        ])}
      </div>
    </div>
  );
}

/** EWMA volatility over time, with the usual level as a reference line. */
export function VolChart({ history, typical }) {
  const data = history.filter((h) => h.ewma_vol != null);
  return (
    <div style={{ height: 180 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
          <CartesianGrid stroke="var(--rule)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={monthTick} minTickGap={40} {...axis} />
          <YAxis {...axis} width={48} tickFormatter={(v) => `${v}%`} domain={[0, "auto"]} />
          <Tooltip {...tooltipStyle} labelFormatter={shortDate} formatter={(v) => [`${v}% a year`, "Volatility (EWMA)"]} />
          {typical != null && (
            <ReferenceLine y={+(typical * 100).toFixed(1)} stroke="var(--chart-market)" strokeDasharray="4 3"
              label={{ value: "usual", position: "insideTopRight", fill: "var(--muted)", fontSize: 12 }} />
          )}
          <Line type="monotone" dataKey="ewma_vol" stroke="var(--accent)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Histogram of 10,000 simulated next-month returns. Loss bars red, gain bars green. */
export function OutcomeChart({ histogram, badMonth }) {
  const data = histogram.map((b) => ({ mid: (b.from_pct + b.to_pct) / 2, count: b.count, from: b.from_pct, to: b.to_pct }));
  return (
    <div style={{ height: 200 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }} barCategoryGap={1}>
          <CartesianGrid stroke="var(--rule)" vertical={false} />
          <XAxis dataKey="mid" {...axis} tickFormatter={(v) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`} minTickGap={24} />
          <YAxis {...axis} width={48} />
          <Tooltip {...tooltipStyle} labelFormatter={(_, p) => (p?.[0] ? `${p[0].payload.from.toFixed(1)}% to ${p[0].payload.to.toFixed(1)}%` : "")}
            formatter={(v) => [`${v.toLocaleString("en-IN")} of 10,000 months`, "Simulated"]} />
          <Bar dataKey="count" isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.mid} fill={d.to <= badMonth * 100 ? "var(--loss)" : d.mid < 0 ? "color-mix(in srgb, var(--loss) 45%, var(--surface))" : "color-mix(in srgb, var(--gain) 55%, var(--surface))"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
