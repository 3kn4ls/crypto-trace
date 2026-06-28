import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export interface Taxpayer {
  id: number;
  name: string;
  tax_id: string | null;
}

interface TaxpayerContextValue {
  taxpayers: Taxpayer[];
  selectedIds: number[];
  isJoint: boolean;
  setTaxpayers: (t: Taxpayer[]) => void;
  selectSingle: (id: number) => void;
  toggleJoint: () => void;
  toggleSelection: (id: number) => void;
  setSelection: (ids: number[]) => void;
  refresh: () => Promise<void>;
}

const TaxpayerContext = createContext<TaxpayerContextValue | null>(null);

const STORAGE_KEY = "crypto_trace_selected_taxpayers";
const JOINT_KEY = "crypto_trace_joint_mode";

export function TaxpayerProvider({ children }: { children: ReactNode }) {
  const [taxpayers, setTaxpayers] = useState<Taxpayer[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [isJoint, setIsJoint] = useState(false);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/taxpayers");
    if (!res.ok) throw new Error(await res.text());
    const data: Taxpayer[] = await res.json();
    setTaxpayers(data);
    if (data.length > 0) {
      setSelectedIds((prev) => {
        const valid = prev.filter((id) => data.some((t) => t.id === id));
        return valid.length > 0 ? valid : [data[0].id];
      });
    }
  }, []);

  // Initial load from storage + API
  useEffect(() => {
    const storedIds = localStorage.getItem(STORAGE_KEY);
    const storedJoint = localStorage.getItem(JOINT_KEY);
    if (storedIds) {
      try {
        setSelectedIds(JSON.parse(storedIds));
      } catch {
        // ignore
      }
    }
    if (storedJoint) {
      setIsJoint(storedJoint === "true");
    }
    refresh();
  }, [refresh]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(selectedIds));
  }, [selectedIds]);

  useEffect(() => {
    localStorage.setItem(JOINT_KEY, String(isJoint));
  }, [isJoint]);

  const selectSingle = useCallback((id: number) => {
    setIsJoint(false);
    setSelectedIds([id]);
  }, []);

  const toggleJoint = useCallback(() => {
    setIsJoint((prev) => !prev);
  }, []);

  const toggleSelection = useCallback((id: number) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) {
        const next = prev.filter((x) => x !== id);
        return next.length > 0 ? next : prev;
      }
      return [...prev, id];
    });
  }, []);

  const setSelection = useCallback((ids: number[]) => {
    setSelectedIds(ids.length > 0 ? ids : []);
  }, []);

  const value = useMemo(
    () => ({
      taxpayers,
      selectedIds,
      isJoint,
      setTaxpayers,
      selectSingle,
      toggleJoint,
      toggleSelection,
      setSelection,
      refresh,
    }),
    [taxpayers, selectedIds, isJoint, refresh, selectSingle, toggleJoint, toggleSelection, setSelection]
  );

  return (
    <TaxpayerContext.Provider value={value}>{children}</TaxpayerContext.Provider>
  );
}

export function useTaxpayers() {
  const ctx = useContext(TaxpayerContext);
  if (!ctx) throw new Error("useTaxpayers must be used within TaxpayerProvider");
  return ctx;
}

export function buildTaxpayerQuery(ids: number[]): string {
  return ids.map((id) => `taxpayer_ids=${encodeURIComponent(id)}`).join("&");
}
