import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/Import";
import Transactions from "./pages/Transactions";
import FiscalYears from "./pages/FiscalYears";
import Model721 from "./pages/Model721";

const links = [
  { to: "/", label: "Panel", end: true },
  { to: "/import", label: "Importar Excel" },
  { to: "/transactions", label: "Transacciones" },
  { to: "/fiscal", label: "Años fiscales" },
  { to: "/model721", label: "Modelo 721" },
];

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>Crypto-Trace</h1>
        <nav>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <p className="muted" style={{ marginTop: 40 }}>
          IRPF · FIFO · base del ahorro. Herramienta de apoyo, no asesoramiento fiscal.
        </p>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/fiscal" element={<FiscalYears />} />
          <Route path="/model721" element={<Model721 />} />
        </Routes>
      </main>
    </div>
  );
}
