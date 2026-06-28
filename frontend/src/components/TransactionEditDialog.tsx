import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";

interface Transaction {
  id: number;
  type: string;
  cost_basis_eur: string | null;
  is_internal_transfer: boolean;
  notes: string | null;
}

export default function TransactionEditDialog({
  transaction,
  onClose,
}: {
  transaction: Transaction;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [costBasis, setCostBasis] = useState(transaction.cost_basis_eur ?? "");
  const [isInternal, setIsInternal] = useState(transaction.is_internal_transfer);
  const [notes, setNotes] = useState(transaction.notes ?? "");

  const update = useMutation({
    mutationFn: () =>
      api.patch(`/transactions/${transaction.id}`, {
        cost_basis_eur: costBasis.trim() ? costBasis : null,
        is_internal_transfer: isInternal,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["reviews"] });
      onClose();
    },
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Editar transacción #{transaction.id}</h3>
          <button className="close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <div style={{ marginBottom: 12 }}>
            <strong>Tipo:</strong> {transaction.type}
          </div>
          <label style={{ display: "block", marginBottom: 12 }}>
            Coste base explícito (EUR)
            <input
              type="text"
              value={costBasis}
              onChange={(e) => setCostBasis(e.target.value)}
              placeholder="Solo DEPOSIT / aperturas"
              style={{ width: "100%" }}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={isInternal}
              onChange={(e) => setIsInternal(e.target.checked)}
            />
            Transferencia interna / entre cuentas propias
          </label>
          <label style={{ display: "block", marginBottom: 12 }}>
            Notas
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              style={{ width: "100%" }}
            />
          </label>
          {update.isError && <p className="error">{String(update.error)}</p>}
          <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
            <button className="secondary" onClick={onClose}>Cancelar</button>
            <button onClick={() => update.mutate()} disabled={update.isPending}>
              {update.isPending ? "Guardando..." : "Guardar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
