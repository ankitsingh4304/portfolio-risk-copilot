import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import Alerts from "./pages/Alerts";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import Holdings from "./pages/Holdings";
import Login from "./pages/Login";
import Scenarios from "./pages/Scenarios";
import Settings from "./pages/Settings";
import "./styles.css";

function App() {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="ask" element={<Chat />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="holdings" element={<Holdings />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
