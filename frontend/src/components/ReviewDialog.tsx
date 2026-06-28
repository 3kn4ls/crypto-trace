import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { api } from "../api";

const CATEGORIES: Record<string, string> = {
  P2P_TRANSFER: "P2P con tercero",
  REVERSAL: "Reversión",
  INSUFFICIENT_BALANCE: "Saldo insuficiente",
  MISSING_PRICE: "Precio ausente",
  MANUAL_REVIEW: "Revisión manual",
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

export default function ReviewDialog({
  transactionId,
  onClose,
}: {
  transactionId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [priceForm, setPriceForm] = useState({ symbol: "", price: "", date: "" });
  const [openingForm, setOpeningForm] = useState({ symbol: "", quantity: "", costBasis: "", date: "" });
  const [activeForm, setActiveForm] = useState<"price" | "opening" | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["reviews", "transaction", transactionId],
    queryFn: () => api.get(`/reviews?transaction_id=${transactionId}`),
  });

  const items: ReviewItem[] = data ?? [];
  const pending = items.filter((i) => i.status === "PENDING");

  const resolve = useMutation({
    mutationFn: ({ id, action, noteText, payload }: { id: number; action: string; noteText: string; payload?: any }) =>
      api.post(`/reviews/${id}/resolve`, { action, note: noteText || null, payload }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      setActiveForm(null);
      setPriceForm({ symbol: "", price: "", date: "" });
      setOpeningForm({ symbol: "", quantity: "", costBasis: "", date: "" });
      if (pending.length === 1) onClose();
    },
  });

  const revert = useMutation({
    mutationFn: (id: number) => api.post(`/reviews/${id}/revert`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });

  useEffect(() => {
    if (items.length > 0) {
      const first = items[0];
      const yearMatch = first.message.match(/31\/12\/(\d{4})/);
      const year = yearMatch ? yearMatch[1] : new Date().getFullYear().toString();
      const assetMatch = first.message.match(/(\w+)\s*\(/);
      setPriceForm((f) => ({ ...f, symbol: assetMatch ? assetMatch[1] : "", date: `${year}-12-31` }));
      setOpeningForm((f) => ({ ...f, symbol: assetMatch ? assetMatch[1] : "", date: first.created_at.slice(0, 10) }));
    }
  }, [items.length]);

  const handleAction = (item: ReviewItem, action: string) => {
    if (action === "ADD_PRICE_QUOTE") {
      setActiveForm("price");
      return;
    }
    if (action === "CREATE_OPENING_POSITION") {
      setActiveForm("opening");
      return;
    }
    resolve.mutate({ id: item.id, action, noteText: note });
  };

  const applyPrice = (item: ReviewItem) => {
    resolve.mutate({
      id: item.id,
      action: "ADD_PRICE_QUOTE",
      noteText: note,
      payload: {
        asset_symbol: priceForm.symbol,
        price_eur: priceForm.price,
        date: priceForm.date,
      },
    });
  };

  const applyOpening = (item: ReviewItem) => {
    resolve.mutate({
      id: item.id,
      action: "CREATE_OPENING_POSITION",
      noteText: note,
      payload: {
        asset_symbol: openingForm.symbol,
        quantity: openingForm.quantity,
        cost_basis_eur: openingForm.costBasis,
        acquired_at: openingForm.date,
      },
    });
  };

  const pendingCount = pending.length;
  const resolvedCount = items.length - pendingCount;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal review-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Resolver avisos de transacción #{transactionId}</h3>
          <button className="close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          {isLoading && <p className="muted">Cargando...</p>}
          {!isLoading && items.length === 0 && <p className="muted">No hay avisos para esta transacción.</p>}

          {!isLoading && items.length > 0 && (
            <div className="review-summary">
              <span className={`badge ${pendingCount > 0 ? "pending" : "resolved"}`}>
                {pendingCount} pendiente{pendingCount !== 1 ? "s" : ""}
              </span>
              {resolvedCount > 0 && (
                <span className="badge resolved">
                  {resolvedCount} resuelto{resolvedCount !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          )}

          {items.map((item) => (
            <div key={item.id} className={`review-card ${item.status === "PENDING" ? "pending" : "resolved"}`}>
              <div className="review-meta">
                <span>{CATEGORIES[item.category] ?? item.category}</span>
                <span className={`badge ${item.status === "PENDING" ? "pending" : "resolved"}`}>
                  {item.status === "PENDING" ? "Pendiente" : "Resuelto"}
                </span>
                <span className="muted">{item.severity}</span>
              </div>
              <p>{item.message}</p>
              {item.status !== "PENDING" ? (
                <>
                  <div className="resolution-info">
                    <strong>Resuelto:</strong>{" "}
                    {ACTION_LABELS[item.resolution_action ?? ""] ?? item.resolution_action ?? "Sin acción"}
                    {item.resolution_note && (
                      <span className="resolution-note"> · {item.resolution_note}</span>
                    )}
                  </div>
                  <div className="review-actions" style={{ marginTop: 10 }}>
                    <button
                      className="small secondary"
                      onClick={() => revert.mutate(item.id)}
                      disabled={revert.isPending}
                    >
                      {revert.isPending ? "Revirtiendo..." : "Cancelar resolución"}
                    </button>
                  </div>
                  <p className="muted revert-hint">
                    Cancelar vuelve a dejar el aviso pendiente. Si la acción anterior creó datos (p.ej. una cotización o una posición de apertura), deberás ajustarlos aparte.
                  </p>
                </>
              ) : (
                <>
                  <div className="review-actions">
                    {(CATEGORY_ACTIONS[item.category] ?? []).map((action) => (
                      <button
                        key={action}
                        className="small action"
                        onClick={() => handleAction(item, action)}
                        disabled={resolve.isPending}
                      >
                        {ACTION_LABELS[action]}
                      </button>
                    ))}
                  </div>

                  {activeForm === "price" && (
                    <div className="inline-form">
                      <input
                        placeholder="Activo"
                        value={priceForm.symbol}
                        onChange={(e) => setPriceForm({ ...priceForm, symbol: e.target.value.toUpperCase() })}
                      />
                      <input
                        placeholder="Precio EUR"
                        value={priceForm.price}
                        onChange={(e) => setPriceForm({ ...priceForm, price: e.target.value })}
                      />
                      <input
                        type="date"
                        value={priceForm.date}
                        onChange={(e) => setPriceForm({ ...priceForm, date: e.target.value })}
                      />
                      <button onClick={() => applyPrice(item)}>Guardar cotización</button>
                    </div>
                  )}

                  {activeForm === "opening" && (
                    <div className="inline-form">
                      <input
                        placeholder="Activo"
                        value={openingForm.symbol}
                        onChange={(e) => setOpeningForm({ ...openingForm, symbol: e.target.value.toUpperCase() })}
                      />
                      <input
                        placeholder="Cantidad"
                        value={openingForm.quantity}
                        onChange={(e) => setOpeningForm({ ...openingForm, quantity: e.target.value })}
                      />
                      <input
                        placeholder="Coste total EUR"
                        value={openingForm.costBasis}
                        onChange={(e) => setOpeningForm({ ...openingForm, costBasis: e.target.value })}
                      />
                      <input
                        type="date"
                        value={openingForm.date}
                        onChange={(e) => setOpeningForm({ ...openingForm, date: e.target.value })}
                      />
                      <button onClick={() => applyOpening(item)}>Crear posición</button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}

          <label style={{ display: "block", marginTop: 16 }}>
            Nota de resolución
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} style={{ width: "100%" }} />
          </label>
        </div>
      </div>
    </div>
  );
}
