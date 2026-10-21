import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { shortDate } from "../format";

const KIND_LABEL = {
  price_move: "Big move", drawdown: "Down from high", concentration: "Concentration",
  volatility: "Risk rising", news: "News",
};

export default function Alerts() {
  const [alerts, setAlerts] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = () => api("/alerts?limit=100").then(setAlerts).catch((e) => setMsg({ error: true, text: e.message }));
  useEffect(() => { load(); }, []);

  async function checkNow() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api("/alerts/check", { method: "POST" });
      setMsg({ text: r.new_alerts ? `${r.new_alerts} new alert${r.new_alerts > 1 ? "s" : ""}.` : "Nothing new right now." });
      await load();
    } catch (e) {
      setMsg({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function markRead() {
    await api("/alerts/read-all", { method: "POST" });
    load();
  }

  const unread = alerts?.filter((a) => !a.read).length ?? 0;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Alerts</h1>
          <p className="muted">
            Every weekday evening we check for big price moves, stocks far below their high, too much money in one place,
            a sudden rise in your portfolio's swings, and worrying news. Connect Telegram in <Link to="/settings">Settings</Link> to get them on your phone.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {unread > 0 && <button className="btn secondary" onClick={markRead}>Mark all as read</button>}
          <button className="btn" onClick={checkNow} disabled={busy}>{busy ? "Checking…" : "Check now"}</button>
        </div>
      </header>

      {msg && <div className={`notice ${msg.error ? "error" : "ok"}`} style={{ marginBottom: 16 }}>{msg.text}</div>}
      {alerts === null && !msg && <p className="spinner">Loading alerts…</p>}
      {alerts?.length === 0 && (
        <div className="empty">
          <h2>No alerts yet</h2>
          <p className="muted">That's good news. Press Check now to run the checks right away.</p>
        </div>
      )}

      <div className="alert-list">
        {alerts?.map((a) => (
          <article key={a.id} className={`alert ${a.severity} ${a.read ? "" : "unread"}`}>
            <span className="strip" aria-hidden="true" />
            <div>
              <p className="small muted">{KIND_LABEL[a.kind] ?? a.kind}{a.symbol ? ` · ${a.symbol}` : ""}</p>
              <h3>{a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a> : a.title}</h3>
              <p className="small muted" style={{ marginTop: 2 }}>{a.body}</p>
            </div>
            <div className="small muted" style={{ textAlign: "right" }}>
              {shortDate(a.created_at)}
              {a.sent_telegram && <div>Sent to Telegram</div>}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
