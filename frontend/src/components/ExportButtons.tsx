import { useState } from "react";

interface ExportButtonsProps {
  scope: "summary" | "transactions" | "model721";
  year?: string | number;
  taxpayerIds: number[];
}

export default function ExportButtons({ scope, year, taxpayerIds }: ExportButtonsProps) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const download = async (format: "csv" | "pdf") => {
    setBusy(true);
    setMsg(null);
    const params = new URLSearchParams();
    if (year !== undefined && year !== "") params.set("year", String(year));
    taxpayerIds.forEach((id) => params.append("taxpayer_ids", String(id)));
    params.set("format", format);
    const url = `/api/exports/${scope}?${params.toString()}`;

    try {
      const res = await fetch(url);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      const blob = await res.blob();
      const header = res.headers.get("content-disposition") || "";
      const match = header.match(/filename="?([^"]+)"?/);
      const filename = match?.[1] || `export_${scope}.${format}`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (err: any) {
      setMsg(`Error al exportar: ${err.message ?? err}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <button
        className="small secondary"
        onClick={() => download("csv")}
        disabled={busy}
        title="Descargar CSV"
      >
        CSV
      </button>
      <button
        className="small secondary"
        onClick={() => download("pdf")}
        disabled={busy}
        title="Descargar PDF"
      >
        PDF
      </button>
      {msg && <span className="error" style={{ fontSize: 13 }}>{msg}</span>}
    </div>
  );
}
