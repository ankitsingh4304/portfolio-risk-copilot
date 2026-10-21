import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="var(--accent)" />
      <path d="M5 22l6-6 5 4 11-11" stroke="var(--accent-ink)" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const [unread, setUnread] = useState(0);
  const location = useLocation();

  useEffect(() => {
    api("/alerts?limit=100")
      .then((a) => setUnread(a.filter((x) => !x.read).length))
      .catch(() => {});
  }, [location.pathname]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <Logo />
          <span>Risk Copilot</span>
        </NavLink>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/scenarios">What if?</NavLink>
          <NavLink to="/ask">Ask</NavLink>
          <NavLink to="/alerts">
            Alerts {unread > 0 && <span className="badge" aria-label={`${unread} unread`}>{unread}</span>}
          </NavLink>
          <NavLink to="/holdings">Holdings</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="muted">{user?.email}</div>
          <button className="btn quiet" onClick={logout}>Log out</button>
        </div>
      </aside>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

export function EmptyPortfolio() {
  return (
    <div className="empty">
      <h2>Add your stocks to get started</h2>
      <p className="muted">
        Upload the holdings file from Zerodha or Groww, or add stocks one by one. Your risk report appears here right after.
      </p>
      <div className="actions">
        <NavLink to="/holdings" className="btn">Upload holdings</NavLink>
      </div>
    </div>
  );
}
