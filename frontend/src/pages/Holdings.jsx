import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { inr } from "../format";

// NSE's industry names, offered as suggestions when you edit a sector.
const SECTORS = [
  "Automobile and Auto Components", "Capital Goods", "Chemicals", "Construction", "Construction Materials",
  "Consumer Durables", "Consumer Services", "Diversified", "Fast Moving Consumer Goods", "Financial Services",
  "Healthcare", "Information Technology", "Media Entertainment & Publication", "Metals & Mining",
  "Oil Gas & Consumable Fuels", "Power", "Realty", "Services", "Telecommunication", "Textiles",
  "Index ETF", "Gold ETF", "Other",
];

export default function Holdings() {
  const [holdings, setHoldings] = useState(null);
  const [upload, setUpload] = useState(null);
  const [error, setError] = useState(null);
  const [replace, setReplace] = useState(true);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ symbol: "", quantity: "", avg_price: "" });
  const [editing, setEditing] = useState(null);
  const fileRef = useRef(null);

  const load = () => api("/portfolio/holdings").then(setHoldings).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function sendFile(file) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setUpload(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await api(`/portfolio/upload?replace=${replace}`, { method: "POST", form: fd });
      setUpload(res);
      setHoldings(res.holdings);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function add(e) {
    e.preventDefault();
    setError(null);
    try {
      await api("/portfolio/holdings", {
        method: "POST",
        body: { symbol: form.symbol, quantity: Number(form.quantity), avg_price: Number(form.avg_price) },
      });
      setForm({ symbol: "", quantity: "", avg_price: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function saveEdit(h) {
    try {
      await api(`/portfolio/holdings/${h.id}`, {
        method: "PUT",
        body: { symbol: h.symbol, quantity: Number(editing.quantity), avg_price: Number(editing.avg_price), sector: editing.sector },
      });
      setEditing(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(h) {
    if (!window.confirm(`Remove ${h.symbol} from your holdings?`)) return;
    await api(`/portfolio/holdings/${h.id}`, { method: "DELETE" }).catch((e) => setError(e.message));
    load();
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Holdings</h1>
          <p className="muted">
            Upload your broker's holdings file or PDF statement, or add stocks yourself. NSE symbols only for now.
            If a sector looks wrong, press Edit to change it.
          </p>
        </div>
        {holdings?.length > 0 && <Link to="/" className="btn secondary">See my risk</Link>}
      </header>

      <section className="two-col">
        <div className="stack">
          <h2>Upload a file</h2>
          <div
            className={`drop ${over ? "over" : ""}`}
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); sendFile(e.dataTransfer.files[0]); }}
            role="button" tabIndex={0} aria-label="Upload holdings file"
          >
            <p><strong>{busy ? "Reading your file…" : "Drop your file here, or click to choose"}</strong></p>
            <p className="small muted" style={{ marginTop: 4 }}>CSV, Excel or PDF statement, up to 5 MB</p>
            <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.pdf" hidden onChange={(e) => sendFile(e.target.files[0])} />
          </div>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "0.92rem" }}>
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} style={{ width: "auto" }} />
            Replace my current holdings (untick to add to them)
          </label>
          <details className="small muted">
            <summary style={{ cursor: "pointer" }}>Where do I get this file?</summary>
            <ul>
              <li><strong>Zerodha Kite:</strong> Portfolio → Holdings → Download (CSV).</li>
              <li><strong>Zerodha Console:</strong> Portfolio → Holdings → Download.</li>
              <li><strong>Groww:</strong> Stocks → Holdings → Download holdings statement.</li>
              <li><strong>PDF statement:</strong> tables are read directly. PDFs without a table are read by the AI, and every number it reads is checked against the PDF.</li>
              <li><strong>Any other:</strong> a CSV with columns <code>symbol, quantity, avg_price</code> (and optionally <code>sector</code>).</li>
            </ul>
          </details>
          {upload && (
            <div className={`notice ${upload.warnings.length ? "" : "ok"}`}>
              Read a {upload.detected_format} file and imported {upload.imported} stocks.
              {upload.warnings.length > 0 && <ul>{upload.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            </div>
          )}
        </div>

        <form className="stack" onSubmit={add}>
          <h2>Add one stock</h2>
          <label className="field">NSE symbol
            <input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} placeholder="INFY" required />
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <label className="field">Quantity
              <input inputMode="decimal" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required />
            </label>
            <label className="field">Average buy price (₹)
              <input inputMode="decimal" value={form.avg_price} onChange={(e) => setForm({ ...form, avg_price: e.target.value })} required />
            </label>
          </div>
          <button className="btn">Add stock</button>
        </form>
      </section>

      {error && <div className="notice error" style={{ marginTop: 24 }}>{error}</div>}
      <datalist id="sector-names">{SECTORS.map((x) => <option key={x} value={x} />)}</datalist>

      <section className="section">
        <div className="section-head"><h2>Your stocks</h2><span className="small muted">{holdings?.length ?? 0} stocks</span></div>
        {holdings?.length === 0 && <p className="muted">Nothing here yet.</p>}
        {holdings?.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Symbol</th><th>Name</th><th>Sector</th><th className="num">Quantity</th>
                  <th className="num">Avg. price</th><th className="num">Invested</th><th /></tr>
              </thead>
              <tbody>
                {holdings.map((h) => {
                  const isEditing = editing?.id === h.id;
                  return (
                    <tr key={h.id}>
                      <td><strong>{h.symbol}</strong></td>
                      <td>{h.name}</td>
                      <td>
                        {isEditing ? <input aria-label="Sector" list="sector-names" value={editing.sector}
                          style={{ width: 200 }} onChange={(e) => setEditing({ ...editing, sector: e.target.value })} /> : h.sector}
                      </td>
                      <td className="num">
                        {isEditing ? <input aria-label="Quantity" value={editing.quantity}
                          onChange={(e) => setEditing({ ...editing, quantity: e.target.value })} /> : h.quantity}
                      </td>
                      <td className="num">
                        {isEditing ? <input aria-label="Average price" value={editing.avg_price}
                          onChange={(e) => setEditing({ ...editing, avg_price: e.target.value })} /> : inr(h.avg_price)}
                      </td>
                      <td className="num">{inr(h.quantity * h.avg_price)}</td>
                      <td className="num">
                        {isEditing ? (
                          <>
                            <button className="btn quiet" onClick={() => saveEdit(h)}>Save</button>
                            <button className="btn quiet" onClick={() => setEditing(null)}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button className="btn quiet" onClick={() => setEditing({ id: h.id, quantity: h.quantity, avg_price: h.avg_price, sector: h.sector })}>Edit</button>
                            <button className="btn danger" onClick={() => remove(h)}>Remove</button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
