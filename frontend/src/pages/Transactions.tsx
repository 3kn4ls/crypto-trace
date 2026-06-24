import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";

export default function Transactions() {
  const [year, setYear] = useState("");
  const txs = useQuery({
    queryKey: ["transactions", year],
    queryFn: () => api.get(`/transactions${year ? `?year=${year}` : ""}`),
  });

  return (
    <>
      <h2>Transacciones</h2>
      <div className="card">
        <input placeholder="Año (p. ej. 2024)" value={year} onChange={(e) => setYear(e.target.value)} />
        <table>
          <thead>
            <tr>
              <th>Fecha</th><th>Tipo</th><th>Entra</th><th>Sale</th><th>Valor €</th><th>Año</th>
            </tr>
          </thead>
          <tbody>
            {(txs.data ?? []).map((t: any) => (
              <tr key={t.id}>
                <td>{new Date(t.timestamp).toLocaleString("es-ES")}</td>
                <td>{t.type}</td>
                <td>{t.amount_in ? `${t.amount_in} ${t.asset_in}` : "—"}</td>
                <td>{t.amount_out ? `${t.amount_out} ${t.asset_out}` : "—"}</td>
                <td>{t.eur_value ?? "—"}</td>
                <td>{t.fiscal_year}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(txs.data ?? []).length === 0 && <p className="muted">Sin transacciones. Importa un Excel primero.</p>}
      </div>
    </>
  );
}
