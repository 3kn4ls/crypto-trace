import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";

const COLORS = ["#38bdf8", "#4ade80", "#f472b6", "#fbbf24", "#a78bfa", "#fb923c", "#34d399"];

export default function Dashboard() {
  const yearly = useQuery({ queryKey: ["yearly"], queryFn: () => api.get("/reports/yearly") });
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: () => api.get("/reports/portfolio") });

  const years = (yearly.data ?? []).map((y: any) => ({
    year: String(y.year),
    ganancia: Number(y.net_capital_gain),
    impuesto: Number(y.tax_due_eur),
  }));
  const holdings = (portfolio.data ?? [])
    .filter((p: any) => p.value_eur != null)
    .map((p: any) => ({ name: p.asset, value: Number(p.value_eur) }));

  const totalTax = years.reduce((s: number, y: any) => s + y.impuesto, 0);
  const totalValue = holdings.reduce((s: number, h: any) => s + h.value, 0);

  return (
    <>
      <h2>Panel general</h2>
      <div className="grid">
        <div className="card">
          <div className="muted">Impuesto estimado acumulado</div>
          <div className="stat">{totalTax.toLocaleString("es-ES", { style: "currency", currency: "EUR" })}</div>
        </div>
        <div className="card">
          <div className="muted">Valor actual de cartera</div>
          <div className="stat good">{totalValue.toLocaleString("es-ES", { style: "currency", currency: "EUR" })}</div>
        </div>
        <div className="card">
          <div className="muted">Años con actividad</div>
          <div className="stat">{years.length}</div>
        </div>
      </div>

      <div className="card">
        <h3>Ganancia neta e impuesto por año fiscal</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={years}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="year" stroke="#94a3b8" />
            <YAxis stroke="#94a3b8" />
            <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
            <Legend />
            <Bar dataKey="ganancia" fill="#38bdf8" name="Ganancia neta (€)" />
            <Bar dataKey="impuesto" fill="#4ade80" name="Impuesto (€)" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h3>Distribución de la cartera</h3>
        {holdings.length === 0 ? (
          <p className="muted">Sin precios cargados todavía. Añade cotizaciones para valorar la cartera.</p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={holdings} dataKey="value" nameKey="name" outerRadius={110} label>
                {holdings.map((_: any, i: number) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
    </>
  );
}
