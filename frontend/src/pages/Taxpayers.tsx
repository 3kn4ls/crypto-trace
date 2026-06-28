import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useTaxpayers } from "../TaxpayerContext";

interface Taxpayer {
  id: number;
  name: string;
  tax_id: string | null;
}

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
    </>
  );
}
