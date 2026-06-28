import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import ReviewDialog from "../components/ReviewDialog";
import { buildTaxpayerQuery, useTaxpayers } from "../TaxpayerContext";

export default function Transactions() {
  const { selectedIds } = useTaxpayers();
  const [year, setYear] = useState("");
  const [activeTx, setActiveTx] = useState<number | null>(null);

  const q = selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}&` : "?";
  const url = `/transactions${q}${year ? `year=${year}` : ""}`;

  const txs = useQuery({
    queryKey: ["transactions", selectedIds, year],
    queryFn: () => api.get(url),
  });

  return (
    <>
      <h2>Transacciones</h2>
      <div className="card">
        <input
          placeholder="Año (p. ej. 2024)"
          value={year}
          onChange={(e) => setYear(e.target.value)}
        />
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Contrib.</th>
              <th>Tipo</th>
              <th>Entra</th>
              <th>Sale</th>
              <th>Valor €</th>
              <th>Origen</th>
              <th>Año</th>
              <th>Revisar</th>
            </tr>
          </thead>
          <tbody>
            {(txs.data ?? []).map((t: any) => (
              <tr key={t.id}>
                <td>{new Date(t.timestamp).toLocaleString("es-ES")}</td>
                <td>{t.taxpayer_id}</td>
                <td>{t.type}</td>
                <td>{t.amount_in ? `${t.amount_in} ${t.asset_in}` : "—"}</td>
                <td>{t.amount_out ? `${t.amount_out} ${t.asset_out}` : "—"}</td>
                <td>{t.eur_value ?? "—"}</td>
                <td>{t.source ?? "—"}</td>
                <td>{t.fiscal_year}</td>
                <td>
                  {t.notes ? (
                    <>
                      <span title={t.notes}>⚠️</span>{" "}
                      <button className="small" onClick={() => setActiveTx(t.id)}>Revisar</button>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(txs.data ?? []).length === 0 && <p className="muted">Sin transacciones. Importa un Excel primero.</p>}
      </div>

      {activeTx !== null && (
        <ReviewDialog transactionId={activeTx} onClose={() => setActiveTx(null)} />
      )}
    </>
  );
}
