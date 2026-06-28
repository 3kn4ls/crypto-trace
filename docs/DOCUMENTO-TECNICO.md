# Documento técnico — Crypto-Trace

> Aplicación local para la monitorización fiscal de criptomonedas (IRPF España, método FIFO).
> Versión del documento: 0.1.0 · Rama: `claude/wonderful-gauss-vbd72u` · Fecha: 2026-06-24.

## 1. Resumen ejecutivo

**Crypto-Trace** es una aplicación **local-first multi-contribuyente** que permite:

- Gestionar varios contribuyentes sin autenticación (todo en la misma sesión local).
- Seleccionar un contribuyente o varios para simular declaraciones de renta conjuntas.
- Importar extractos de exchanges (CSV/XLSX) mediante conectores configurables.
- Normalizar cada movimiento a un modelo canónico agnóstico de la plataforma.
- Calcular ganancias/pérdidas patrimoniales por el **método FIFO** (criterio de la DGT).
- Estimar el impuesto de la **base del ahorro** por ejercicio (IRPF), individual o conjunto.
- Gestionar años fiscales abiertos/cerrados, resúmenes manuales y posiciones de apertura **por contribuyente**.
- Generar el informativo **Modelo 721** para criptomonedas en el extranjero.
- Ofrecer un panel web con gráficos de evolución fiscal y distribución de cartera.

> ⚠️ La aplicación es una **herramienta de apoyo al cálculo**, no asesoramiento fiscal. Las calificaciones de ciertos movimientos (staking, airdrops, cashback, regalos, permutas) son configurables y deben ser validadas por el usuario o su asesor.

## 2. Stack tecnológico

| Capa | Tecnología | Motivación |
|------|-----------|------------|
| Backend | Python 3.11 + FastAPI + Pydantic v2 | Tipado, validación, autodocumentación OpenAPI, alto rendimiento para carga IO-bound. |
| ORM / persistencia | SQLAlchemy 2.0 + SQLite | Modelado relacional declarativo, sin dependencia de servidor de base de datos. |
| Dinero y cantidades | `decimal.Decimal` (nunca `float`) | Evita redondeo en coma flotante; crítico para cálculos fiscales. |
| Excel / CSV | `openpyxl` + `csv` | Lectura de exportaciones de exchanges; auto-detección XLSX vs CSV por contenido. |
| Precios históricos | `requests` + CoinGecko public API | Carga automática de cierres de 31/12 para valorar cartera y Modelo 721. |
| Frontend | React 18 + TypeScript + Vite | SPA ligera con recarga rápida en desarrollo. |
| Estado servidor | TanStack Query | Caché, invalidación y sincronización con la API. |
| Gráficos | Recharts | Visualizaciones simples de serie temporal y distribución. |
| Contenedores | Docker + docker-compose + nginx | Entorno reproducible; nginx sirve el SPA y proxy a `/api`. |
| Tests | pytest + TestClient de FastAPI | Tests unitarios del motor fiscal y end-to-end de la API HTTP. |

## 3. Estructura del repositorio

```
crypto-trace/
├── backend/
│   ├── app/
│   │   ├── main.py                 # Punto de entrada FastAPI y lifespan (init + seed)
│   │   ├── core/                   # Config, base de datos, utilidades Decimal, seed
│   │   ├── models/                 # ORM SQLAlchemy, enums, tipos personalizados
│   │   ├── schemas/                # Esquemas Pydantic para la API
│   │   ├── connectors/             # Framework + conectores + mappings YAML
│   │   ├── services/               # Lógica de negocio pura e impura
│   │   ├── tax/                    # Tramos impositivos por año
│   │   └── api/                    # Routers REST
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api.ts                  # Wrapper fetch (GET/POST/PUT/DELETE)
│   │   ├── App.tsx                 # Rutas, layout y selector global de contribuyente
│   │   ├── main.tsx                # Bootstrap React + QueryClient + Router + TaxpayerProvider
│   │   ├── TaxpayerContext.tsx     # Estado global de contribuyentes seleccionados (localStorage)
│   │   ├── pages/                  # Dashboard, Import, Transactions, FiscalYears, Model721, Taxpayers
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── docs/                           # Documentación de proyecto
└── informes/                       # Datos fiscales personales (ignorados por git)
```

## 4. Arquitectura general

### 4.1 Principios de diseño

1. **Single source of truth**: las `Transaction` canónicas son la única fuente de verdad. Todo el estado derivado (lotes, enajenaciones, rentas) se recalcula a partir de ellas.
2. **Separación de responsabilidades**: los conectores **solo traducen** formatos de exchange al modelo canónico. El motor FIFO, la fiscalidad y los informes no conocen formatos externos.
3. **Motor fiscal puro**: `fifo_engine.py` es determinista, libre de dependencias de base de datos y reutilizable para simulaciones (Fase 2).
4. **Dinero exacto**: todo uso de `Decimal`; almacenamiento en SQLite como `TEXT` mediante `DecimalText` para evitar redondeo.
5. **Privacidad por defecto**: datos personales en `informes/` (`.gitignore`); base de datos SQLite local; sin autenticación ni telemetría.

### 4.2 Flujo de datos de alto nivel

```
[Export CSV/XLSX de exchange]
           │
           ▼
[Connector específico + mapping YAML]
           │
           ▼
[CanonicalTransaction] ─────┐
           │                │
           ▼                ▼
   [import_service]   [dedup / validación]
           │                │
           └───────┬────────┘
                   ▼
        [Persist Transaction en SQLite]
                   │
                   ▼
        [recompute_all: ledger → FIFO engine]
                   │
                   ▼
        [Lot, Disposal, LotConsumption, IncomeEvent]
                   │
                   ▼
        [tax_calculator, reporting, model721]
                   │
                   ▼
        [API REST → Frontend]
```

## 5. Modelo de datos

La base de datos se crea automáticamente al arrancar (`Base.metadata.create_all`) y se siembra con activos y tramos impositivos por defecto.

### 5.1 Entidades principales

| Entidad | Tabla | Propósito |
|---------|-------|-----------|
| `Taxpayer` | `taxpayers` | Contribuyente (`name`, `tax_id` opcional). Se crea uno por defecto ("Principal") al inicializar la base de datos para no romper datos existentes. |
| `Asset` | `assets` | Catálogo de activos (`BTC`, `ETH`, `EUR`, `USDT`…). `kind` distingue `CRYPTO`, `STABLECOIN`, `FIAT`. |
| `Account` | `accounts` | Cuentas o wallets de un contribuyente (`taxpayer_id`). `is_abroad` activa la consideración para el Modelo 721. |
| `ImportBatch` | `import_batches` | Registro de cada carga: conector, `file_hash`, contribuyente (`taxpayer_id`), conteos, errores. |
| `Transaction` | `transactions` | Movimiento canónico normalizado. Punto de entrada único del motor fiscal. Vinculado a contribuyente, cuenta e import (`source`). |
| `Lot` | `lots` | Lote FIFO creado por una adquisición de un contribuyente. En la Fase 1 el FIFO es global por contribuyente (no por cuenta), por lo que `account_id` se guarda como `None` y los flags `is_carryforward` / `is_opening` permanecen en `False`; están reservados para futuras mejoras. |
| `Disposal` | `disposals` | Enajenación gravable (venta, permuta, gasto) de un contribuyente. |
| `LotConsumption` | `lot_consumptions` | Línea de casación FIFO: cuánto de un lote consumió una enajenación. |
| `IncomeEvent` | `income_events` | Renta percibida al valor de mercado (staking, airdrop, referidos, reversos) de un contribuyente. |
| `FiscalYear` | `fiscal_years` | Estado abierto/cerrado de un ejercicio **por contribuyente**. |
| `FiscalYearSummary` | `fiscal_year_summaries` | Snapshot inmutable del resultado fiscal (calculado o manual) **por contribuyente**. |
| `TaxBracket` | `tax_brackets` | Tramos marginales de la base del ahorro por año. |
| `PriceQuote` | `price_quotes` | Precio histórico en EUR para valoraciones. |
| `ReviewItem` | `review_items` | Aviso de revisión generado por conector, motor FIFO o informes. Vinculado a transacción y contribuyente; estados `PENDING`, `RESOLVED`, `IGNORED`. |

### 5.2 Almacenamiento de decimales

SQLite no tiene tipo `DECIMAL` nativo y SQLAlchemy `Numeric` redondea a `float`. Para evitarlo se usa `DecimalText` (`backend/app/models/types.py`):

```python
class DecimalText(TypeDecorator):
    impl = String
    def process_bind_param(self, value, dialect):
        return format(to_decimal(value), "f")   # sin notación científica
    def process_result_value(self, value, dialect):
        return Decimal(value)
```

Todas las cantidades, importes EUR y costes unitarios se almacenan como texto. Las agregaciones fiscales se realizan en Python con `Decimal`.

### 5.3 Convenciones de `Transaction`

- `taxpayer_id`: contribuyente titular de la operación.
- `account_id`: cuenta origen del exchange/wallet.
- `asset_in` / `amount_in`: lo recibido (lado adquisición).
- `asset_out` / `amount_out`: lo entregado (lado enajenación).
- `eur_value`: valor de mercado en EUR de la operación, usado para valorar permutas y rentas.
- `external_id`: identificador del exchange o sintético (hash de contenido) para deduplicación.
- `fiscal_year`: año impositivo derivado de `timestamp.year`.
- `source`: origen de la importación, copiado desde `ImportBatch.connector` (p. ej. `CRYPTO_COM`, `REVOLUT_EXCHANGE`).

Restricciones de unicidad:
- `uq_accounts_taxpayer_name` sobre `(taxpayer_id, name)`.
- `uq_tx_taxpayer_account_external` sobre `(taxpayer_id, account_id, external_id)`.
- `uq_fiscal_year_taxpayer_year` sobre `(taxpayer_id, year)`.
- `uq_fiscal_year_summary_taxpayer_year` sobre `(taxpayer_id, year)`.

### 5.4 Enums canónicos

Definidos en `backend/app/models/enums.py`:

| Enum | Valores | Uso |
|------|---------|-----|
| `AssetKind` | `CRYPTO`, `STABLECOIN` (se grava como cripto), `FIAT` | Clasificación del activo. |
| `AccountPlatform` | `CRYPTO_COM`, `REVOLUT`, `MANUAL`, `WALLET` | Plataforma asociada a una cuenta. |
| `AccountType` | `EXCHANGE`, `WALLET` | Tipo de cuenta. |
| `TransactionType` | `BUY`, `SELL`, `SWAP`, `DEPOSIT`, `WITHDRAWAL`, `STAKING_REWARD`, `AIRDROP`, `REFERRAL`, `SPEND`, `FEE`, `TRANSFER`, `REVERSAL` | Tipos canónicos de movimiento. |
| `DisposalKind` | `SALE`, `SWAP`, `SPEND` | Naturaleza de la enajenación. |
| `IncomeCategory` | `RCM`, `GANANCIA`, `ACTIVIDAD` | Clasificación fiscal de la renta. |
| `FiscalYearStatus` | `OPEN`, `CLOSED` | Estado del ejercicio. |
| `SummarySource` | `COMPUTED`, `MANUAL_SUMMARY` | Origen del resumen fiscal. |
| `ImportStatus` | `OK`, `PARTIAL`, `FAILED` | Resultado de una importación. |

### 5.5 FIFO global y campos reservados de `Lot`

En la Fase 1 el motor FIFO es **global por contribuyente**: las adquisiciones de cada contribuyente se procesan en colas separadas; dentro de un mismo contribuyente, todas las adquisiciones del mismo activo se apilan en una única cola independientemente de la cuenta origen. Esto simplifica el cálculo y es válido cuando un contribuyente mantiene la titularidad del activo entre sus propias wallets/exchanges.

`recompute.py` propaga `taxpayer_id` desde `Transaction` a `Lot`, `Disposal` e `IncomeEvent`, guarda `Lot.account_id = None` y deja `is_carryforward` e `is_opening` a `False`. Estos campos están reservados para futuras extensiones:

- `account_id`: permitir FIFO separado por cuenta cuando sea necesario.
- `is_carryforward`: marcar lotes arrastrados desde un ejercicio cerrado.
- `is_opening`: identificar posiciones de apertura manuales en el flujo FIFO.

## 6. Motor FIFO (`services/fifo_engine.py`)

### 6.1 Diseño puro

El motor es una función pura `run_fifo(moves: list[LedgerMove]) -> EngineResult` que:

1. Ordena los movimientos por `(timestamp, seq)`.
2. Mantiene una cola FIFO por `asset_id`.
3. Procesa adquisiciones (`ACQUIRE`), enajenaciones (`DISPOSE`) y retiradas sin efecto fiscal (`REMOVE`).

### 6.2 Estructuras clave

```python
class LedgerMove:
    seq: int
    timestamp: datetime
    asset_id: int
    move: MoveType          # ACQUIRE | DISPOSE | REMOVE
    quantity: Decimal
    eur: Decimal            # coste total o contraprestación neta
    ref: int | None         # id de Transaction origen
    disposal_kind: DisposalKind | None
```

```python
class EngineDisposal:
    ref: int | None
    asset_id: int
    disposed_at: datetime
    quantity: Decimal
    proceeds_eur: Decimal
    cost_basis_eur: Decimal
    gain_loss_eur: Decimal
    disposal_kind: DisposalKind
    consumptions: list[EngineConsumption]
```

### 6.3 Comportamiento del matching

- **FIFO estricto por activo**: se consume siempre desde el lote más antiguo.
- **Consumo parcial**: un lote puede consumirse parcialmente; el resto permanece en la cola.
- **Saldo insuficiente**: si no hay lotes suficientes, la parte faltante se enajena con coste 0 (conservador) y se emite un `warning`.
- **Ajuste de céntimos**: cualquier desviación por redondeo se absorbe en la última línea de consumo para que la suma de contraprestaciones coincida exactamente con el total.
- **Permutas cripto→cripto**: el caller (`ledger.py`) descompone un `SWAP` en un `DISPOSE` de la pata entregada + un `ACQUIRE` de la pata recibida. Ambas se valoran al mismo valor de mercado EUR; si la operación incluye comisiones en fiat, éstas se imputan a la contraprestación de la pata de enajenación (`market - fee_eur`), mientras que la adquisición se registra al valor de mercado completo.
- **Stablecoins**: se tratan como cripto; un swap a `USDT` es una permuta gravable.

## 7. Puente contable (`services/ledger.py`)

`build_ledger(transactions)` traduce las `Transaction` del ORM a `LedgerMove` e `IncomeSpec`:

| Tipo canónico | Efecto en el motor | Efecto fiscal |
|---------------|-------------------|---------------|
| `BUY` | `ACQUIRE` de cripto | Adquisición con coste = EUR pagado + comisiones en fiat. |
| `SELL` / `SPEND` | `DISPOSE` de cripto | Enajenación; contraprestación = EUR recibido menos comisiones en fiat. |
| `SWAP` | `DISPOSE` pata out + `ACQUIRE` pata in | Permuta gravable a valor de mercado. |
| `STAKING_REWARD`, `REFERRAL` | `ACQUIRE` + `IncomeSpec(RCM)` | RCM al valor de mercado en recepción. |
| `AIRDROP` | `ACQUIRE` + `IncomeSpec(GANANCIA)` | Ganancia patrimonial. |
| `DEPOSIT` | `ACQUIRE` solo si `eur_value` está informado | Posición de apertura o adquisición externa con base conocida. |
| `REVERSAL` | `REMOVE` de unidades + `IncomeSpec(RCM negativo)` | Retirada de unidades sin ganancia/pérdida; deshace renta previamente computada. |
| `TRANSFER` / `WITHDRAWAL` / `FEE` | Sin movimiento | Asumidos internos o comisiones ya reflejadas en otra pata. |

La clasificación de rentas es configurable en `INCOME_CATEGORY_MAP`. Esto permite adaptar el tratamiento fiscal sin alterar el modelo de datos.

## 8. Cálculo de impuestos (`services/tax_calculator.py`)

### 8.1 Base del ahorro

El cálculo agrupa:

- **Ganancias/pérdidas patrimoniales** por enajenaciones (`Disposal.gain_loss_eur`).
- **Rentas de `IncomeCategory.GANANCIA`**: se unen al grupo de ganancias/pérdidas.
- **RCM** (`IncomeCategory.RCM`): grupo independiente de la base del ahorro.
- **ACTIVIDAD**: se reporta aparte, fuera de la base del ahorro (Fase 1 no lo integra automáticamente).

### 8.2 Compensación cruzada

Aplicada hasta el 25% cuando uno de los dos grupos de la base del ahorro es negativo y el otro positivo:

```python
if base_pl < 0 and base_rcm > 0:
    offset = min(-base_pl, base_rcm * 0.25)
```

La nota de "saldo negativo compensable en los 4 ejercicios siguientes" se genera cuando el grupo de ganancias/pérdidas es negativo en origen (`group_pl < 0`), independientemente de que la compensación cruzada lo absorba parcialmente.

### 8.3 Tramos progresivos

Los tramos se almacenan en `TaxBracket` y se siembran por defecto en `tax/brackets.py`:

- **2021-2022**: 19 %, 21 %, 23 %, 26 %.
- **2023+**: 19 %, 21 %, 23 %, 27 %, 28 %.

Cada tramo tiene `from_eur`, `to_eur` (o `None` para el tramo superior abierto) y `rate`. El cálculo aplica tipo marginal.

## 9. Conectores (`connectors/`)

### 9.1 Framework

`BaseConnector` (`connectors/base.py`) proporciona:

- Carga automática de XLSX o CSV por contenido (magic bytes `PK\x03\x04`).
- Lectura del mapping YAML: columnas, formatos de fecha, separador decimal y `type_map`.
- Helpers para celdas, símbolos, decimales, fechas e IDs sintéticos.
- Normalización por defecto; conectores específicos sobreescriben `normalize_row` para casos complejos.

Registro automático mediante decorador `@register` en `connectors/registry.py`.

### 9.2 Contrato `CanonicalTransaction`

```python
@dataclass
class CanonicalTransaction:
    external_id: str | None
    timestamp: datetime
    type: TransactionType
    asset_in: str | None
    amount_in: Decimal | None
    asset_out: str | None
    amount_out: Decimal | None
    fee_asset: str | None
    fee_amount: Decimal | None
    eur_value: Decimal | None
    notes: str | None
```

### 9.3 Conectores implementados

| Conector | Fichero | Mapping | Estado |
|----------|---------|---------|--------|
| `CRYPTO_COM` | `crypto_com.py` | `crypto_com.yaml` | Implementado para App/exchange; soporta 13+ tipos incluyendo cashback, reversión, transfers internos/P2P. **PROVISIONAL**; ajustar con export real. |
| `CRYPTO_EXCHANGE` | `crypto_exchange.py` | `crypto_exchange.yaml` | Implementado para el journal de Crypto.com Exchange (`OEX_TRANSACTION_*`). Agrupa filas por `Order ID`, colapsa múltiples fills en una sola operación, convierte `USD_Stable_Coin` a EUR vía Frankfurter y emite `BUY`/`SELL` canónicos. **PROVISIONAL**. |
| `REVOLUT` | `revolut.py` | `revolut.yaml` | Implementado para el informe de ganancias/pérdidas de Revolut (`Date acquired`, `Date sold`, `Symbol`, `Quantity`, `Cost basis`, `Gross proceeds`, `Fees`, `Currency`). Cada fila genera un `BUY` + un `SELL` ordenados cronológicamente. Convierte USD a EUR usando el tipo de cambio oficial del BCE (Frankfurter) para cada fecha; usa `fallback_usd_to_eur_rate` si la API no responde. |
| `REVOLUT_EXCHANGE` | `revolut_exchange.py` | `revolut_exchange.yaml` | Esqueleto implementado. **PROVISIONAL**. |

### 9.4 Deduplicación e idempotencia

`import_service` utiliza `external_id` + `account_id` para evitar duplicados. Para exports sin identificador por fila (como Crypto.com), el conector genera un `external_id` sintético con hash SHA-1 de `(ts, kind, currency, amount, to_currency, to_amount, native_amount, occurrence)`.

## 10. Servicios de negocio

### 10.1 `import_service.py`

Orquesta la importación (requiere `taxpayer_id`):

1. Valida que la cuenta pertenezca al contribuyente.
2. Obtiene el conector por nombre.
3. Calcula `sha256` del fichero.
4. Parsea filas y genera `CanonicalTransaction`.
5. Crea `ImportBatch` con `taxpayer_id`, conector, conteos y errores.
6. Descarta duplicados (`external_id` ya existente en la cuenta para ese contribuyente) y movimientos de años cerrados.
7. Persiste nuevas `Transaction` con `taxpayer_id` y `source = connector_name`; crea `Asset` y `FiscalYear` por contribuyente si es necesario.
8. Si se insertó algo, invoca `recompute_all`.

### 10.2 `recompute.py`

Borra las tablas derivadas (`LotConsumption`, `Disposal`, `IncomeEvent`, `Lot`) y reconstruye todo el estado fiscal desde cero, propagando `taxpayer_id` desde `Transaction` a cada tabla derivada:

```python
txs = db.scalars(select(Transaction).order_by(timestamp, id))
moves, incomes = build_ledger(txs)
result = run_fifo(moves)
# Persistir lots, disposals, consumptions, income_events con taxpayer_id
```

Estrategia deliberada a escala local: simplifica la lógica, garantiza coherencia y permite cambiar tratamientos fiscales retroactivamente.

### 10.3 `fiscal_year_service.py`

- `compute_year(db, year, taxpayer_ids=None)`: calcula el resultado fiscal del ejercicio; si se pasa una lista de `taxpayer_ids`, agrega bases y aplica tramos sobre la base combinada (declaración conjunta).
- `close_year(db, year, taxpayer_id)`: congela el resumen, bloquea ediciones y marca el año como `CLOSED` para un único contribuyente.
- `reopen_year(db, year, taxpayer_id)`: reabre el año para un único contribuyente.
- `load_manual_summary(..., taxpayer_id)`: carga un resumen manual para un contribuyente y año sin detalle.
- `add_opening_position(..., taxpayer_id)`: registra una posición inicial como `DEPOSIT` con coste conocido para un contribuyente.

### 10.4 `model721_service.py`

Calcula saldos a 31/12 por `(account_id, asset_id)` desde `Transaction` filtrando por `taxpayer_id` o `taxpayer_ids`, valora con `PriceQuote` más reciente anterior o igual a esa fecha, suma solo cuentas `is_abroad` y compara con el umbral de 50.000 €.

### 10.5 `pricing_service.py`

- `get_price(db, asset_id, on)`: última cotización conocida en o antes de la fecha.
- `upsert_price(...)`: carga o actualiza una cotización manual vía API.

### 10.6 `reporting_service.py`

Todas las funciones aceptan `taxpayer_ids` y filtran las consultas correspondientes:

- `account_balances`: cantidades netas por cuenta/activo desde transacciones.
- `portfolio`: cartera actual desde `Lot` restantes, valorada al último precio.
- `realized_by_asset`: ganancias/pérdidas realizadas por activo y año.
- `yearly_summary`: resumen fiscal por ejercicio.

### 10.7 `review_service.py`

Centraliza los avisos que requieren atención del usuario:

- `generate_manual_items`: escanea `Transaction.notes` y crea items (`P2P_TRANSFER`, `REVERSAL`, `MANUAL_REVIEW`).
- `generate_fifo_items`: convierte los warnings estructurados del motor FIFO en items (`INSUFFICIENT_BALANCE`, `REVERSAL_SHORTFALL`).
- `generate_missing_price_items`: detecta activos del Modelo 721 sin cotización a 31/12.
- `auto_resolve_reversals`: busca avisos de `REVERSAL` que correspondan a una recompensa previa del mismo año, misma cuenta, mismo activo y misma cantidad; los marca como `AUTO_RESOLVED` porque el efecto fiscal neto es nulo, evitando que lleguen a la pantalla de revisión.
- `list_items` / `summary`: listado y conteos filtrados por contribuyente, estado, categoría y año.
- `resolve_item`: resuelve o ignora un aviso. Soporta acciones como `MARK_OWN_ACCOUNT`, `ACCEPT_ZERO_BASIS`, `ADD_PRICE_QUOTE`, `CREATE_OPENING_POSITION`, `IGNORE` y `AUTO_RESOLVED`.

`recompute_all` invoca la generación automática tras cada recomputación, por lo que los avisos se mantienen sincronizados con las transacciones.

### 10.8 `pricing_provider.py`

Integración con CoinGecko para precios históricos en EUR:

- `COIN_ID_MAP`: mapeo manual de símbolos (p. ej. `BTC` → `bitcoin`, `CRO` → `crypto-com-chain`) a los IDs de CoinGecko.
- `fetch_history_eur(coin_id, on)`: consulta el endpoint `/coins/{id}/history` con `date=dd-mm-yyyy` y extrae `market_data.current_price.eur`.
- `fetch_historical_prices` (endpoint `POST /api/prices/fetch-historical`): detecta automáticamente los años fiscales con actividad (`Disposal` / `IncomeEvent`) y los activos presentes en `Lot` para el contribuyente; para cada 31/12 descarga el precio EUR y lo guarda como `PriceQuote` con `source="coingecko"`. Devuelve listas de `fetched`, `missing` y `errors`.

> Los activos no mapeados (p. ej. tokens de pequeño cap) aparecen en `missing` y pueden valorarse manualmente con `POST /api/prices`.

## 11. API REST

Routers montados bajo `/api` en `backend/app/api/__init__.py`.

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Healthcheck. |
| GET | `/connectors` | Lista de conectores registrados. |
| GET | `/assets` | Activos disponibles. |
| GET/POST/PUT/DELETE | `/taxpayers` | CRUD de contribuyentes. El DELETE se bloquea si tiene transacciones. |
| POST | `/prices` | Añadir/actualizar cotización EUR manualmente. |
| POST | `/prices/fetch-historical` | Carga masiva de precios de cierre de año desde CoinGecko (31/12) para los activos del contribuyente. |
| GET/POST | `/accounts` | CRUD de cuentas (filtrado/creación por `taxpayer_id`). |
| POST | `/imports` | Subir fichero CSV/XLSX (requiere `taxpayer_id`). |
| GET | `/imports` | Listar lotes de importación (filtrado por `taxpayer_id`). |
| GET | `/transactions` | Listar transacciones (`?taxpayer_id=` o `?taxpayer_ids=`). Incluye `taxpayer_id` y `source`. |
| GET | `/reviews` | Avisos de revisión (`?taxpayer_id=&status=&category=&year=`). |
| GET | `/reviews/summary` | Conteos de avisos por estado/categoría. |
| POST | `/reviews/generate` | Regenerar avisos manualmente (opcionalmente por año para precios). |
| POST | `/reviews/{id}/resolve` | Resolver aviso (`action` + `note` + `payload`). |
| POST | `/reviews/{id}/ignore` | Ignorar aviso. |
| GET | `/fiscal-years` | Años fiscales con resumen (`?taxpayer_id=` o `?taxpayer_ids=`). |
| GET | `/fiscal-years/{year}/tax` | Cálculo fiscal del año (individual o conjunto). |
| POST | `/fiscal-years/{year}/close?taxpayer_id=...` | Cerrar año para un contribuyente. |
| POST | `/fiscal-years/{year}/reopen?taxpayer_id=...` | Reabrir año para un contribuyente. |
| POST | `/fiscal-years/manual-summary?taxpayer_id=...` | Cargar resumen manual para un contribuyente. |
| POST | `/fiscal-years/opening-position?taxpayer_id=...` | Cargar posición de apertura para un contribuyente. |
| GET | `/reports/portfolio` | Cartera actual valorada (filtrado por contribuyente). |
| GET | `/reports/by-asset?year=...` | Ganancias por activo (filtrado por contribuyente). |
| GET | `/reports/yearly` | Resumen por año fiscal (filtrado por contribuyente). |
| GET | `/reports/model721/{year}` | Datos para Modelo 721 (filtrado por contribuyente). |
| GET | `/reports/dashboard?year=...` | Dashboard consolidado: fiscal, cartera, actividad, avisos y Modelo 721 (filtrado por contribuyente). |

La documentación interactiva está disponible en `/docs` (Swagger UI de FastAPI).

## 12. Frontend

### 12.1 Estructura

- `main.tsx`: monta la aplicación con `QueryClientProvider`, `BrowserRouter`, `TaxpayerProvider` y tema oscuro.
- `App.tsx`: layout con barra lateral de navegación, rutas y selector global de contribuyente.
- `TaxpayerContext.tsx`: contexto React que mantiene los contribuyentes seleccionados, el modo conjunto y la persistencia en `localStorage`. Exporta `buildTaxpayerQuery()` para construir query strings (`taxpayer_id` o `taxpayer_ids[]`).
- `api.ts`: wrapper fino sobre `fetch` con métodos `get`, `post`, `put`, `del` y manejo de errores.
- Páginas:
  - **Dashboard**: panel de control con selector de año fiscal, KPIs de patrimonio, ganancias realizadas, impuestos, ingresos, avisos y Modelo 721; gráficos de evolución fiscal, evolución del patrimonio a cierre de año, distribución de cartera, ingresos por categoría, transacciones por tipo y avisos por estado; tablas de top activos, últimas transacciones y avisos pendientes. Incluye un botón "Cargar precios históricos (CoinGecko)" que invoca `POST /api/prices/fetch-historical` para valorar la cartera y el Modelo 721 con los cierres de 31/12. Alimentado por `GET /api/reports/dashboard`.
  - **Taxpayers**: CRUD de contribuyentes.
  - **ImportPage**: creación de cuentas con `taxpayer_id`, selector de conector, selector de fichero (`<input type="file">`), histórico de importaciones; requiere contribuyente seleccionado.
  - **Transactions**: listado filtrado por contribuyentes seleccionados; muestra columnas `taxpayer_id` y `source`; enlace a la pantalla Revisar si tiene aviso.
  - **Reviews**: bandeja única de avisos con resumen, filtros, acciones inline (cuenta propia, aceptar base 0, añadir cotización, etc.) y resolución masiva.
  - **FiscalYears**: listado de ejercicios filtrado por contribuyente(s), cierre/reapertura por contribuyente, y desglose de tramos impositivos; en modo conjunto calcula el resultado agregado.
  - **Model721**: saldos a 31/12, umbral y obligación de declarar filtrados por contribuyente(s).

> Nota: las funciones de **resumen manual** (`POST /fiscal-years/manual-summary`) y **posición de apertura** (`POST /fiscal-years/opening-position`) están disponibles únicamente vía API en la Fase 1; requieren `taxpayer_id`.

### 12.2 Proxy y despliegue

- En desarrollo: Vite proxya `/api` a `http://localhost:8000`.
- En Docker: nginx sirve el build estático y proxya `/api` al contenedor backend.

## 13. Despliegue

### 13.1 Docker (recomendado)

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- API/docs: http://localhost:8008 (mapeado al puerto 8000 del contenedor backend)
- La base de datos persiste en el volumen `backend-data`.

### 13.2 Sin Docker

Backend:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

### 13.3 Variables de entorno

| Variable | Propósito | Default |
|----------|-----------|---------|
| `CRYPTO_TRACE_DB` | Ruta del fichero SQLite. | `backend/data/crypto_trace.db` |
| `CRYPTO_TRACE_CORS_ORIGINS` | Orígenes CORS permitidos. | `http://localhost:5173`, `http://127.0.0.1:5173` |

## 14. Tests

Ubicados en `backend/tests/`:

- `test_fifo_engine.py`: casos deterministas de compra/venta, multi-lote parcial, pérdidas, saldo insuficiente, orden cronológico y permuta.
- `test_tax_calculator.py`: tramos, compensación, saldos negativos, compensación cruzada RCM.
- `test_import_flow.py`: import end-to-end con XLSX en memoria, verificación de lotes/enajenaciones/rentas e idempotencia; usa contribuyente.
- `test_crypto_com_csv.py`: soporte CSV real de Crypto.com, cashback, reversión, transfers, import del fichero real en `informes/`; usa contribuyente.
- `test_api.py`: flujo HTTP completo con `TestClient` (contribuyente, cuenta, import, transacciones, impuestos, precios, Modelo 721, cierre); verifica `source`.
- `test_joint_taxation.py`: dos contribuyentes con ganancias; verifica resultados individuales y el cálculo conjunto con base y tramos combinados.
- `test_reviews.py`: generación de avisos desde importaciones (P2P) y del motor FIFO; resolución de avisos vía API, incluyendo añadir cotización y revertir resoluciones.
- `test_reporting.py`: agregaciones del dashboard (`/api/reports/dashboard`) y filtrado por año fiscal.
- `test_revolut.py`: conector Revolut para informe de ganancias/pérdidas (`BUY`+`SELL` por fila, comisiones, orden cronológico, import del fichero real en `informes/`); usa contribuyente.
- `test_crypto_exchange.py`: conector Crypto.com Exchange (agrupación por `Order ID`, conversión USD→EUR, comisiones en crypto y en fiat, import del fichero real en `informes/`); usa contribuyente.
- `test_pricing_provider.py`: descubrimiento dinámico de IDs de CoinGecko y carga de cotizaciones históricas.

En total el proyecto contiene **43 funciones de test** (+ skips si algún CSV real de muestra no está presente).

Ejecución:
```bash
cd backend
.venv\Scripts\activate
pytest -q
```

## 15. Decisiones técnicas y trade-offs

### 15.1 Recálculo completo en cada importación

Se optó por borrar y reconstruir tablas derivadas. Es simple, correcto y suficiente para un usuario local. El coste computacional es despreciable hasta miles de transacciones. Si en el futuro crece el volumen, se podría migrar a un recálculo incremental.

### 15.2 SQLite en lugar de PostgreSQL

Prioriza simplicidad de instalación y privacidad. No requiere servidor ni credenciales. La concurrencia es mínima en uso local.

### 15.3 Multi-contribuyente sin autenticación

Se añade la entidad `Taxpayer` y todas las importaciones, cuentas, transacciones y cálculos fiscales se vinculan a ella. No hay login: el selector global en el frontend decide qué datos se consultan. Para no romper bases de datos existentes, `migrate_db()` añade las columnas `taxpayer_id` idempotentemente, crea un contribuyente "Principal" y las rellena retroactivamente.

### 15.4 Sin migraciones Alembic

El esquema se crea con `create_all` y el seed se ejecuta en el lifespan. Para evoluciones se usa una migración manual idempotente en `db.py`. Alembic está identificado como mejora futura.

### 15.5 Conectores basados en YAML

Permite ajustar nombres de columnas y mapas de tipo sin tocar código. Cuando la lógica es demasiado específica (p. ej. IDs sintéticos con contador de ocurrencia, notas de revisión), el conector hereda y extiende `BaseConnector`.

### 15.6 `TRANSFER` y `WITHDRAWAL` sin efecto fiscal

El diseño actual asume que las salidas son entre cuentas propias. Para envíos reales a terceros, la cartera quedaría sobrevalorada. Se documenta en `docs/SUGGESTIONS.md` como mejora futura: añadir campo de contraparte / "¿cuenta propia?".

### 15.7 Coste de adquisición en `DEPOSIT`

Un depósito solo crea lote FIFO si se proporciona `eur_value`. Esto permite distinguir posiciones de apertura con base conocida de transferencias internas sin base.

## 16. Seguridad y privacidad

- Los datos fiscales personales residen en `informes/` y `backend/data/`, ambos ignorados por git.
- No hay autenticación: todos los contribuyentes comparten la misma sesión local y se distinguen únicamente por el selector global.
- No se envían datos personales a servicios externos.
- Las cotizaciones pueden cargarse manualmente (`POST /api/prices`) o automáticamente desde CoinGecko (`POST /api/prices/fetch-historical`) para los cierres de 31/12 necesarios en el dashboard y el Modelo 721. La llamada a CoinGecko solo incluye símbolos de activos y fechas, nunca datos personales ni del contribuyente.

## 17. Estado actual y próximos pasos

### 17.1 Hecho (Fase 1)

- Backend FastAPI completo con modelo de datos, motor FIFO, impuestos y API.
- Soporte multi-contribuyente con `Taxpayer`, `taxpayer_id` en todas las entidades y declaración conjunta.
- Cada transacción vinculada a contribuyente y origen de importación (`source`).
- Conector `CRYPTO_COM` funcional para export CSV/XLSX con cashback, reversión, staking, P2P.
- Conector `CRYPTO_EXCHANGE` funcional para el journal de Crypto.com Exchange (agrupación por `Order ID`, USD→EUR).
- Conector `REVOLUT` funcional para el informe de ganancias/pérdidas de Revolut (USD, round-trip por fila).
- Conector `REVOLUT_EXCHANGE` esqueleto.
- Frontend funcional con 6 pantallas, selector global de contribuyente y dashboard completo con KPIs, filtros y gráficos; incluye botón para cargar precios históricos de CoinGecko.
- Docker Compose operativo.
- 43 funciones de test (+ skips por muestras reales no presentes).

### 17.2 Tarea pendiente inmediata

**Conector Crypto.com BANK / exchange efectivo**: según `docs/ESTADO.md`, renombrar `CRYPTO_COM` → `CRYPTO_COM_EXCHANGE` y crear `CRYPTO_COM_BANK` para el extracto bancario/tarjeta, cubriendo todos los tipos de movimiento.

### 17.3 Mejoras identificadas

- Reclasificación manual de movimientos desde la UI.
- Campo de contraparte para distinguir transferencias internas de envíos a terceros.
- Migraciones Alembic.
- Mapeo de activos adicionales en CoinGecko y carga manual masiva de cotizaciones desde la UI.
- Fase 2: `SimulationService` para "¿qué pasa si vendo X hoy?".
- Exportar dashboard/resumen fiscal a PDF o CSV.

## 18. Referencias

- `backend/app/models/orm.py` — modelo de datos, incluyendo `Taxpayer` y `taxpayer_id`.
- `backend/app/api/taxpayers.py` — CRUD de contribuyentes.
- `backend/app/core/db.py` — migración idempotente SQLite para columnas `taxpayer_id`.
- `backend/app/services/fifo_engine.py` — motor FIFO puro.
- `backend/app/services/ledger.py` — traducción canónica → movimientos fiscales.
- `backend/app/services/tax_calculator.py` — cálculo IRPF base del ahorro.
- `backend/app/services/fiscal_year_service.py` — cálculo individual y conjunto.
- `backend/app/services/review_service.py` — gestión centralizada de avisos.
- `backend/app/connectors/base.py` — framework de conectores.
- `frontend/src/TaxpayerContext.tsx` — selector global y persistencia.
- `frontend/src/pages/Reviews.tsx` — bandeja de avisos.
- `docs/ESTADO.md` — handoff y tarea pendiente.
- `docs/PLAN-FASE-1.md` — plan de arquitectura original.
- `docs/SUGGESTIONS.md` — decisiones fiscales abiertas tras integrar Crypto.com CSV real.
