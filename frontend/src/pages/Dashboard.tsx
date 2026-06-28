import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import { api } from "../api";
import { buildTaxpayerQuery, useTaxpayers } from "../TaxpayerContext";

const COLORS = ["#38bdf8", "#4ade80", "#f472b6", "#fbbf24", "#a78bfa", "#fb923c", "#34d399", "#60a5fa"];

const TX_LABELS: Record<string, string> = {
  BUY: "Compra",
  SELL: "Venta",
  SWAP: "Permuta",
  TRANSFER: "Transferencia",
  DEPOSIT: "Depósito",
  WITHDRAWAL: "Retirada",
  STAKING_REWARD: "Staking",
  AIRDROP: "Airdrop",
  REFERRAL: "Referido",
  SPEND: "Gasto",
  REVERSAL: "Reversión",
  FEE: "Comisión",
};

const REVIEW_CAT_LABELS: Record<string, string> = {
  P2P_TRANSFER: "P2P",
  REVERSAL: "Reversión",
  INSUFFICIENT_BALANCE: "Saldo insuficiente",
  MISSING_PRICE: "Precio ausente",
  MANUAL_REVIEW: "Manual",
};

const INCOME_CAT_LABELS: Record<string, string> = {
  RCM: "RCM",
  GANANCIA: "Ganancia patrimonial",
  ACTIVIDAD: "Actividad económica",
};

function eur(n: number | string | null | undefined): string {
  if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("es-ES", { style: "currency", currency: "EUR" });
}

function num(n: number | string | null | undefined): string {
  if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("es-ES", { maximumFractionDigits: 8 });
}

function pct(n: number | string | null | undefined): string {
  if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
  return `${Number(n).toFixed(2)}%`;
}

function trendClass(n: number): string {
  if (n > 0) return "good";
  if (n < 0) return "bad";
  return "";
}

export default function Dashboard() {
  const { selectedIds } = useTaxpayers();
  const [year, setYear] = useState<number | "">("");
  const [priceMsg, setPriceMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const fetchPrices = useMutation({
    mutationFn: () =>
      api.post("/prices/fetch-historical", {
        taxpayer_ids: selectedIds.length > 0 ? selectedIds : undefined,
        year: year || undefined,
      }),
    onSuccess: (res: any) => {
      const fetched = (res.fetched ?? []).length;
      const missing = (res.missing ?? []).length;
      const skipped = (res.skipped ?? []).length;
      const errors = (res.errors ?? []).length;
      setPriceMsg(
        `Precios cargados: ${fetched} cotizaciones. ` +
          (missing ? `Sin mapear: ${missing}. ` : "") +
          (skipped ? `Saltados: ${skipped}. ` : "") +
          (errors ? `Errores: ${errors}.` : "")
      );
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: any) => {
      setPriceMsg(`Error al cargar precios: ${err.message ?? err}`);
    },
  });

  const params = new URLSearchParams();
  selectedIds.forEach((id) => params.append("taxpayer_ids", String(id)));
  if (year !== "") params.set("year", String(year));
  const url = `/reports/dashboard${params.toString() ? `?${params.toString()}` : ""}`;

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", selectedIds, year],
    queryFn: () => api.get(url),
  });

  const d = data ?? {};
  const years = (d.years ?? []) as any[];
  const fiscal = d.fiscal_totals ?? {};
  const portfolio = d.portfolio ?? {};
  const activity = d.activity ?? {};
  const reviews = d.reviews ?? {};
  const model721 = d.model721 ?? {};
  const evolution = (d.portfolio_evolution ?? []) as any[];
  const investedTotals = d.invested_totals ?? {};
  const contributions = (d.contributions ?? []) as any[];

  const availableYears = useMemo(
    () => Array.from(new Set([...(years.map((y) => y.year) as number[]), ...(evolution.map((e) => e.year) as number[])])).sort((a, b) => b - a),
    [years, evolution]
  );

  const fiscalChart = years.map((y: any) => ({
    year: String(y.year),
    ganancia: Number(y.net_capital_gain),
    impuesto: Number(y.tax_due_eur),
    rcm: Number(y.income_rcm),
    ganancia_income: Number(y.income_ganancia),
  }));

  const portfolioChart = evolution.map((e: any) => ({
    year: String(e.year),
    valor: Number(e.value_eur),
    coste: Number(e.cost_basis_eur),
  }));

  const holdings = (portfolio.top_assets ?? []).map((p: any) => ({
    name: p.asset,
    value: Number(p.value_eur ?? 0),
  }));

  const txTypeData = Object.entries(activity.transactions_by_type ?? {}).map(([k, v]) => ({
    name: TX_LABELS[k] ?? k,
    count: v as number,
  }));

  const incomeByYear = years.map((y: any) => ({
    year: String(y.year),
    rcm: Number(y.income_rcm),
    ganancia: Number(y.income_ganancia),
    actividad: Number(y.income_actividad),
  }));

  const reviewStatusData = [
    { name: "Pendientes", value: reviews.summary?.pending ?? 0, fill: "#f87171" },
    { name: "Resueltos", value: reviews.summary?.resolved ?? 0, fill: "#4ade80" },
    { name: "Ignorados", value: reviews.summary?.ignored ?? 0, fill: "#94a3b8" },
  ].filter((x) => x.value > 0);

  const reviewCatData = Object.entries(reviews.by_category ?? {}).map(([k, v]: [string, any]) => ({
    name: REVIEW_CAT_LABELS[k] ?? k,
    pending: v.pending ?? 0,
    resolved: v.resolved ?? 0,
    ignored: v.ignored ?? 0,
  }));

  const pendingReviews = (reviews.pending ?? []) as any[];
  const lastTransactions = (activity.last_transactions ?? []) as any[];

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Panel general</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="muted">Año fiscal</span>
            <select value={year} onChange={(e) => setYear(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">Todos los años</option>
              {availableYears.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => fetchPrices.mutate()}
            disabled={fetchPrices.isPending || selectedIds.length === 0}
            title="Cargar precios de cierre de año desde CoinGecko"
          >
            {fetchPrices.isPending ? "Cargando precios..." : "Cargar precios históricos (CoinGecko)"}
          </button>
        </div>
      </div>

      {priceMsg && (
        <div className={`alert ${priceMsg.includes("Error") ? "alert-error" : "alert-success"}`} style={{ marginBottom: 16 }}>
          {priceMsg}
          <button onClick={() => setPriceMsg(null)} style={{ marginLeft: 12 }} aria-label="Cerrar">
            ✕
          </button>
        </div>
      )}

      {isLoading && <p className="muted">Cargando panel...</p>}

      {!isLoading && (
        <>
          {/* KPIs */}
          <div className="kpi-grid">
            <div className="card kpi">
              <div className="muted">Patrimonio {year ? `a 31/12/${year}` : "actual"}</div>
              <div className="stat">{eur(portfolio.total_value_eur)}</div>
              <div className={`kpi-trend ${trendClass(Number(portfolio.unrealized_gain_eur))}`}>
                {Number(portfolio.unrealized_gain_eur) >= 0 ? "▲" : "▼"} {eur(portfolio.unrealized_gain_eur)} no realizado
              </div>
            </div>

            <div className="card kpi">
              <div className="muted">Total aportado</div>
              <div className="stat">{eur(investedTotals.invested_eur)}</div>
              <div className="kpi-trend muted">
                {eur(investedTotals.rewards_eur)} en recompensas · {eur(investedTotals.cost_basis_eur)} base de coste total
              </div>
            </div>

            <div className="card kpi">
              <div className="muted">Ganancia neta realizada</div>
              <div className={`stat ${trendClass(Number(fiscal.net_capital_gain))}`}>
                {eur(fiscal.net_capital_gain)}
              </div>
              <div className="kpi-trend muted">
                {eur(fiscal.total_gains)} ganancias · {eur(fiscal.total_losses)} pérdidas
              </div>
            </div>

            <div className="card kpi">
              <div className="muted">Impuesto estimado</div>
              <div className="stat">{eur(fiscal.tax_due_eur)}</div>
              <div className="kpi-trend muted">Base ahorro: {eur(fiscal.savings_base)}</div>
            </div>

            <div className="card kpi">
              <div className="muted">Ingresos declarables</div>
              <div className="stat">{eur(Number(fiscal.rcm_income) + Number(fiscal.ganancia_income) + Number(fiscal.actividad_income))}</div>
              <div className="kpi-trend muted">
                RCM {eur(fiscal.rcm_income)} · Ganancias {eur(fiscal.ganancia_income)} · Actividad {eur(fiscal.actividad_income)}
              </div>
            </div>

            <Link to="/reviews" className="card kpi clickable">
              <div className="muted">Avisos pendientes</div>
              <div className={`stat ${reviews.summary?.pending ? "bad" : "good"}`}>{reviews.summary?.pending ?? 0}</div>
              <div className="kpi-trend muted">
                {reviews.summary?.resolved ?? 0} resueltos · {reviews.summary?.ignored ?? 0} ignorados
              </div>
            </Link>

            <Link to="/model721" className="card kpi clickable">
              <div className="muted">Modelo 721 ({model721.year})</div>
              <div className="stat">{eur(model721.total_abroad_eur)}</div>
              <div className={`kpi-trend ${model721.obligated ? "bad" : "good"}`}>
                {model721.obligated ? "Obligado a declarar" : `Bajo umbral (${eur(model721.threshold_eur)})`}
              </div>
            </Link>
          </div>

          {/* Fiscal + portfolio evolution */}
          <div className="chart-grid">
            <div className="card">
              <h3>Evolución fiscal</h3>
              {fiscalChart.length === 0 ? (
                <p className="muted">Sin datos fiscales todavía.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={fiscalChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="year" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                    <Legend />
                    <Bar dataKey="ganancia" fill="#38bdf8" name="Ganancia neta (€)" />
                    <Bar dataKey="rcm" fill="#f472b6" name="RCM (€)" />
                    <Line type="monotone" dataKey="impuesto" stroke="#4ade80" name="Impuesto (€)" />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card">
              <h3>Evolución del patrimonio</h3>
              {portfolioChart.length === 0 ? (
                <p className="muted">Sin datos de cartera.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart data={portfolioChart}>
                    <defs>
                      <linearGradient id="colorValor" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="year" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                    <Legend />
                    <Area type="monotone" dataKey="valor" stroke="#38bdf8" fill="url(#colorValor)" name="Valor (€)" />
                    <Line type="monotone" dataKey="coste" stroke="#94a3b8" name="Coste (€)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Distribution, activity, reviews */}
          <div className="chart-grid">
            <div className="card">
              <h3>Distribución de la cartera</h3>
              {holdings.length === 0 ? (
                <p className="muted">Sin precios cargados. Añade cotizaciones para valorar.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie data={holdings} dataKey="value" nameKey="name" outerRadius={110} label>
                      {holdings.map((_: any, i: number) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} formatter={(v: any) => eur(v)} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card">
              <h3>Ingresos por categoría y año</h3>
              {incomeByYear.length === 0 ? (
                <p className="muted">Sin ingresos registrados.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={incomeByYear}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="year" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                    <Legend />
                    <Bar dataKey="rcm" stackId="a" fill="#38bdf8" name={INCOME_CAT_LABELS.RCM} />
                    <Bar dataKey="ganancia" stackId="a" fill="#f472b6" name={INCOME_CAT_LABELS.GANANCIA} />
                    <Bar dataKey="actividad" stackId="a" fill="#fbbf24" name={INCOME_CAT_LABELS.ACTIVIDAD} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card">
              <h3>Transacciones por tipo</h3>
              {txTypeData.length === 0 ? (
                <p className="muted">Sin transacciones.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={txTypeData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" stroke="#94a3b8" />
                    <YAxis dataKey="name" type="category" width={110} stroke="#94a3b8" />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                    <Bar dataKey="count" fill="#38bdf8" />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card">
              <h3>Estado de los avisos</h3>
              {reviewStatusData.length === 0 ? (
                <p className="muted">Sin avisos.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie data={reviewStatusData} dataKey="value" nameKey="name" innerRadius={70} outerRadius={110} label>
                      {reviewStatusData.map((entry: any, i: number) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {reviewCatData.length > 0 && (
            <div className="card">
              <h3>Avisos por categoría</h3>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={reviewCatData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" stroke="#94a3b8" />
                  <YAxis stroke="#94a3b8" />
                  <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid #334155" }} />
                  <Legend />
                  <Bar dataKey="pending" stackId="a" fill="#f87171" name="Pendiente" />
                  <Bar dataKey="resolved" stackId="a" fill="#4ade80" name="Resuelto" />
                  <Bar dataKey="ignored" stackId="a" fill="#94a3b8" name="Ignorado" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Tables */}
          <div className="chart-grid">
            <div className="card">
              <h3>Top activos por valor</h3>
              <table>
                <thead>
                  <tr>
                    <th>Activo</th>
                    <th className="numeric">Cantidad</th>
                    <th className="numeric">Precio</th>
                    <th className="numeric">Valor</th>
                    <th className="numeric">No realizado</th>
                    <th className="numeric">%</th>
                  </tr>
                </thead>
                <tbody>
                  {(portfolio.top_assets ?? []).map((a: any) => (
                    <tr key={a.asset}>
                      <td><strong>{a.asset}</strong></td>
                      <td className="numeric">{num(a.quantity)}</td>
                      <td className="numeric">{eur(a.price_eur)}</td>
                      <td className="numeric">{eur(a.value_eur)}</td>
                      <td className={`numeric ${trendClass(Number(a.unrealized_eur))}`}>{eur(a.unrealized_eur)}</td>
                      <td className="numeric">{pct(a.pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(portfolio.top_assets ?? []).length === 0 && <p className="muted">Sin activos valorados.</p>}
            </div>

            <div className="card">
              <h3>Últimas transacciones</h3>
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Movimiento</th>
                    <th className="numeric">EUR</th>
                  </tr>
                </thead>
                <tbody>
                  {lastTransactions.map((tx: any) => (
                    <tr key={tx.id}>
                      <td>{new Date(tx.timestamp).toLocaleDateString("es-ES")}</td>
                      <td>{TX_LABELS[tx.type] ?? tx.type}</td>
                      <td>
                        {tx.amount_in ? `${num(tx.amount_in)} ${tx.asset_in}` : ""}
                        {tx.amount_in && tx.amount_out ? " → " : ""}
                        {tx.amount_out ? `${num(tx.amount_out)} ${tx.asset_out}` : ""}
                      </td>
                      <td className="numeric">{eur(tx.eur_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {lastTransactions.length === 0 && <p className="muted">Sin transacciones.</p>}
            </div>
          </div>

          {contributions.length > 0 && (
            <div className="card">
              <h3>Dinero aportado por activo</h3>
              <table>
                <thead>
                  <tr>
                    <th>Activo</th>
                    <th className="numeric">Cantidad</th>
                    <th className="numeric">Comprado (EUR)</th>
                    <th className="numeric">Recompensas (EUR)</th>
                    <th className="numeric">Base de coste</th>
                    <th className="numeric">Valor actual</th>
                    <th className="numeric">Rentabilidad</th>
                  </tr>
                </thead>
                <tbody>
                  {contributions.map((c: any) => {
                    const top = (portfolio.top_assets ?? []).find((a: any) => a.asset === c.asset);
                    const value = top ? Number(top.value_eur ?? 0) : 0;
                    const cost = Number(c.cost_basis_eur ?? 0);
                    const pnl = value - cost;
                    return (
                      <tr key={c.asset}>
                        <td><strong>{c.asset}</strong></td>
                        <td className="numeric">{num(c.quantity)}</td>
                        <td className="numeric">{eur(c.invested_eur)}</td>
                        <td className="numeric">{eur(c.rewards_eur)}</td>
                        <td className="numeric">{eur(c.cost_basis_eur)}</td>
                        <td className="numeric">{eur(value)}</td>
                        <td className={`numeric ${trendClass(pnl)}`}>{pnl > 0 ? "+" : ""}{eur(pnl)} (
                          {cost > 0 ? ((pnl / cost) * 100).toFixed(2) : "—"}%)
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ marginTop: 12, display: "flex", gap: 24 }} className="muted">
                <span>Total aportado: <strong>{eur(investedTotals.invested_eur)}</strong></span>
                <span>Total recompensas: <strong>{eur(investedTotals.rewards_eur)}</strong></span>
                <span>Base de coste: <strong>{eur(investedTotals.cost_basis_eur)}</strong></span>
              </div>            </div>
          )}

          {pendingReviews.length > 0 && (
            <div className="card">
              <h3>Avisos pendientes recientes</h3>
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Categoría</th>
                    <th>Severidad</th>
                    <th>Mensaje</th>
                    <th>Tx</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingReviews.map((r: any) => (
                    <tr key={r.id}>
                      <td>{new Date(r.created_at).toLocaleDateString("es-ES")}</td>
                      <td>{REVIEW_CAT_LABELS[r.category] ?? r.category}</td>
                      <td>{r.severity}</td>
                      <td>{r.message}</td>
                      <td>{r.transaction_id ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ marginTop: 12 }}>
                <Link to="/reviews">Ver todos los avisos →</Link>
              </p>
            </div>
          )}
        </>
      )}
    </>
  );
}
