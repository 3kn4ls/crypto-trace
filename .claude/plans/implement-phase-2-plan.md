# Plan — Mejoras 5-8 (reclasificación, precios, exportación, importador)

## Contexto
El usuario pide implementar 4 funcionalidades más sobre la versión actual de Crypto-Trace, dejando la app funcionando en Docker y manteniendo la arquitectura existente (FastAPI + SQLAlchemy 2.0 + SQLite + React/Vite + motor FIFO puro + recálculo completo).

## Objetivo
Añadir sin romper lo existente:
1. **Reclasificación manual de transacciones** desde la UI (cambiar tipo/categoría y recalcular).
2. **Carga masiva de cierres de 31/12** desde el dashboard (CoinGecko).
3. **Exportación a PDF/CSV** de resumen fiscal, transacciones y Modelo 721.
4. **Importador mejorado**: preview de filas y errores por fila legibles.

---

## 1. Reclasificación manual de transacciones

### Backend
- `backend/app/schemas/__init__.py`: añadir `type: TransactionType | None` a `TransactionUpdateIn`.
- `backend/app/api/transactions.py`: en `patch_transaction`, si se recibe `type`, actualizar `tx.type` y lanzar `recompute_all(db)`.

### Frontend
- `frontend/src/components/TransactionEditDialog.tsx`: añadir un select para cambiar el `type` de la transacción (mapa de etiquetas en español). Enviar el nuevo tipo junto a los demás campos en el PATCH.
- Asegurar que el diálogo invalida las queries de transacciones, reviews y dashboard tras guardar.

### Tests
- `backend/tests/test_high_priority.py` o fichero nuevo: PATCH cambia tipo de `TRANSFER` a `SELL`, se crea Disposal correspondiente y se actualiza el resumen fiscal.

---

## 2. Carga masiva / automática de precios de cierre

### Backend
- `backend/app/api/meta.py`: mejorar `fetch_historical_prices` para que, cuando no se indique `year`, use **todos los años presentes en `Transaction.fiscal_year`** (no solo los que tengan disposals/income). Así los ejercicios con solo compras también obtienen cotización de cierre y el dashboard puede valorar la cartera a 31/12.
- Mantener `fetch_current_prices` tal cual (precios de hoy para la vista "Todos los años").

### Frontend
- `frontend/src/pages/Dashboard.tsx`: separar el botón actual en dos acciones explícitas:
  - **“Cargar cierres 31/12 (CoinGecko)”** → llama a `/prices/fetch-historical`.
  - **“Cargar precios actuales (CoinGecko)”** → llama a `/prices/fetch-current`.
- Mantener el mensaje de resultado con conteos de fetched/skipped/missing/errors.

### Tests
- Verificar que `fetch-historical` sin `year` devuelve cotizaciones para un año que solo tiene compras.

---

## 3. Exportación a PDF/CSV

### Backend
- Añadir dependencia `fpdf2>=2.8` en `backend/requirements.txt`.
- Nuevo `backend/app/services/export_service.py`:
  - `export_summary_csv/pdf(db, taxpayer_ids, year=None)`.
  - `export_transactions_csv/pdf(db, taxpayer_ids, year=None)`.
  - `export_model721_csv/pdf(db, year, taxpayer_ids)`.
  - CSV con `csv` + `io.StringIO`; PDF con `fpdf.FPDF` y fuente `DejaVu` para acentos.
- Nuevo `backend/app/api/exports.py`:
  - `GET /exports/{scope}` donde `scope ∈ {summary, transactions, model721}`.
  - Query params: `format` (csv|pdf), `year`, `taxpayer_id`, `taxpayer_ids`.
  - Devuelve `StreamingResponse` con `Content-Disposition: attachment; filename=...`.
- `backend/app/api/__init__.py`: montar `exports.router` bajo `/exports`.

### Frontend
- Nuevo componente `frontend/src/components/ExportButtons.tsx`:
  - Dos botones pequeños (CSV / PDF).
  - Hace `fetch` directo a `/api/exports/{scope}?...`, convierte la respuesta en blob y dispara la descarga con nombre de fichero.
- Añadir botones en:
  - `Dashboard.tsx` para exportar resumen fiscal.
  - `Transactions.tsx` para exportar transacciones (respeta año filtrado).
  - `Model721.tsx` para exportar Modelo 721 (respeta año seleccionado).

### Tests
- `backend/tests/test_exports.py`: comprobar status 200 y cabecera `Content-Disposition` para cada scope y formato; verificar que CSV contiene cabeceras esperadas.

---

## 4. Mejorar el importador: preview y errores legibles

### Backend
- `backend/app/api/imports.py`: añadir `POST /imports/preview`.
  - Recibe los mismos parámetros de formulario que `/imports` (`connector`, `taxpayer_id`, `account_id`, `file`).
  - Usa `get_connector(...).parse(BytesIO(content))` sin persistir nada.
  - Devuelve `total_rows`, `parsed_count`, `error_count`, `preview` (primeras 10 filas canónicas) y `errors` (lista `{row, message}`).

### Frontend
- `frontend/src/pages/Import.tsx`:
  - Añadir mutación `preview` y estado `preview`.
  - Botón **“Vista previa”** habilitado cuando hay conector, contribuyente, cuenta y fichero.
  - Mostrar tabla con las primeras 10 filas parseadas (fecha, tipo, entrada, salida, EUR).
  - Mostrar tabla de errores por fila con número de fila y mensaje (legible, no solo conteo).
  - Botón **“Confirmar importación”** para ejecutar la importación real.
  - Tras importar, limpiar la vista previa.

### Tests
- `backend/tests/test_import_preview.py`: subir fichero de ejemplo, comprobar que preview devuelve filas y no crea transacciones ni lotes.

---

## Orden de implementación
1. Reclasificación manual (cambio pequeño, alto impacto fiscal).
2. Carga masiva de precios (backend + dashboard).
3. Exportación PDF/CSV (nuevo servicio, router y componente).
4. Importador con preview (nuevo endpoint + UI).
5. Tests y Docker build final.

## Riesgos / decisiones
- Cambiar el tipo de una transacción puede dejar asset_in/asset_out inconsistentes con el nuevo tipo. Se acepta tal cual y se deja que `ledger.py` lo ignore si faltan patas; el usuario lo corregirá editando o con reseñas si es necesario.
- La exportación PDF usa fpdf2 con fuente DejaVu para soportar tildes y euró.
- El preview no escribe en DB, por lo que no crea activos ni años fiscales; por eso muestra símbolos en bruto.

## Verificación final
- `docker compose up --build` levanta la app en `http://localhost:5173`.
- Backend healthcheck pasa.
- `pytest backend/tests` sigue en verde (54+ tests).
