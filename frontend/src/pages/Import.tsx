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
  const [preview, setPreview] = useState<any | null>(null);

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
      setPreview(null);
      qc.invalidateQueries();
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("connector", connector);
      fd.append("taxpayer_id", importTaxpayerId);
      fd.append("account_id", accountId);
      fd.append("file", file as File);
      return api.upload("/imports/preview", fd);
    },
    onSuccess: (data: any) => {
      setPreview(data);
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
        <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
          <button
            className="secondary"
            onClick={() => previewMutation.mutate()}
            disabled={!connector || !importTaxpayerId || !accountId || !file || previewMutation.isPending}
          >
            {previewMutation.isPending ? "Analizando..." : "Vista previa"}
          </button>
          <button
            onClick={() => upload.mutate()}
            disabled={!connector || !importTaxpayerId || !accountId || !file || upload.isPending}
          >
            {upload.isPending ? "Importando..." : "Confirmar importación"}
          </button>
        </div>
        {upload.isError && <p className="error">{String(upload.error)}</p>}
        {upload.data && (
          <p className="muted">
            Insertadas {upload.data.inserted_count}, duplicadas{" "}
            {upload.data.duplicate_count}, estado {upload.data.status}.
            {upload.data.errors && upload.data.errors.length > 0 && (
              <span>{` · ${upload.data.errors.length} filas con error`}</span>
            )}
          </p>
        )}

        {preview && (
          <div style={{ marginTop: 20 }}>
            <div className="muted" style={{ marginBottom: 8 }}>
              Vista previa: {preview.parsed_count} filas parseadas,{" "}
              {preview.error_count} errores (mostrando hasta 10 primeras).
            </div>
            {preview.preview.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Entrada</th>
                    <th>Salida</th>
                    <th className="numeric">EUR</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.map((row: any, i: number) => (
                    <tr key={i}>
                      <td>{new Date(row.timestamp).toLocaleString("es-ES")}</td>
                      <td>{row.type}</td>
                      <td>{row.amount_in ? `${row.amount_in} ${row.asset_in}` : "—"}</td>
                      <td>{row.amount_out ? `${row.amount_out} ${row.asset_out}` : "—"}</td>
                      <td className="numeric">{row.eur_value ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {preview.errors.length > 0 && (
              <>
                <h4 style={{ marginTop: 16, color: "#fca5a5" }}>Errores por fila</h4>
                <table>
                  <thead>
                    <tr>
                      <th>Fila</th>
                      <th>Mensaje</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.errors.map((e: any, i: number) => (
                      <tr key={i}>
                        <td>{e.row}</td>
                        <td className="error">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
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
