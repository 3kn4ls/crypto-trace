# Plan inicial — Fase 1: Crypto-Trace (España, IRPF · FIFO)

> Plan de arquitectura aprobado para la primera fase. Se conserva como referencia del diseño.
> El estado de ejecución y la tarea pendiente están en [`ESTADO.md`](./ESTADO.md).

## Contexto
Aplicación para el **control fiscal de criptomonedas** orientada a la **declaración de la renta (IRPF)**:

1. **Modelo de datos** que registra todos los movimientos y calcula, por **método FIFO** (criterio DGT),
   las ganancias/pérdidas patrimoniales y **cuánto pagar** por ejercicio.
2. **Conectores** que importan **Excel** de plataformas (`CRYPTO.COM`, `REVOLUT_EXCHANGE`, …) y los
   normalizan a un **formato canónico** interno (arquitectura *pluggable*).
3. Gestión de **años cerrados** (bloqueo + arrastre FIFO) y **resúmenes de años pasados** sin detalle.
4. **Cuadros de mando y gráficos** por año fiscal, cripto, evolución de cartera, etc.
5. **Modelo 721** (informativa de criptos en el extranjero).
6. **Cimientos Fase 2**: simulaciones ("¿y si vendo X hoy?").

> Aviso: herramienta de apoyo, **no asesoramiento fiscal**. Calificaciones discutibles (staking,
> permutas, airdrops) modeladas como **configurables**.

## Decisiones (confirmadas con el usuario)
- **Backend**: Python + **FastAPI**, **SQLAlchemy 2.0**, **Pydantic v2**.
- **Persistencia**: **SQLite** local, monousuario, sin login.
- **Frontend**: **React + TypeScript** (Vite) + **TanStack Query** + **Recharts**.
- **Excel**: **openpyxl**.
- **Dinero/cantidades**: SIEMPRE `Decimal`. **Nunca `float`**.
- **Alcance fiscal Fase 1**: completo — ganancias patrimoniales + rendimientos (staking/airdrops/referidos)
  + informativo **Modelo 721**.
- **Tests**: `pytest` con casos deterministas.

> Nota de ejecución: el esquema se crea con `Base.metadata.create_all` + seed al arrancar
> (Alembic queda como mejora futura).

## Estructura de proyecto
```
crypto-trace/
├── backend/app/
│   ├── main.py                  # arranque FastAPI, montaje de routers
│   ├── core/                    # config, db (SQLite), money (Decimal)
│   ├── models/                  # ORM + enums + tipos (DecimalText)
│   ├── schemas/                 # Pydantic (entrada API)
│   ├── connectors/              # base + registry + crypto_com + revolut + mappings/*.yaml
│   ├── services/                # fifo_engine, tax_calculator, import_service, ledger,
│   │                            # recompute, fiscal_year_service, model721_service,
│   │                            # pricing_service, reporting_service
│   ├── tax/                     # brackets por año
│   └── api/                     # routers: meta, accounts, imports, transactions, fiscal, reports
├── backend/tests/
└── frontend/src/                # pages/ (Dashboard, Import, Transactions, FiscalYears, Model721)
```

## Modelo de datos (núcleo)
| Entidad | Propósito | Campos clave |
|---|---|---|
| **Asset** | Catálogo de activos | `symbol`, `name`, `kind` (CRYPTO/STABLECOIN/FIAT), `coingecko_id`, `decimals` |
| **Account** | Cuenta/wallet | `name`, `platform`, `type`, `is_abroad` (721), `country` |
| **ImportBatch** | Cada carga de Excel | `connector`, `filename`, `file_hash`, `row_count`, `status`, `errors_json` |
| **Transaction** | Movimiento canónico | `type`, `asset_in/amount_in`, `asset_out/amount_out`, `fee_*`, `eur_value`, `external_id`, `fiscal_year` |
| **Lot** | Lote FIFO | `asset_id`, `acquired_at`, `qty_original`, `qty_remaining`, `unit_cost_eur`, `is_carryforward` |
| **Disposal** | Enajenación gravable | `asset_id`, `disposed_at`, `quantity`, `proceeds_eur`, `cost_basis_eur`, `gain_loss_eur`, `disposal_kind` |
| **LotConsumption** | Casación FIFO | `disposal_id`, `lot_id`, `qty_consumed`, `cost_basis_eur`, `proceeds_eur`, `gain_loss_eur`, `holding_days` |
| **IncomeEvent** | Rendimiento | `asset_id`, `received_at`, `eur_value`, `category` (RCM/GANANCIA/ACTIVIDAD), `fiscal_year` |
| **FiscalYear** | Ejercicio | `year`, `status` (OPEN/CLOSED), `closed_at` |
| **FiscalYearSummary** | Snapshot inmutable | `net_gain_eur`, `total_gains/losses`, `income_total`, `savings_base`, `tax_due_eur`, `source` |
| **TaxBracket** | Tramos del ahorro por año | `year`, `from_eur`, `to_eur`, `rate` |
| **PriceQuote** | Precio histórico EUR | `asset_id`, `date`, `price_eur`, `source` |

Notas: las **stablecoins son cripto** (swap a USDT = permuta gravable); un `IncomeEvent` crea también un
`Lot` con coste = valor de mercado en recepción; `external_id` + `file_hash` → **dedup idempotente**.

## Motor FIFO (`services/fifo_engine.py`)
Función **pura y determinista** sobre eventos ordenados (reutilizable en Fase 2). Orden cronológico
estricto; FIFO **por tipo de cripto**. Adquisición → crea `Lot`; enajenación → consume lotes desde el más
antiguo (con `LotConsumption`); **permuta** = enajenación de la pata entregada (valor de mercado EUR) +
nuevo `Lot` para la recibida; consumo parcial y aviso por saldo insuficiente.

## Cálculo de impuestos (`services/tax_calculator.py`)
Base del **ahorro**: netar ganancias/pérdidas, compensación cruzada con RCM (25%), **tramos progresivos**
por año (`tax/brackets.py`: 2024 → 19/21/23/27/28 %). Rendimientos clasificados por `IncomeCategory`.

## Conectores (`connectors/`) — traductores de formato
Un conector **solo traduce** el Excel de cada exchange a `CanonicalTransaction` (agnóstico de la
plataforma). El resto del sistema trabaja **solo** sobre el modelo canónico. Mapeo de columnas y tipos en
**YAML** (`connectors/mappings/*.yaml`): ajustar a ficheros reales = editar YAML, no código. Añadir un
exchange = añadir un conector, sin tocar la lógica fiscal.

## Años cerrados / Modelo 721 / Reporting
- **Cerrar año**: `status=CLOSED`, bloqueo de edición y `FiscalYearSummary` congelado + arrastre FIFO.
  Años pasados sin detalle: resumen manual + posiciones de apertura.
- **721**: saldos a 31/12 por cuenta/activo en EUR, cuentas `is_abroad`, umbral 50.000 €.
- **Reporting**: agregados por año fiscal, por cripto, cartera y obligación 721 para los gráficos.

## Cimientos Fase 2 (simulaciones)
El motor FIFO es puro → un futuro `SimulationService` clona el estado de lotes y aplica enajenaciones
hipotéticas sin persistir.

## Orden de implementación (hitos)
1. Andamiaje backend (FastAPI, core, healthcheck).
2. Modelo de datos (ORM + Pydantic + seed de Assets y TaxBracket).
3. Motor FIFO + tax_calculator con **tests deterministas**.
4. Framework de conectores + import_service + CRYPTO_COM / REVOLUT_EXCHANGE (tests con Excel de ejemplo).
5. Años fiscales + Modelo 721.
6. API de reporting + frontend.
7. README + arranque.

## Verificación
- `pytest backend/tests` (FIFO, impuestos, import end-to-end, API).
- Importar Excel de ejemplo y comprobar `Transaction`/`Lot`/`Disposal` + idempotencia.
- Cálculo anual: ganancia neta, tramos y total a pagar.
- Arranque: `uvicorn` + `vite dev`; subir Excel y ver gráficos.
- 721: cuenta `is_abroad` con saldo > 50.000 € activa el indicador.
