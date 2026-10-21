import { useState } from "react";
import { Logo } from "../components/Layout";
import { useAuth } from "../auth";

export default function Login() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await signup(email, password, name);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-pitch">
        <div style={{ display: "flex", alignItems: "center", gap: 10, font: "700 1.15rem var(--font-display)" }}>
          <Logo /> Risk Copilot
        </div>
        <p className="pitch">See how risky your stocks are, explained in plain words.</p>
        <ul className="muted" style={{ margin: 0, paddingLeft: 20, maxWidth: "46ch" }}>
          <li>How much you could lose on a bad day</li>
          <li>Which stock is quietly causing most of your risk</li>
          <li>What happens if IT falls 15%, or the 2020 crash repeats</li>
          <li>Ask questions and get answers based on your real numbers</li>
        </ul>
      </section>

      <section className="auth-form">
        <form onSubmit={submit} aria-label={mode === "login" ? "Log in" : "Create account"}>
          <h1 style={{ fontSize: "1.6rem" }}>{mode === "login" ? "Log in" : "Create your account"}</h1>
          {mode === "signup" && (
            <label className="field">Name
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
          )}
          <label className="field">Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
          </label>
          <label className="field">Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={mode === "signup" ? 8 : undefined}
              autoComplete={mode === "login" ? "current-password" : "new-password"} required />
          </label>
          {mode === "signup" && <p className="small muted" style={{ marginTop: -6 }}>At least 8 characters.</p>}
          {error && <div className="notice error">{error}</div>}
          <button className="btn" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}</button>
          <p className="small muted">
            {mode === "login" ? "New here? " : "Already have an account? "}
            <button type="button" className="btn quiet" style={{ color: "var(--accent)", padding: 0 }}
              onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}>
              {mode === "login" ? "Create an account" : "Log in"}
            </button>
          </p>
        </form>
      </section>
    </div>
  );
}
