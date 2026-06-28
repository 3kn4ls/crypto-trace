import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import ExportButtons from "../components/ExportButtons";
import ReviewDialog from "../components/ReviewDialog";
import TransactionEditDialog from "../components/TransactionEditDialog";
import { buildTaxpayerQuery, useTaxpayers } from "../TaxpayerContext";

interface Transaction {
  id: number;
  timestamp: string;
  type: string;
  asset_in: string | null;
  amount_in: string | null;
  asset_out: string | null;
  amount_out: string | null;
  eur_value: string | null;
  cost_basis_eur: string | null;
  is_internal_transfer: boolean;
  fiscal_year: number;
  source: string | null;
  notes: string | null;
}

export default function Transactions() {
  const { selectedIds } = useTaxpayers();
  const [year, setYear] = useState("");
  const [activeTx, setActiveTx] = useState<number | null>(null);
  const [editTx, setEditTx] = useState<Transaction | null>(null);

  const q = selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}&` : "?";
  const url = `/transactions${q}${year ? `year=${year}` : ""}`;

  const txs = useQuery({
    queryKey: ["transactions", selectedIds, year],
    queryFn: () => api.get(url),
  });

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Transacciones</h2>
        <ExportButtons scope="transactions" year={year} taxpayerIds={selectedIds} />
      </div>
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
              <th>Coste base €</th>
              <th>Interna</th>
              <th>Origen</th>
              <th>Año</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {(txs.data ?? []).map((t: Transaction) => (
              <tr key={t.id}>
                <td>{new Date(t.timestamp).toLocaleString("es-ES")}</td>
                <td>{t.taxpayer_id}</td>
                <td>{t.type}</td>
                <td>{t.amount_in ? `${t.amount_in} ${t.asset_in}` : "—"}</td>
                <td>{t.amount_out ? `${t.amount_out} ${t.asset_out}` : "—"}</td>
                <td>{t.eur_value ?? "—"}</td>
                <td>{t.cost_basis_eur ?? "—"}</td>
                <td>{t.is_internal_transfer ? "Sí" : "No"}</td>
                <td>{t.source ?? "—"}</td>
                <td>{t.fiscal_year}</td>
                <td>
                  <button className="small" onClick={() => setEditTx(t)} style={{ marginRight: 8 }}>
                    Editar
                  </button>
                  {t.notes && (
                    <>
                      <span title={t.notes}>⚠️</span>{" "}
                      <button className="small" onClick={() => setActiveTx(t.id)}>Revisar</button>
                    </>
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
      {editTx !== null && (
        <TransactionEditDialog transaction={editTx} onClose={() => setEditTx(null)} />
      )}
    </>
  );
}
