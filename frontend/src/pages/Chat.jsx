import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const SUGGESTIONS = [
  "Give me a short weekly brief on my portfolio",
  "How risky is my portfolio?",
  "What if IT stocks fall 15%?",
  "What's the chance I lose 10% next month?",
  "Replay the COVID crash on my portfolio",
  "Which stock causes the most risk?",
  "Which of my stocks move together?",
];

const TOOL_NAMES = {
  get_portfolio_overview: "read holdings",
  get_risk_metrics: "risk numbers",
  get_risk_outlook: "forecast",
  get_stock_details: "stock details",
  run_sector_scenario: "sector what-if",
  run_market_scenario: "market what-if",
  run_historical_scenario: "past crash replay",
  run_custom_scenario: "custom what-if",
  get_correlated_pairs: "correlations",
  get_stock_news: "news",
};

// Which AI model wrote the answer (the backend tries the main one, then the backup).
const MODEL_NAMES = { gemini: "Gemini", groq: "Groq" };

/** Turns **bold** into <strong>, keeps everything else as plain text. */
function Rich({ text }) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function send(text) {
    const q = text.trim();
    if (!q || busy) return;
    const history = messages.map(({ role, content }) => ({ role, content })).slice(-10);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy(true);
    try {
      const res = await api("/chat", { method: "POST", body: { message: q, history } });
      setMessages((m) => [...m, { role: "assistant", content: res.answer, tools: res.tool_calls, mode: res.mode }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: e.message, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Ask about your portfolio</h1>
          <p className="muted">
            The assistant looks up your real numbers before answering. It explains risk. It won't tell you what to buy or sell.
          </p>
        </div>
      </header>

      <div className="chat">
        <div className="chat-log" ref={logRef} aria-live="polite">
          {messages.length === 0 && (
            <div>
              <p className="muted" style={{ marginBottom: 12 }}>Try one of these:</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className={`body ${m.error ? "loss" : ""}`}><Rich text={m.content} /></div>
              {m.tools?.length > 0 && (
                <div className="tools-used">
                  Checked:
                  {[...new Set(m.tools.map((t) => t.tool))].map((t) => (
                    <span key={t} className="chip" title={JSON.stringify(m.tools.find((x) => x.tool === t).args)}>
                      {TOOL_NAMES[t] ?? t}
                    </span>
                  ))}
                  {m.mode === "offline" && <span>· basic mode (AI not available)</span>}
                  {MODEL_NAMES[m.mode] && <span>· answered by {MODEL_NAMES[m.mode]}</span>}
                </div>
              )}
            </div>
          ))}
          {busy && <p className="typing">Looking up your numbers…</p>}
        </div>

        <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question about your portfolio"
            aria-label="Your question" maxLength={2000} />
          <button className="btn" disabled={busy || !input.trim()}>Ask</button>
        </form>
      </div>
    </>
  );
}
