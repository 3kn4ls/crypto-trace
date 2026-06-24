# Estado del proyecto — Crypto-Trace

> Rama: `claude/wonderful-gauss-vbd72u` · Fecha: 2026-06-24
> Documento de **handoff** para retomar el proyecto desde otra sesión (incluida una sesión local
> con acceso a `C:\ws\crypto-trace`, a la carpeta `informes/` y a la app en `http://localhost:5173`).

## 1. Qué es
App **local monousuario** para el **control fiscal de criptomonedas** (IRPF España, método **FIFO**,
base imponible del ahorro). Importa Excel de exchanges mediante **conectores** que traducen cada formato
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
  `LotConsumption`, `IncomeEvent`, `FiscalYear`, `FiscalYearSummary`, `TaxBracket`, `PriceQuote`, `ImportBatch`.
  Enums canónicos en `models/enums.py`.
- **Motor FIFO puro y determinista** (`services/fifo_engine.py`) + **cálculo de impuestos**
  (`services/tax_calculator.py`: base del ahorro, compensación g/p y cruzada con RCM 25%, tramos por año
  en `tax/brackets.py`).
- **Conectores** (`connectors/`): framework `base.py` (`BaseConnector`, `CanonicalTransaction`, parseo
  dirigido por **YAML**) + `registry.py` (auto-registro con `@register`). Implementados **PROVISIONALES**:
  `CRYPTO_COM` (App/exchange) y `REVOLUT_EXCHANGE`; mapeos en `connectors/mappings/*.yaml`.
- **Importación** (`services/import_service.py`): dedup **idempotente** (`external_id` / `file_hash`) +
  `services/recompute.py` (recalcula todo el FIFO desde las transacciones); puente
  `services/ledger.py` (transacción canónica → movimientos del motor + rentas).
- **Servicios**: `fiscal_year_service.py` (cierre/arrastre, resumen manual, posición de apertura),
  `model721_service.py` (saldos 31/12 en EUR, umbral 50.000 €), `reporting_service.py`, `pricing_service.py`.
- **API REST** (`api/`, montada en `/api`). **Frontend** (`frontend/src/pages/`): Dashboard, Import,
  Transactions, FiscalYears, Model721.
- **Docker**: `docker-compose.yml` + Dockerfiles + nginx (proxy `/api`). App en `:5173`, API en `:8000`.
- **Tests**: **15 en verde** (`backend/tests/`): FIFO, impuestos, import end-to-end (idempotencia), API.

## 3. Cómo arrancar
- **Docker** (recomendado): `docker compose up --build` → http://localhost:5173 (API/docs en `:8000/docs`).
- **Sin Docker**:
  - Backend (desde `backend/`): `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload`
  - Frontend (desde `frontend/`): `npm install && npm run dev`
- **Tests** (desde `backend/`, con el venv activo): `pytest -q`

## 4. TAREA PENDIENTE — Conector **Crypto.com BANK**
Objetivo: conector **efectivo** para el documento de Crypto.com **banco/tarjeta** y asegurar que se
contemplan **todos los tipos** (cashback, regalos/gifts, referidos, gasto con tarjeta, recargas, reembolsos…).
Habrá además otro fichero de Crypto.com **exchange**.

**Enfoque (decidido con el usuario): dos conectores.**
- Renombrar el actual `CRYPTO_COM` → `CRYPTO_COM_EXCHANGE` (atributo `name` + su fichero de mapeo).
- Crear `CRYPTO_COM_BANK` (`connectors/crypto_com_bank.py` + `mappings/crypto_com_bank.yaml`) siguiendo
  el patrón de `connectors/crypto_com.py`.

**Pasos (sesión local, que SÍ ve `informes/`):**
1. **Inspeccionar el fichero real** de `informes/`: hoja, fila de cabecera, **columnas exactas** y
   **todos los valores distintos** de la columna de tipo/descripción.
   - Si NO es `.xlsx` (CSV o PDF): ampliar el lector. Hoy `connectors/base.py` usa `openpyxl.load_workbook`.
     CSV = cambio pequeño; PDF = añadir p. ej. `pdfplumber` + extracción de tablas (más trabajo).
2. **Mapear cada tipo** a `TransactionType` en el YAML (`type_map`). Cubrir como mínimo: card cashback
   (y su reverso), supercharger, referral bonus, **regalos / “Crypto Gift”**, gasto con tarjeta (`SPEND`),
   card top-up, refunds / reembolsos, depósitos / retiradas, rewards / staking.
3. Si faltan tipos canónicos, **añadirlos** en `models/enums.py` (p. ej. `CASHBACK`, `GIFT`, `REBATE`,
   `REFUND`) y darles tratamiento en `services/ledger.py` (`INCOME_CATEGORY_MAP`) y en la clasificación
   fiscal (`IncomeCategory`: RCM / GANANCIA). **Criterio inicial a confirmar**: cashback de tarjeta ≈
   menor coste de adquisición / “rappel”; **regalos → ganancia patrimonial**; **referidos → RCM**.
4. Registro automático vía `@register`; revisar el import en `connectors/registry.py::_load_builtin`.
5. **Test** con muestra anonimizada (`tests/test_crypto_com_bank.py`) replicando el patrón de
   `tests/test_import_flow.py` (Excel construido en memoria con `openpyxl`).
6. **Verificar end-to-end**: subir el Excel real por la UI y revisar Transacciones / Años / impuesto.

**Archivos clave:** `backend/app/connectors/{base.py, registry.py, crypto_com.py → crypto_com_exchange.py,
crypto_com_bank.py}`, `connectors/mappings/*.yaml`, `models/enums.py`, `services/ledger.py`,
`services/tax_calculator.py` (si nuevas categorías), `tests/`.

## 5. Privacidad
`informes/` está en `.gitignore`: contiene datos fiscales personales y **nunca** debe subirse al repo.

## 6. Cómo retomar en local
```bash
git fetch origin
git checkout claude/wonderful-gauss-vbd72u
git pull
# leer docs/ESTADO.md (este fichero) y docs/PLAN-FASE-1.md, y continuar la TAREA PENDIENTE
```

## 7. Backlog / siguientes pasos
- Conector `CRYPTO_COM_BANK` + `CRYPTO_COM_EXCHANGE` con ficheros reales (tarea pendiente arriba).
- Afinar mapeos provisionales de `CRYPTO_COM`/`REVOLUT_EXCHANGE` con exports reales.
- Fase 2: `SimulationService` (el motor FIFO ya es puro y reutilizable).
- Opcional: migraciones Alembic (hoy el esquema se crea con `Base.metadata.create_all` al arrancar).
