import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { buildTaxpayerQuery, useTaxpayers } from "../TaxpayerContext";

export default function FiscalYears() {
  const qc = useQueryClient();
  const { selectedIds, isJoint } = useTaxpayers();
  const singleTaxpayerId = isJoint ? null : selectedIds[0] ?? null;
  const [selected, setSelected] = useState<number | null>(null);

  const q = selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}` : "";
  const years = useQuery({
    queryKey: ["fiscal-years", selectedIds],
    queryFn: () => api.get(`/fiscal-years${q}`),
  });

  const tax = useQuery({
    queryKey: ["tax", selected, selectedIds],
    queryFn: () => api.get(`/fiscal-years/${selected}/tax${q}`),
    enabled: selected != null,
  });

  const close = useMutation({
    mutationFn: (year: number) =>
      api.post(`/fiscal-years/${year}/close?taxpayer_id=${singleTaxpayerId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fiscal-years"] }),
  });

  const reopen = useMutation({
    mutationFn: (year: number) =>
      api.post(`/fiscal-years/${year}/reopen?taxpayer_id=${singleTaxpayerId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fiscal-years"] }),
  });

  const eur = (v: any) =>
    v == null ? "—" : Number(v).toLocaleString("es-ES", { style: "currency", currency: "EUR" });

  return (
    <>
      <h2>Años fiscales</h2>
      {isJoint && <p className="muted">Modo declaración conjunta. El cierre/reapertura requiere un único contribuyente.</p>}
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Contrib.</th>
              <th>Año</th>
              <th>Estado</th>
              <th>Ganancia neta</th>
              <th>Impuesto</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(years.data ?? []).map((y: any) => (
              <tr key={`${y.taxpayer_id}-${y.year}`}>
                <td>{y.taxpayer_id}</td>
                <td>
                  <a onClick={() => setSelected(y.year)} style={{ cursor: "pointer" }}>
                    {y.year}
                  </a>
                </td>
                <td>
                  <span className={`badge ${y.status === "CLOSED" ? "closed" : "open"}`}>
                    {y.status}
                  </span>
                </td>
                <td>{eur(y.net_gain_eur)}</td>
                <td>{eur(y.tax_due_eur)}</td>
                <td>
                  {y.status === "CLOSED" ? (
                    <button
                      className="ghost"
                      onClick={() => reopen.mutate(y.year)}
                      disabled={isJoint || singleTaxpayerId !== y.taxpayer_id}
                    >
                      Reabrir
                    </button>
                  ) : (
                    <button
                      onClick={() => close.mutate(y.year)}
                      disabled={isJoint || singleTaxpayerId !== y.taxpayer_id}
                    >
                      Cerrar año
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(years.data ?? []).length === 0 && <p className="muted">Sin años todavía. Importa transacciones.</p>}
      </div>

      {selected != null && tax.data && (
        <div className="card">
          <h3>Detalle fiscal {selected}</h3>
          <div className="grid">
            <div>
              <div className="muted">Ganancias</div>
              <div className="stat good">{eur(tax.data.total_gains)}</div>
            </div>
            <div>
              <div className="muted">Pérdidas</div>
              <div className="stat bad">{eur(tax.data.total_losses)}</div>
            </div>
            <div>
              <div className="muted">Base del ahorro</div>
              <div className="stat">{eur(tax.data.savings_base)}</div>
            </div>
            <div>
              <div className="muted">Impuesto estimado</div>
              <div className="stat">{eur(tax.data.tax_due)}</div>
            </div>
            <div>
              <div className="muted">Tipo efectivo</div>
              <div className="stat">{(Number(tax.data.effective_rate) * 100).toFixed(2)}%</div>
            </div>
          </div>
          <h4>Tramos aplicados</h4>
          <table>
            <thead>
              <tr>
                <th>Desde</th>
                <th>Hasta</th>
                <th>Tipo</th>
                <th>Cuota</th>
              </tr>
            </thead>
            <tbody>
              {(tax.data.bracket_breakdown ?? []).map((b: any, i: number) => (
                <tr key={i}>
                  <td>{eur(b.from_eur)}</td>
                  <td>{b.to_eur ? eur(b.to_eur) : "∞"}</td>
                  <td>{(Number(b.rate) * 100).toFixed(0)}%</td>
                  <td>{eur(b.tax)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(tax.data.notes ?? []).map((n: string, i: number) => (
            <p key={i} className="muted">{n}</p>
          ))}
        </div>
      )}
    </>
  );
}
