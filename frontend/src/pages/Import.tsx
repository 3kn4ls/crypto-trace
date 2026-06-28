import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useTaxpayers } from "../TaxpayerContext";

export default function ImportPage() {
  const qc = useQueryClient();
  const { taxpayers, selectedIds } = useTaxpayers();
  const defaultTaxpayerId = selectedIds[0] ?? "";

  const [connector, setConnector] = useState("");
  const [importTaxpayerId, setImportTaxpayerId] = useState(String(defaultTaxpayerId));
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [newAccount, setNewAccount] = useState("");
  const [abroad, setAbroad] = useState(true);

  const connectors = useQuery({ queryKey: ["connectors"], queryFn: () => api.get("/connectors") });
  const accounts = useQuery({
    queryKey: ["accounts", importTaxpayerId],
    queryFn: () => api.get(`/accounts?taxpayer_id=${importTaxpayerId}`),
    enabled: !!importTaxpayerId,
  });
  const batches = useQuery({
    queryKey: ["batches", importTaxpayerId],
    queryFn: () => api.get(`/imports?taxpayer_id=${importTaxpayerId}`),
    enabled: !!importTaxpayerId,
  });

  const createAccount = useMutation({
    mutationFn: () =>
      api.post("/accounts", {
        taxpayer_id: Number(importTaxpayerId),
        name: newAccount,
        platform: "MANUAL",
        is_abroad: abroad,
      }),
    onSuccess: () => {
      setNewAccount("");
      qc.invalidateQueries({ queryKey: ["accounts", importTaxpayerId] });
    },
  });

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("connector", connector);
      fd.append("taxpayer_id", importTaxpayerId);
      fd.append("account_id", accountId);
      fd.append("file", file as File);
      return api.upload("/imports", fd);
    },
    onSuccess: () => {
      qc.invalidateQueries();
    },
  });

  const deleteBatch = useMutation({
    mutationFn: (batchId: number) =>
      api.del(`/imports/${batchId}?taxpayer_id=${importTaxpayerId}`),
    onSuccess: () => qc.invalidateQueries(),
  });

  const clearAll = useMutation({
    mutationFn: () => api.del(`/imports?taxpayer_id=${importTaxpayerId}`),
    onSuccess: () => qc.invalidateQueries(),
  });

  const handleDeleteBatch = (batchId: number) => {
    if (!window.confirm("¿Eliminar esta importación? Se borrarán sus transacciones y se recalculará todo el estado derivado.")) {
      return;
    }
    deleteBatch.mutate(batchId);
  };

  const handleClearAll = () => {
    if (!window.confirm("¿Borrar TODAS las importaciones y transacciones de este contribuyente? Esta acción no se puede deshacer.")) {
      return;
    }
    clearAll.mutate();
  };

  return (
    <>
      <h2>Importar movimientos (CSV / Excel)</h2>

      <div className="card">
        <h3>Nueva cuenta</h3>
        <select
          value={importTaxpayerId}
          onChange={(e) => setImportTaxpayerId(e.target.value)}
        >
          <option value="">— Contribuyente —</option>
          {taxpayers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} {t.tax_id ? `(${t.tax_id})` : ""}
            </option>
          ))}
        </select>
        <input
          placeholder="Nombre (p. ej. Crypto.com)"
          value={newAccount}
          onChange={(e) => setNewAccount(e.target.value)}
        />
        <label className="muted">
          <input
            type="checkbox"
            checked={abroad}
            onChange={(e) => setAbroad(e.target.checked)}
          />{" "}
          En el extranjero (Modelo 721)
        </label>
        <button
          onClick={() => createAccount.mutate()}
          disabled={!newAccount || !importTaxpayerId}
        >
          Crear cuenta
        </button>
      </div>

      <div className="card">
        <h3>Subir fichero</h3>
        <select value={connector} onChange={(e) => setConnector(e.target.value)}>
          <option value="">— Conector —</option>
          {(connectors.data ?? []).map((c: any) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
        </select>
        <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">— Cuenta —</option>
          {(accounts.data ?? []).map((a: any) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <input
          type="file"
          accept=".csv,.xlsx"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          onClick={() => upload.mutate()}
          disabled={!connector || !importTaxpayerId || !accountId || !file}
        >
          Importar
        </button>
        {upload.isError && <p className="error">{String(upload.error)}</p>}
        {upload.data && (
          <p className="muted">
            Insertadas {upload.data.inserted_count}, duplicadas{" "}
            {upload.data.duplicate_count}, estado {upload.data.status}.
          </p>
        )}
      </div>

      <div className="card">
        <div className="flex-between">
          <h3>Importaciones</h3>
          <button
            className="danger"
            onClick={handleClearAll}
            disabled={!importTaxpayerId || !(batches.data ?? []).length || clearAll.isPending}
          >
            Limpiar todo
          </button>
        </div>
        {deleteBatch.isError && <p className="error">{String(deleteBatch.error)}</p>}
        {clearAll.isError && <p className="error">{String(clearAll.error)}</p>}
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Contribuyente</th>
              <th>Conector</th>
              <th>Fichero</th>
              <th>Insertadas</th>
              <th>Duplicadas</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {(batches.data ?? []).map((b: any) => (
              <tr key={b.id}>
                <td>{b.id}</td>
                <td>{b.taxpayer_id}</td>
                <td>{b.connector}</td>
                <td>{b.filename}</td>
                <td>{b.inserted_count}</td>
                <td>{b.duplicate_count}</td>
                <td>{b.status}</td>
                <td>
                  <button
                    className="small danger"
                    onClick={() => handleDeleteBatch(b.id)}
                    disabled={deleteBatch.isPending && deleteBatch.variables === b.id}
                  >
                    Eliminar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
