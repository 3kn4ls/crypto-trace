import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useTaxpayers } from "../TaxpayerContext";

interface Taxpayer {
  id: number;
  name: string;
  tax_id: string | null;
}

interface RewardPreference {
  id?: number;
  taxpayer_id: number;
  transaction_type: string;
  income_category: string;
  zero_cost_basis: boolean;
}

const REWARD_TYPES = ["STAKING_REWARD", "REFERRAL", "AIRDROP"];
const INCOME_CATEGORIES = ["RCM", "GANANCIA", "ACTIVIDAD"];

export default function Taxpayers() {
  const qc = useQueryClient();
  const { refresh } = useTaxpayers();
  const taxpayers = useQuery({
    queryKey: ["taxpayers"],
    queryFn: () => api.get("/taxpayers"),
  });

  const [name, setName] = useState("");
  const [taxId, setTaxId] = useState("");
  const [editing, setEditing] = useState<Taxpayer | null>(null);

  const create = useMutation({
    mutationFn: () => api.post("/taxpayers", { name, tax_id: taxId || null }),
    onSuccess: () => {
      setName("");
      setTaxId("");
      qc.invalidateQueries({ queryKey: ["taxpayers"] });
      refresh();
    },
  });

  const update = useMutation({
    mutationFn: () =>
      api.put(`/taxpayers/${editing!.id}`, {
        name: editing!.name,
        tax_id: editing!.tax_id,
      }),
    onSuccess: () => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["taxpayers"] });
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/taxpayers/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["taxpayers"] });
      refresh();
    },
  });

  const [prefsTaxpayer, setPrefsTaxpayer] = useState<Taxpayer | null>(null);

  const prefs = useQuery({
    queryKey: ["reward-preferences", prefsTaxpayer?.id],
    queryFn: () => api.get(`/taxpayers/${prefsTaxpayer!.id}/reward-preferences`),
    enabled: !!prefsTaxpayer,
  });

  const savePrefs = useMutation({
    mutationFn: (payload: RewardPreference[]) =>
      api.put(`/taxpayers/${prefsTaxpayer!.id}/reward-preferences`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reward-preferences", prefsTaxpayer?.id] });
    },
  });

  const ensureDefaults = (rows: RewardPreference[]): RewardPreference[] => {
    const existing = new Set(rows.map((r) => r.transaction_type));
    const defaults: RewardPreference[] = REWARD_TYPES.filter((t) => !existing.has(t)).map((t) => ({
      taxpayer_id: prefsTaxpayer!.id,
      transaction_type: t,
      income_category: t === "STAKING_REWARD" || t === "REFERRAL" ? "RCM" : "GANANCIA",
      zero_cost_basis: false,
    }));
    return [...rows, ...defaults];
  };

  const updatePref = (type: string, patch: Partial<RewardPreference>) => {
    const current = ensureDefaults((prefs.data ?? []) as RewardPreference[]);
    const next = current.map((r) => (r.transaction_type === type ? { ...r, ...patch } : r));
    savePrefs.mutate(next);
  };

  return (
    <>
      <h2>Contribuyentes</h2>

      <div className="card">
        <h3>{editing ? "Editar contribuyente" : "Nuevo contribuyente"}</h3>
        <input
          placeholder="Nombre"
          value={editing ? editing.name : name}
          onChange={(e) =>
            editing
              ? setEditing({ ...editing, name: e.target.value })
              : setName(e.target.value)
          }
        />
        <input
          placeholder="DNI / NIE (opcional)"
          value={editing ? editing.tax_id || "" : taxId}
          onChange={(e) =>
            editing
              ? setEditing({ ...editing, tax_id: e.target.value || null })
              : setTaxId(e.target.value)
          }
        />
        <div style={{ marginTop: 8 }}>
          {editing ? (
            <>
              <button onClick={() => update.mutate()}>Guardar</button>
              <button className="ghost" onClick={() => setEditing(null)} style={{ marginLeft: 8 }}>
                Cancelar
              </button>
            </>
          ) : (
            <button onClick={() => create.mutate()} disabled={!name}>Crear</button>
          )}
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Nombre</th>
              <th>DNI/NIE</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(taxpayers.data ?? []).map((t: Taxpayer) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{t.tax_id || "—"}</td>
                <td>
                  <button className="ghost" onClick={() => setEditing(t)} style={{ marginRight: 8 }}>
                    Editar
                  </button>
                  <button className="ghost" onClick={() => setPrefsTaxpayer(t)} style={{ marginRight: 8 }}>
                    Preferencias
                  </button>
                  <button className="ghost" onClick={() => remove.mutate(t.id)}>Borrar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(taxpayers.data ?? []).length === 0 && (
          <p className="muted">Sin contribuyentes. Crea al menos uno para empezar.</p>
        )}
      </div>

      {prefsTaxpayer && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="flex-between">
            <h3>Preferencias fiscales: {prefsTaxpayer.name}</h3>
            <button className="ghost" onClick={() => setPrefsTaxpayer(null)}>Cerrar</button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Tipo</th>
                <th>Categoría</th>
                <th>Base cero (descuento)</th>
              </tr>
            </thead>
            <tbody>
              {ensureDefaults((prefs.data ?? []) as RewardPreference[]).map((r) => (
                <tr key={r.transaction_type}>
                  <td>{r.transaction_type}</td>
                  <td>
                    <select
                      value={r.income_category}
                      onChange={(e) => updatePref(r.transaction_type, { income_category: e.target.value })}
                    >
                      {INCOME_CATEGORIES.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={r.zero_cost_basis}
                      onChange={(e) => updatePref(r.transaction_type, { zero_cost_basis: e.target.checked })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {savePrefs.isError && <p className="error">{String(savePrefs.error)}</p>}
        </div>
      )}
    </>
  );
}
