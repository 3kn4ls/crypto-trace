# Crypto-Trace — Monitorización fiscal de criptomonedas (IRPF · FIFO)

Aplicación local para llevar el **control fiscal de criptomonedas** de cara a la
**declaración de la renta (IRPF) española**: registra todos los movimientos,
calcula ganancias/pérdidas patrimoniales por **método FIFO** (criterio DGT),
estima **cuánto pagar** por ejercicio, soporta **Modelo 721** y deja preparada
la **Fase 2** (simulaciones).

> ⚠️ Herramienta de apoyo al cálculo, **no es asesoramiento fiscal**. Algunas
> calificaciones (staking, airdrops, permutas) tienen interpretaciones de la DGT
> que pueden cambiar; por eso son configurables.

## Arquitectura

```
backend/   FastAPI + SQLAlchemy 2.0 + SQLite   (motor FIFO, impuestos, conectores, API)
frontend/  React + TypeScript + Vite + Recharts (panel, importación, informes)
```

- **Monousuario, local**. Base de datos SQLite en `backend/data/crypto_trace.db`.
- **Dinero exacto**: todo en `Decimal`; las columnas se guardan como texto
  (`DecimalText`) para evitar el redondeo en coma flotante de SQLite.

### Modelo de datos (núcleo)

`Asset`, `Account`, `Transaction` (movimiento canónico), `Lot` (lotes FIFO),
`Disposal` + `LotConsumption` (enajenaciones y su casación FIFO), `IncomeEvent`
(staking/airdrop/referidos), `FiscalYear` / `FiscalYearSummary`, `TaxBracket`,
`PriceQuote`, `ImportBatch`. Ver `backend/app/models/orm.py`.

### Conectores (traductores de formato)

Un conector **solo traduce** el Excel de cada exchange al modelo canónico
`CanonicalTransaction`, **agnóstico de la plataforma**. El motor FIFO, los
impuestos y los informes trabajan solo sobre el modelo canónico. Añadir un
exchange = añadir un conector, sin tocar la lógica fiscal.

- Conectores: `CRYPTO_COM`, `REVOLUT_EXCHANGE` (en `backend/app/connectors/`).
- El mapeo de columnas y la traducción de tipos viven en YAML
  (`backend/app/connectors/mappings/*.yaml`): **provisionales**, ajústalos a tus
  ficheros reales sin tocar código.

### Motor FIFO e impuestos

- `services/fifo_engine.py`: **puro y determinista**, sobre eventos en memoria
  (reutilizable en la Fase 2 para simulaciones). FIFO por activo; permutas
  cripto→cripto = enajenación + nueva adquisición a valor de mercado.
- `services/tax_calculator.py`: base imponible del **ahorro**, compensación de
  ganancias/pérdidas y compensación cruzada con RCM (25%), tramos progresivos
  por año (`tax/brackets.py`).

## Puesta en marcha

### Backend

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000  (docs en /docs)
```

La base de datos se crea y se siembra (activos + tramos) al arrancar.

### Frontend

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173  (proxy /api -> :8000)
```

### Tests

```bash
cd backend && . .venv/bin/activate && pytest -q
```

Cubren el motor FIFO (venta simple, permuta, multi-lote parcial, saldo
insuficiente, orden cronológico), el cálculo de impuestos (tramos, compensación)
y el flujo de importación end-to-end (idempotencia) y la API.

## Flujo de uso

1. **Importar Excel**: crea una cuenta (marca *en el extranjero* para el 721),
   elige conector y sube el fichero. Se normaliza, deduplica y recalcula el FIFO.
2. **Transacciones**: revisa los movimientos normalizados.
3. **Años fiscales**: consulta el detalle (ganancias, base del ahorro, tramos,
   impuesto) y **cierra** el año (congela el resumen). Puedes cargar un
   **resumen manual** o **posiciones de apertura** para años pasados sin detalle.
4. **Modelo 721**: saldos a 31/12 valorados en EUR e indicador de obligación.
   Carga cotizaciones en `POST /api/prices` para valorar.
5. **Panel**: gráficos por año fiscal y distribución de cartera.

## Endpoints principales (`/api`)

`/health` · `/connectors` · `/assets` · `/prices` · `/accounts` · `/imports` ·
`/transactions` · `/fiscal-years` · `/fiscal-years/{año}/tax|close|reopen` ·
`/fiscal-years/manual-summary|opening-position` · `/reports/portfolio|by-asset|yearly` ·
`/reports/model721/{año}`.

## Fase 2 (preparada, no implementada)

El motor FIFO es puro: un `SimulationService` podrá clonar el estado de lotes y
aplicar enajenaciones hipotéticas ("¿cuánto pagaría si vendo X hoy?") sin
persistir nada.
