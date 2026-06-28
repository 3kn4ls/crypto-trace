# Estado del proyecto — Crypto-Trace

> Rama: `claude/wonderful-gauss-vbd72u` · Fecha: 2026-06-24
> Documento de **handoff** para retomar el proyecto desde otra sesión (incluida una sesión local
> con acceso a `C:\ws\crypto-trace`, a la carpeta `informes/` y a la app en `http://localhost:5173`).

## 1. Qué es
App **local monousuario** para el **control fiscal de criptomonedas** (IRPF España, método **FIFO**,
base imponible del ahorro). Importa Excel/CSV de exchanges mediante **conectores** que traducen cada formato
a un **modelo canónico** agnóstico; calcula ganancias/pérdidas y el **impuesto estimado** por ejercicio;
gestiona **años fiscales** (cierre/arrastre), **Modelo 721** (criptos en el extranjero) y un **panel** con
gráficos. Deja preparada la **Fase 2** (simulaciones).

Stack: **Backend** Python/FastAPI + SQLAlchemy 2.0 + SQLite (Decimal exacto). **Frontend** React + TS + Vite + Recharts.

> ⚠️ Herramienta de apoyo al cálculo, **no asesoramiento fiscal**. Calificaciones discutibles
> (staking, airdrops, permutas, cashback, regalos) modeladas como **configurables**.

## 2. Lo que YA está hecho (commiteado y pusheado)
- **Backend** (`backend/app/`): FastAPI + SQLAlchemy 2.0 + SQLite. Dinero en `Decimal`, almacenado como
  texto (`models/types.py::DecimalText`) para evitar el redondeo en coma flotante de SQLite.
- **Modelo de datos** (`models/orm.py`): `Asset`, `Account`, `Transaction` (canónica), `Lot`, `Disposal`,
  `LotConsumption`, `IncomeEvent`, `FiscalYear`, `FiscalYearSummary`, `TaxBracket`, `PriceQuote`, `ImportBatch`,
  `TaxpayerRewardPreference`. Enums canónicos en `models/enums.py`.
- **Motor FIFO puro y determinista** (`services/fifo_engine.py`) + **cálculo de impuestos**
  (`services/tax_calculator.py`: base del ahorro, compensación g/p y cruzada con RCM 25%, tramos por año
  en `tax/brackets.py`).
- **Conectores** (`connectors/`): framework `base.py` (`BaseConnector`, `CanonicalTransaction`, parseo
  dirigido por **YAML**) + `registry.py` (auto-registro con `@register`). Implementados y afinados con
  exports reales de `informes/`: `CRYPTO_COM_BANK` (App/tarjeta), `CRYPTO_EXCHANGE` (journal de Crypto.com
  Exchange) y `REVOLUT` (tax statement); mapeos en `connectors/mappings/*.yaml`.
- **Importación** (`services/import_service.py`): dedup **idempotente** (`external_id` / `file_hash`) +
  `services/recompute.py` (recalcula todo el FIFO desde las transacciones); puente
  `services/ledger.py` (transacción canónica → movimientos del motor + rentas).
- **Eliminación de importaciones** (`api/imports.py`): borrar un lote o limpiar todo un contribuyente,
  con recálculo automático del estado derivado.
- **Servicios**: `fiscal_year_service.py` (cierre/arrastre, resumen manual, posición de apertura),
  `model721_service.py` (saldos 31/12 en EUR, umbral 50.000 €), `reporting_service.py`, `pricing_service.py`,
  `reward_preference_service.py` (configuración fiscal de recompensas).
- **API REST** (`api/`, montada en `/api`) incluyendo:
  - `GET/PUT /api/taxpayers/{id}/reward-preferences` (tratamiento fiscal de recompensas).
  - `PATCH /api/transactions/{id}` (edición de `cost_basis_eur`, `is_internal_transfer`, `notes`).
  - `POST /api/reviews/{id}/resolve` con acciones `MARK_OWN_ACCOUNT`, `MARK_THIRD_PARTY_SEND`, `MARK_PAYMENT`.
- **Frontend** (`frontend/src/pages/`): Dashboard, Import, Transactions, FiscalYears, Model721, Reviews,
  Taxpayers (con editor de preferencias de recompensas) y edición inline de transacciones.
- **Docker**: `docker-compose.yml` + Dockerfiles + nginx (proxy `/api`). App en `:5173`, API en `:8000`.
- **Tests**: **54 en verde** (`backend/tests/`): FIFO, impuestos, import end-to-end (idempotencia), API,
  eliminación de importaciones, conectores Crypto.com Bank/Exchange y Revolut, preferencias fiscales,
  envíos P2P y coste base explícito.

## 3. Cómo arrancar
- **Docker** (recomendado): `docker compose up --build` → http://localhost:5173 (API/docs en `:8000/docs`).
- **Sin Docker**:
  - Backend (desde `backend/`): `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload`
  - Frontend (desde `frontend/`): `npm install && npm run dev`
- **Tests** (desde `backend/`, con el venv activo): `pytest -q`

## 4. Tarea pendiente inmediata
**Validación fiscal real del ejercicio 2025.**

Los tres conectores ya importan sin errores los ficheros de `informes/`. El siguiente paso es
revisar los resultados fiscales del ejercicio actual:
1. Importar los tres ficheros en la UI para el contribuyente correspondiente.
2. Ajustar preferencias de recompensas (`Taxpayers → Preferencias`) según criterio del asesor
   (RCM, ganancia patrimonial o descuento/base cero).
3. Resolver avisos P2P (`Reviews`): marcar envíos a terceros como `MARK_THIRD_PARTY_SEND`.
4. Completar posiciones de apertura / costes base reales para depósitos externos (`Transactions → Editar`).
5. Revisar años fiscales, Modelo 721 y cuota estimada.

## 5. Privacidad
`informes/` está en `.gitignore`: contiene datos fiscales personales y **nunca** debe subirse al repo.

## 6. Cómo retomar en local
```bash
git fetch origin
git checkout claude/wonderful-gauss-vbd72u
git pull
# leer docs/ESTADO.md (este fichero) y docs/DOCUMENTO-TECNICO.md
```

## 7. Backlog / siguientes pasos
- [x] Afinar mapeos provisionales de `CRYPTO_COM_BANK`, `CRYPTO_EXCHANGE` y `REVOLUT` con exports reales.
- [x] Reclasificación manual de movimientos desde la UI (edición de transacciones y preferencias de recompensas).
- [x] Campo de contraparte para distinguir transferencias internas de envíos a terceros (`is_internal_transfer` + acciones de revisión P2P).
- [x] Permitir a los depósitos/aperturas llevar un `cost_basis_eur` explícito.
- Fase 2: `SimulationService` (el motor FIFO ya es puro y reutilizable).
- Exportar dashboard/resumen fiscal a PDF o CSV.
- Integrar fuente de cotizaciones (p. ej. CoinGecko) para valorar ingresos y Modelo 721.
- Migraciones Alembic (hoy el esquema se crea con `Base.metadata.create_all` al arrancar).
