import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/Import";
import Transactions from "./pages/Transactions";
import FiscalYears from "./pages/FiscalYears";
import Model721 from "./pages/Model721";
import Reviews from "./pages/Reviews";
import Taxpayers from "./pages/Taxpayers";
import { buildTaxpayerQuery, useTaxpayers } from "./TaxpayerContext";

const links = [
  { to: "/", label: "Panel", end: true },
  { to: "/import", label: "Importar Excel" },
  { to: "/transactions", label: "Transacciones" },
  { to: "/reviews", label: "Revisar" },
  { to: "/fiscal", label: "Años fiscales" },
  { to: "/model721", label: "Modelo 721" },
  { to: "/taxpayers", label: "Contribuyentes" },
];

function TaxpayerSelector() {
  const { taxpayers, selectedIds, isJoint, selectSingle, toggleJoint, toggleSelection } =
    useTaxpayers();

  if (taxpayers.length === 0) {
    return (
      <div className="card" style={{ marginTop: 20 }}>
        <p className="muted">No hay contribuyentes. Crea uno primero.</p>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="muted" style={{ marginBottom: 8 }}>Contribuyente activo</div>
      {!isJoint ? (
        <select
          value={selectedIds[0] ?? ""}
          onChange={(e) => selectSingle(Number(e.target.value))}
          style={{ width: "100%" }}
        >
          {taxpayers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} {t.tax_id ? `(${t.tax_id})` : ""}
            </option>
          ))}
        </select>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {taxpayers.map((t) => (
            <label key={t.id} className="muted" style={{ cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={selectedIds.includes(t.id)}
                onChange={() => toggleSelection(t.id)}
              />{" "}
              {t.name} {t.tax_id ? `(${t.tax_id})` : ""}
            </label>
          ))}
        </div>
      )}
      <label className="muted" style={{ display: "block", marginTop: 8, cursor: "pointer" }}>
        <input type="checkbox" checked={isJoint} onChange={toggleJoint} /> Declaración conjunta
      </label>
    </div>
  );
}

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
        <TaxpayerSelector />
        <p className="muted" style={{ marginTop: 20 }}>
          IRPF · FIFO · base del ahorro. Herramienta de apoyo, no asesoramiento fiscal.
        </p>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/reviews" element={<Reviews />} />
          <Route path="/fiscal" element={<FiscalYears />} />
          <Route path="/model721" element={<Model721 />} />
          <Route path="/taxpayers" element={<Taxpayers />} />
        </Routes>
      </main>
    </div>
  );
}

export { buildTaxpayerQuery };
