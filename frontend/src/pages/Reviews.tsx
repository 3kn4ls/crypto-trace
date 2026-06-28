import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { buildTaxpayerQuery, useTaxpayers } from "../TaxpayerContext";

const CATEGORIES: Record<string, string> = {
  P2P_TRANSFER: "P2P con tercero",
  REVERSAL: "Reversión",
  INSUFFICIENT_BALANCE: "Saldo insuficiente",
  MISSING_PRICE: "Precio ausente",
  MANUAL_REVIEW: "Revisión manual",
};

const SEVERITY_EMOJI: Record<string, string> = {
  INFO: "ℹ️",
  WARNING: "⚠️",
  ERROR: "🛑",
};

const ACTION_LABELS: Record<string, string> = {
  MARK_OWN_ACCOUNT: "Cuenta propia",
  MARK_THIRD_PARTY_SEND: "Envío a tercero",
  MARK_PAYMENT: "Pago por bienes/servicios",
  REVIEWED_OK: "Revisado OK",
  ACCEPT_ZERO_BASIS: "Aceptar base 0",
  CREATE_OPENING_POSITION: "Crear posición apertura",
  ADD_PRICE_QUOTE: "Añadir cotización",
  IGNORE: "Ignorar",
};

const CATEGORY_ACTIONS: Record<string, string[]> = {
  P2P_TRANSFER: ["MARK_OWN_ACCOUNT", "MARK_THIRD_PARTY_SEND", "MARK_PAYMENT", "IGNORE"],
  REVERSAL: ["REVIEWED_OK", "IGNORE"],
  INSUFFICIENT_BALANCE: ["ACCEPT_ZERO_BASIS", "CREATE_OPENING_POSITION", "IGNORE"],
  MISSING_PRICE: ["ADD_PRICE_QUOTE", "IGNORE"],
  MANUAL_REVIEW: ["REVIEWED_OK", "IGNORE"],
};

interface ReviewItem {
  id: number;
  transaction_id: number | null;
  taxpayer_id: number;
  category: string;
  severity: string;
  message: string;
  status: string;
  resolution_action: string | null;
  resolution_note: string | null;
  created_at: string;
  resolved_at: string | null;
}

export default function Reviews() {
  const { selectedIds } = useTaxpayers();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("PENDING");
  const [category, setCategory] = useState("");
  const [year, setYear] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkAction, setBulkAction] = useState("");
  const [priceForm, setPriceForm] = useState<{ itemId?: number; symbol: string; price: string; date: string }>({
    symbol: "",
    price: "",
    date: "",
  });
  const [openingForm, setOpeningForm] = useState<{ itemId?: number; symbol: string; quantity: string; costBasis: string; date: string }>({
    symbol: "",
    quantity: "",
    costBasis: "",
    date: "",
  });

  const baseQ = selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}&` : "?";
  const listUrl = `/reviews${baseQ}status=${status}${category ? `&category=${category}` : ""}${year ? `&year=${year}` : ""}`;
  const summaryUrl = `/reviews/summary${selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}` : ""}`;

  const items = useQuery({
    queryKey: ["reviews", selectedIds, status, category, year],
    queryFn: () => api.get(listUrl),
  });

  const summary = useQuery({
    queryKey: ["reviews-summary", selectedIds],
    queryFn: () => api.get(summaryUrl),
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post(`/reviews/generate${selectedIds.length > 0 ? `?${buildTaxpayerQuery(selectedIds)}` : ""}${year ? `&year=${year}` : ""}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      queryClient.invalidateQueries({ queryKey: ["reviews-summary"] });
    },
  });

  const resolve = useMutation({
    mutationFn: ({ id, action, note, payload }: { id: number; action: string; note?: string; payload?: any }) =>
      api.post(`/reviews/${id}/resolve`, { action, note, payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      queryClient.invalidateQueries({ queryKey: ["reviews-summary"] });
      setPriceForm({ symbol: "", price: "", date: "" });
      setOpeningForm({ symbol: "", quantity: "", costBasis: "", date: "" });
    },
  });

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleAll = () => {
    const data = (items.data ?? []) as ReviewItem[];
    if (selected.size === data.length) setSelected(new Set());
    else setSelected(new Set(data.map((d) => d.id)));
  };

  const runBulk = () => {
    if (!bulkAction) return;
    const promises = Array.from(selected).map((id) => resolve.mutateAsync({ id, action: bulkAction }));
    Promise.all(promises).then(() => setSelected(new Set()));
  };

  const applyPrice = (item: ReviewItem) => {
    const assetMatch = item.message.match(/(\w+)\s*\(/);
    const symbol = priceForm.symbol || (assetMatch ? assetMatch[1] : "");
    const d = priceForm.date || `${year || new Date().getFullYear()}-12-31`;
    resolve.mutate({
      id: item.id,
      action: "ADD_PRICE_QUOTE",
      payload: { asset_symbol: symbol, price_eur: priceForm.price, date: d },
    });
  };

  const applyOpening = (item: ReviewItem) => {
    const assetMatch = item.message.match(/asset_id=(\d+)/);
    resolve.mutate({
      id: item.id,
      action: "CREATE_OPENING_POSITION",
      payload: {
        asset_symbol: openingForm.symbol,
        quantity: openingForm.quantity,
        cost_basis_eur: openingForm.costBasis,
        acquired_at: openingForm.date,
      },
    });
  };

  const data = (items.data ?? []) as ReviewItem[];
  const s = summary.data ?? { pending: 0, resolved: 0, ignored: 0, total: 0 };

  return (
    <>
      <h2>Revisar avisos</h2>

      <div className="card" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <div><strong>{s.pending}</strong> <span className="muted">pendientes</span></div>
        <div><strong>{s.resolved}</strong> <span className="muted">resueltos</span></div>
        <div><strong>{s.ignored}</strong> <span className="muted">ignorados</span></div>
        <div><strong>{s.total}</strong> <span className="muted">total</span></div>
      </div>

      <div className="card" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "end", marginBottom: 16 }}>
        <label>
          Estado
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todos</option>
            <option value="PENDING">Pendiente</option>
            <option value="RESOLVED">Resuelto</option>
            <option value="IGNORED">Ignorado</option>
          </select>
        </label>
        <label>
          Categoría
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Todas</option>
            {Object.entries(CATEGORIES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Año
          <input placeholder="2025" value={year} onChange={(e) => setYear(e.target.value)} style={{ width: 80 }} />
        </label>
        <button onClick={() => generate.mutate()}>Regenerar avisos</button>
      </div>

      <div className="card" style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <input type="checkbox" checked={data.length > 0 && selected.size === data.length} onChange={toggleAll} />
        <select value={bulkAction} onChange={(e) => setBulkAction(e.target.value)}>
          <option value="">Acción masiva...</option>
          <option value="IGNORE">Ignorar</option>
          <option value="REVIEWED_OK">Marcar revisado OK</option>
          <option value="MARK_OWN_ACCOUNT">Marcar cuenta propia</option>
        </select>
        <button onClick={runBulk} disabled={!bulkAction || selected.size === 0}>Aplicar a {selected.size}</button>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Severidad</th>
              <th>Fecha</th>
              <th>Categoría</th>
              <th>Mensaje</th>
              <th>Tx</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td><input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} /></td>
                <td>{SEVERITY_EMOJI[item.severity] ?? item.severity}</td>
                <td>{new Date(item.created_at).toLocaleDateString("es-ES")}</td>
                <td>{CATEGORIES[item.category] ?? item.category}</td>
                <td style={{ maxWidth: 360, whiteSpace: "normal" }}>{item.message}</td>
                <td>{item.transaction_id ?? "—"}</td>
                <td>{item.status}</td>
                <td style={{ minWidth: 220 }}>
                  {item.status === "PENDING" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {(CATEGORY_ACTIONS[item.category] ?? []).map((action) => (
                        <button
                          key={action}
                          className="small"
                          onClick={() => {
                            if (action === "ADD_PRICE_QUOTE") {
                              const match = item.message.match(/(\w+)\s*\(/);
                              const y = year || new Date().getFullYear();
                              setPriceForm({ itemId: item.id, symbol: match ? match[1] : "", price: "", date: `${y}-12-31` });
                            } else if (action === "CREATE_OPENING_POSITION") {
                              setOpeningForm({ itemId: item.id, symbol: "", quantity: "", costBasis: "", date: item.created_at.slice(0, 10) });
                            } else {
                              resolve.mutate({ id: item.id, action });
                            }
                          }}
                        >
                          {ACTION_LABELS[action]}
                        </button>
                      ))}
                    </div>
                  )}
                  {item.status !== "PENDING" && (
                    <span className="muted">{ACTION_LABELS[item.resolution_action ?? ""] ?? item.resolution_action}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.length === 0 && <p className="muted">Sin avisos.</p>}
      </div>

      {priceForm.itemId && (
        <div className="card" style={{ marginTop: 16 }}>
          <h4>Añadir cotización</h4>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <input placeholder="Activo" value={priceForm.symbol} onChange={(e) => setPriceForm({ ...priceForm, symbol: e.target.value.toUpperCase() })} />
            <input placeholder="Precio EUR" value={priceForm.price} onChange={(e) => setPriceForm({ ...priceForm, price: e.target.value })} />
            <input type="date" value={priceForm.date} onChange={(e) => setPriceForm({ ...priceForm, date: e.target.value })} />
            <button onClick={() => {
              const item = data.find((d) => d.id === priceForm.itemId);
              if (item) applyPrice(item);
            }}>Guardar cotización</button>
            <button className="secondary" onClick={() => setPriceForm({ symbol: "", price: "", date: "" })}>Cancelar</button>
          </div>
        </div>
      )}

      {openingForm.itemId && (
        <div className="card" style={{ marginTop: 16 }}>
          <h4>Crear posición de apertura</h4>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <input placeholder="Activo" value={openingForm.symbol} onChange={(e) => setOpeningForm({ ...openingForm, symbol: e.target.value.toUpperCase() })} />
            <input placeholder="Cantidad" value={openingForm.quantity} onChange={(e) => setOpeningForm({ ...openingForm, quantity: e.target.value })} />
            <input placeholder="Coste total EUR" value={openingForm.costBasis} onChange={(e) => setOpeningForm({ ...openingForm, costBasis: e.target.value })} />
            <input type="date" value={openingForm.date} onChange={(e) => setOpeningForm({ ...openingForm, date: e.target.value })} />
            <button onClick={() => {
              const item = data.find((d) => d.id === openingForm.itemId);
              if (item) applyOpening(item);
            }}>Crear posición</button>
            <button className="secondary" onClick={() => setOpeningForm({ symbol: "", quantity: "", costBasis: "", date: "" })}>Cancelar</button>
          </div>
        </div>
      )}
    </>
  );
}
