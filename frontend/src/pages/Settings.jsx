import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Settings() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [chatId, setChatId] = useState(user?.telegram_chat_id ?? "");
  const [msg, setMsg] = useState(null);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (user?.role === "admin") api("/admin/stats").then(setStats).catch(() => {});
  }, [user]);

  async function save(e) {
    e.preventDefault();
    try {
      const u = await api("/auth/me", { method: "PATCH", body: { name, telegram_chat_id: chatId } });
      setUser(u);
      setMsg({ text: "Settings saved." });
    } catch (err) {
      setMsg({ error: true, text: err.message });
    }
  }

  async function testTelegram() {
    try {
      await api("/alerts/test-telegram", { method: "POST" });
      setMsg({ text: "Test message sent. Check Telegram." });
    } catch (err) {
      setMsg({ error: true, text: err.message });
    }
  }

  return (
    <>
      <header className="page-head"><h1>Settings</h1></header>

      <form className="stack" onSubmit={save} style={{ maxWidth: 520 }}>
        <label className="field">Your name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </label>

        <div className="stack" style={{ "--stack": "8px" }}>
          <h2>Telegram alerts</h2>
          <p className="small muted">Get alerts on your phone. It takes about a minute:</p>
          <ol className="small" style={{ margin: 0, paddingLeft: 20 }}>
            <li>Open the bot set up for this app in Telegram and press <strong>Start</strong>.</li>
            <li>Message <strong>@userinfobot</strong> to find your chat ID (a number).</li>
            <li>Paste it below, save, then send a test message.</li>
          </ol>
          <label className="field">Telegram chat ID
            <input value={chatId} onChange={(e) => setChatId(e.target.value)} inputMode="numeric" placeholder="123456789" />
          </label>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn">Save settings</button>
          <button type="button" className="btn secondary" onClick={testTelegram} disabled={!user?.telegram_chat_id}>
            Send a test message
          </button>
        </div>
        {msg && <div className={`notice ${msg.error ? "error" : "ok"}`}>{msg.text}</div>}
      </form>

      {stats && (
        <section className="section" style={{ maxWidth: 520 }}>
          <div className="section-head"><h2>App usage</h2><span className="small muted">Visible to admins only</span></div>
          <table>
            <tbody>
              <tr><td>People signed up</td><td className="num">{stats.users}</td></tr>
              <tr><td>People with a portfolio</td><td className="num">{stats.users_with_portfolio}</td></tr>
              <tr><td>New this week</td><td className="num">{stats.new_users_7d}</td></tr>
              <tr><td>Stocks tracked</td><td className="num">{stats.holdings}</td></tr>
              <tr><td>Alerts created</td><td className="num">{stats.alerts_total}</td></tr>
              <tr><td>Alerts sent to Telegram</td><td className="num">{stats.alerts_sent_telegram}</td></tr>
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
