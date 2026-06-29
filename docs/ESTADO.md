# Estado del proyecto — Crypto-Trace

> Rama: `claude/wonderful-gauss-vbd72u` · Fecha: 2026-06-29
> Documento de **handoff** para retomar el proyecto desde otra sesión (incluida una sesión local
> con acceso a `C:\ws\crypto-trace`, a la carpeta `informes/` y a la app en `http://localhost:5173`).

## 1. Qué es
App **local monousuario / multi-contribuyente** para el **control fiscal de criptomonedas**
(IRPF España, método **FIFO**, base imponible del ahorro). Importa Excel/CSV de exchanges mediante
**conectores** que traducen cada formato a un **modelo canónico** agnóstico; calcula
ganancias/pérdidas y el **impuesto estimado** por ejercicio; gestiona **años fiscales**
(cierre/arrastre), **Modelo 721** (criptos en el extranjero) y un **panel** con gráficos.
Exporta a **PDF/CSV** y deja preparada la **Fase 2** (simulaciones).

Stack: **Backend** Python/FastAPI + SQLAlchemy 2.0 + SQLite (Decimal exacto). **Frontend** React + TS + Vite + Recharts.

> ⚠️ Herramienta de apoyo al cálculo, **no asesoramiento fiscal**. Calificaciones discutibles
> (staking, airdrops, permutas, cashback, regalos) modeladas como **configurables**.

## 2. Lo que YA está hecho (commiteado y pusheado)
- **Backend** (`backend/app/`): FastAPI + SQLAlchemy 2.0 + SQLite. Dinero en `Decimal`, almacenado como
  texto (`models/types.py::DecimalText`) para evitar el redondeo en coma flotante de SQLite.
- **Modelo de datos** (`models/orm.py`): `Taxpayer`, `Asset`, `Account`, `ImportBatch`, `Transaction`
  (canónica), `Lot`, `Disposal`, `LotConsumption`, `IncomeEvent`, `FiscalYear`, `FiscalYearSummary`,
  `ReviewItem`, `TaxpayerRewardPreference`, `TaxBracket`, `PriceQuote`. Enums canónicos en `models/enums.py`.
- **Motor FIFO puro y determinista** (`services/fifo_engine.py`) + **cálculo de impuestos**
  (`services/tax_calculator.py`: base del ahorro, compensación g/p y cruzada con RCM 25%, tramos por año
  en `tax/brackets.py`).
- **Conectores** (`connectors/`): framework `base.py` (parseo dirigido por **YAML**, autodetección
  CSV/XLSX) + `registry.py` (auto-registro con `@register`). Implementados:
  - `CRYPTO_COM_BANK` (App/tarjeta Crypto.com) — `crypto_com_bank.py` / `.yaml`.
  - `CRYPTO_EXCHANGE` (journal de Crypto.com Exchange, agrupa por `Order ID`, USD→EUR) — `crypto_exchange.py`.
  - `REVOLUT` (informe de ganancias/pérdidas, BUY+SELL por fila, USD→EUR vía BCE/Frankfurter) — `revolut.py`.
  - `REVOLUT_EXCHANGE` — esqueleto provisional.
- **Importación** (`services/import_service.py`): dedup **idempotente** (`external_id` por cuenta) +
  `services/recompute.py` (recálculo total del FIFO) + puente `services/ledger.py`.
  - **Preview** (`POST /imports/preview`): parsea sin persistir, muestra 10 filas y errores por fila.
- **Eliminación de importaciones** (`api/imports.py`): borrar un lote o limpiar todo un contribuyente,
  con recálculo automático.
- **Reclasificación manual** (`PATCH /transactions/{id}`): cambiar `type`, `cost_basis_eur`,
  `is_internal_transfer` y `notes`; recalcula FIFO e impuestos al guardar.
- **Servicios**: `fiscal_year_service.py` (cierre/arrastre, resumen manual, posición de apertura),
  `model721_service.py` (saldos 31/12 en EUR, umbral 50.000 €), `reporting_service.py` (dashboard),
  `pricing_service.py` + `pricing_provider.py` (CoinGecko: cierres 31/12 y precio actual),
  `reward_preference_service.py` (configuración fiscal de recompensas), `review_service.py` (avisos),
  `export_service.py` (PDF/CSV), `exchange_rate_provider.py` (USD/EUR BCE).
- **API REST** (`api/`, montada en `/api`): contribuyentes, cuentas, importaciones (+preview),
  transacciones (+PATCH), avisos (resolver/ignorar/revertir), años fiscales, informes, dashboard,
  precios (manual / históricos / actuales), preferencias de recompensas y **exportación PDF/CSV**.
- **Frontend** (`frontend/src/pages/`): Dashboard (con filtro de año explícito, KPIs, gráficos,
  carga de precios y botones de export), Import (con preview), Transactions (con edición inline),
  FiscalYears, Model721, Reviews y Taxpayers (editor de preferencias). Selector global de contribuyente.
- **Docker**: `docker-compose.yml` + Dockerfiles + nginx (proxy `/api`). App en `:5173`, API en `:8008`.
- **Tests**: **61 funciones** en `backend/tests/`; **60 en verde** y 1 dependiente de `fpdf2`
  (instalar la dependencia del `requirements.txt` para que pase). Cubren FIFO, impuestos, import
  end-to-end (idempotencia), API, eliminación de importaciones, conectores, preferencias fiscales,
  P2P, coste base, dashboard, pricing y funcionalidades de fase 2.

## 3. Cómo arrancar
- **Docker** (recomendado): `docker compose up --build` → http://localhost:5173 (API/docs en `:8008/docs`).
- **Sin Docker**:
  - Backend (desde `backend/`): `python -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt && uvicorn app.main:app --reload`
  - Frontend (desde `frontend/`): `npm install && npm run dev`
- **Tests** (desde `backend/`, con el venv activo y `pip install -r requirements.txt`): `pytest -q`

## 4. Tarea pendiente inmediata
**Validación fiscal real del ejercicio 2025** y resolución de los hallazgos de `docs/ANALISIS.md`.

1. Importar los tres ficheros de `informes/` para el contribuyente correspondiente.
2. Ajustar preferencias de recompensas (`Taxpayers → Preferencias`) según criterio del asesor.
3. Resolver avisos P2P (`Reviews`): marcar envíos a terceros como `MARK_THIRD_PARTY_SEND`.
4. Completar posiciones de apertura / costes base reales para depósitos externos (`Transactions → Editar`).
5. Cargar precios de cierre (`Dashboard → Cargar precios históricos`) y revisar Modelo 721.
6. Revisar años fiscales y cuota estimada; cerrar el ejercicio.

## 5. Privacidad
`informes/` y `backend/data/` están en `.gitignore`: contienen datos fiscales personales y **nunca**
deben subirse al repo.

## 6. Cómo retomar en local
```bash
git fetch origin
git checkout claude/wonderful-gauss-vbd72u
git pull
# leer docs/ESTADO.md (este fichero), docs/DOCUMENTO-TECNICO.md y docs/ANALISIS.md
```

## 7. Backlog / siguientes pasos
Histórico de alta prioridad y mejoras 5-8: **completado** (conectores, preferencias de recompensas,
P2P, coste base, reclasificación manual, cierres 31/12, exportación PDF/CSV, preview de importación).

Pendiente (detalle y priorización en `docs/ANALISIS.md`):
- [x] Corregir la reversión para que respete la categoría/base de la recompensa (ANALISIS §1.1).
- [x] Definir la semántica de "año cerrado": write-lock de años cerrados (ANALISIS §1.2).
- [ ] Validaciones restantes en `PATCH /transactions/{id}`: coherencia del nuevo tipo (ANALISIS §1.3; el bloqueo por año cerrado ya está).
- [ ] `pytest.importorskip("fpdf")` y manejo de error del export PDF (ANALISIS §1.4).
- [ ] Generar avisos `MISSING_PRICE` también en el recompute (ANALISIS §1.5).
- [ ] Fase 2: `SimulationService` (el motor FIFO ya es puro y reutilizable).
- [ ] Migraciones Alembic; arrastre real de pérdidas a 4 años; rate limiting CoinGecko.
- [ ] UI para resumen manual y posición de apertura (hoy solo vía API).
