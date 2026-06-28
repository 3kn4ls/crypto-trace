# Plan — 4 temas de alta prioridad

## Contexto
Crypto-Trace ya tiene los conectores renombrados (`CRYPTO_COM_BANK`, `CRYPTO_EXCHANGE`) y la funcionalidad de eliminar importaciones implementada. Quedan 4 temas de alta prioridad pendientes.

## Objetivo
Implementar los 4 temas de alta prioridad de forma coherente con el stack existente (FastAPI + SQLAlchemy 2.0 + SQLite + React/Vite), manteniendo el motor FIFO puro y la estrategia de recálculo completo.

---

## 1. Afinar conectores con exports reales

### Alcance
- Validar `CRYPTO_COM_BANK` contra `informes/crypto_transactions_record_24062026_120003-1.csv`.
- Validar `CRYPTO_EXCHANGE` contra `informes/OEX_TRANSACTION_CRYPTO_COM_EXCHANGE.csv`.
- Validar `REVOLUT` (Gains/Losses) contra `informes/REVOLUT_DEMO.csv`.

### Ficheros a tocar
- `backend/app/connectors/crypto_com_bank.py` / `mappings/crypto_com_bank.yaml`: añadir nuevas monedas (BARA, XPL) si son cripto; verificar que no haya `Transaction Kind` sin mapear.
- `backend/app/connectors/crypto_exchange.py` / `mappings/crypto_exchange.yaml`: verificar agrupación por `Order ID`, comisiones, depósitos fiat.
- `backend/tests/test_real_imports.py`: nuevo test que importa los 3 ficheros reales y comprueba `errors_json is None` y conteos razonables.
- `README.md` y `docs/DOCUMENTO-TECNICO.md`: aclarar que `REVOLUT` = informe de ganancias/pérdidas y `REVOLUT_EXCHANGE` = journal de operaciones (esqueleto).

### Decisiones clave
- No renombrar conectores ya commiteados.
- Si aparece un tipo no mapeado en el CSV real, añadirlo al YAML correspondiente (no al enum salvo que sea realmente nuevo).

---

## 2. Tratamiento fiscal configurable de recompensas

### Alcance
Permitir que el usuario decida, por tipo de recompensa y contribuyente, si se trata como:
- `RCM` (actual),
- `GANANCIA` patrimonial,
- `DESCUENTO` (coste de adquisición 0, sin ingreso).

Tipos afectados: `STAKING_REWARD`, `REFERRAL`, `AIRDROP`.

### Modelo
- Nuevo modelo `TaxpayerRewardPreference`:
  - `taxpayer_id` (FK),
  - `transaction_type` (STAKING_REWARD | REFERRAL | AIRDROP),
  - `income_category` (RCM | GANANCIA | ACTIVIDAD),
  - `zero_cost_basis` (bool).
- Clave única `(taxpayer_id, transaction_type)`.
- Añadir en `migrate_db()`.

### Lógica
- `services/ledger.py` consulta preferencias del contribuyente al construir `IncomeSpec`.
- Si `zero_cost_basis=True`: no genera `IncomeEvent`, pero sí crea el lote con `unit_cost_eur=0`.
- Si `zero_cost_basis=False`: genera ingreso según `income_category`.

### API
- `GET /api/taxpayers/{id}/reward-preferences`
- `PUT /api/taxpayers/{id}/reward-preferences` (cuerpo lista de preferencias).

### Frontend
- Añadir sección "Tratamiento de recompensas" en la página de contribuyentes (`/taxpayers`) o un diálogo.

---

## 3. Envíos P2P a terceros: retirar unidades del FIFO

### Alcance
Los `TRANSFER` internos no afectan al FIFO. Cuando un envío P2P es a un tercero, debe enajenarse (sale del patrimonio).

### Modelo
- Añadir columna `transactions.is_internal_transfer` (bool, default `True`).
- Migrar en `migrate_db()`.

### Lógica
- `services/ledger.py`:
  - Si `type == TRANSFER` e `is_internal_transfer == True`: ignorar (comportamiento actual).
  - Si `type == TRANSFER` e `is_internal_transfer == False`:
    - si tiene `asset_out` → `DISPOSE` (como una venta a tercero).
    - si tiene `asset_in` → dejar la transacción marcada con nota y generar aviso de revisión (no crear lote automáticamente, ya que podría ser donación, pago, etc.).
- `services/review_service.py`: implementar la acción `MARK_THIRD_PARTY_SEND`:
  - Pone `is_internal_transfer = False` en la transacción.
  - Llama a `recompute_all()`.
  - La acción ya existe en `VALID_ACTIONS`; falta el cuerpo.

### API
- `GET /api/transactions` ya devuelve `is_internal_transfer`.
- `POST /api/reviews/{id}/resolve` con acción `MARK_THIRD_PARTY_SEND` ejecuta el cambio.

### Frontend
- En `/reviews`, el botón para `MARK_THIRD_PARTY_SEND` ya está permitido; solo hace falta que el backend lo ejecute.
- En `/transactions`, mostrar el flag si es `False`.

---

## 4. Depósitos externos con coste real

### Alcance
Un `DEPOSIT` (posición de apertura o ingreso desde otro exchange) debe poder llevar un `cost_basis_eur` explícito en lugar de usar el valor de mercado del día.

### Modelo
- Añadir columna `transactions.cost_basis_eur` (`DecimalText`, nullable).
- Migrar en `migrate_db()`.

### Lógica
- `services/ledger.py`: para `DEPOSIT`, usar `cost_basis_eur` si está informado; si no, `eur_value` (comportamiento actual).

### API
- `PUT /api/transactions/{id}`: permite editar `cost_basis_eur`, `eur_value`, `notes` y `type` (solo valores permitidos para evitar inconsistencias). Requiere que la transacción pertenezca al contribuyente.
- Recompute automático tras la edición.

### Frontend
- En `/transactions`, añadir un botón "Editar" en cada fila para DEPOSIT (y eventualmente otros) que permita cambiar `cost_basis_eur` y `notes`.

---

## Orden de implementación recomendado
1. Esquema + migraciones (columnas y tabla).
2. `services/ledger.py` para aplicar los nuevos flags.
3. `services/review_service.py` implementar `MARK_THIRD_PARTY_SEND`.
4. API endpoints (reward preferences + transaction update).
5. Ajustes de conectores y tests reales.
6. Frontend (diálogo de preferencias + edición de transacción).
7. Tests de regresión y Docker end-to-end.

---

## Tests a añadir
- `backend/tests/test_reward_preferences.py`: configurar RCM/GANANCIA/DESCUENTO y verificar resultado fiscal.
- `backend/tests/test_p2p_third_party.py`: marcar un P2P como envío a tercero y comprobar que se enajena.
- `backend/tests/test_deposit_cost_basis.py`: DEPOSIT con `cost_basis_eur` distinto del valor de mercado.
- `backend/tests/test_real_imports.py`: importar los 3 CSV/XLSX reales sin errores.
- Actualizar tests existentes que rompan por nuevas columnas.

## Riesgos / notas
- El motor FIFO se recalcula entero tras cada cambio; por eso basta con editar la transacción y llamar `recompute_all()`.
- Las nuevas columnas deben ser nullable o tener default para no romper imports antiguos.
- `MARK_THIRD_PARTY_SEND` es irreversible a efectos de FIFO; se puede revertir el review item, pero la transacción seguirá con `is_internal_transfer=False`. Se documentará así.
