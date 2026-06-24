import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";

export default function Model721() {
  const [year, setYear] = useState(String(new Date().getFullYear() - 1));
  const data = useQuery({
    queryKey: ["model721", year],
    queryFn: () => api.get(`/reports/model721/${year}`),
    enabled: !!year,
  });

  const eur = (v: any) => (v == null ? "—" : Number(v).toLocaleString("es-ES", { style: "currency", currency: "EUR" }));
  const d = data.data;

  return (
    <>
      <h2>Modelo 721 — criptos en el extranjero</h2>
      <div className="card">
        <input value={year} onChange={(e) => setYear(e.target.value)} placeholder="Año" />
        {d && (
          <>
            <div className="grid">
              <div>
                <div className="muted">Saldo total en el extranjero a 31/12</div>
                <div className="stat">{eur(d.total_abroad_eur)}</div>
              </div>
              <div>
                <div className="muted">Umbral de declaración</div>
                <div className="stat">{eur(d.threshold_eur)}</div>
              </div>
              <div>
                <div className="muted">Obligación de declarar</div>
                <div className={`stat ${d.obligated ? "bad" : "good"}`}>{d.obligated ? "SÍ" : "No"}</div>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>Cuenta</th><th>Extranjero</th><th>Activo</th><th>Cantidad</th><th>Precio €</th><th>Valor €</th></tr>
              </thead>
              <tbody>
                {(d.holdings ?? []).map((h: any, i: number) => (
                  <tr key={i}>
                    <td>{h.account}</td>
                    <td>{h.is_abroad ? "Sí" : "No"}</td>
                    <td>{h.asset}</td>
                    <td>{h.quantity}</td>
                    <td>{h.price_eur ?? "—"}</td>
                    <td>{h.value_eur ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(d.warnings ?? []).map((w: string, i: number) => <p key={i} className="muted">{w}</p>)}
          </>
        )}
      </div>
    </>
  );
}
