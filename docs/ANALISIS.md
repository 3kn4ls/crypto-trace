# Análisis del proyecto — estado, errores y mejoras

> Revisión técnica del 2026-06-29 sobre la rama `claude/wonderful-gauss-vbd72u`.
> Complementa a `docs/DOCUMENTO-TECNICO.md` (arquitectura) y `docs/ESTADO.md`
> (handoff). Aquí se recogen **hallazgos accionables**: errores de corrección,
> riesgos fiscales a validar, mejoras y discrepancias de documentación.
>
> ⚠️ No es asesoramiento fiscal. Las calificaciones discutibles se señalan como
> "decisión del asesor".

## 0. Resumen ejecutivo

El proyecto está **funcional y bien estructurado**: motor FIFO puro, modelo
canónico, multi-contribuyente, 4 conectores, dashboard, exportación PDF/CSV,
preview de importación y reclasificación manual. Los tests pasan **60/61**
(el único fallo es de entorno: falta `fpdf2` en el venv local; ver §1.4).

Los hallazgos más relevantes:

| # | Severidad | Hallazgo | Tipo |
|---|-----------|----------|------|
| 1.1 | ~~Alta~~ ✅ **Resuelto** | La reversión (`REVERSAL`) siempre restaba RCM aunque la recompensa fuera "ganancia" o de base cero | Corrección fiscal |
| 1.2 | ~~Alta~~ ✅ **Resuelto** | Editar/borrar transacciones recalculaba también años **cerrados**: el resumen congelado dejaba de coincidir con el cálculo en vivo | Corrección |
| 1.3 | ~~Media~~ ✅ **Resuelto** | `PATCH /transactions/{id}` no validaba año cerrado ni coherencia del nuevo tipo | Robustez |
| 1.4 | ~~Media~~ ✅ **Resuelto** | `fpdf2` ausente daba un test rojo y un 500 del export PDF | Entorno / robustez |
| 1.5 | Media | Los avisos `MISSING_PRICE` no se generan en el recompute, solo bajo petición explícita | Funcional |
| 1.6 | Baja | `account_balances` / Modelo 721 pueden descuadrar con transferencias entre cuentas propias | Edge case |
| 1.7 | Baja | El `external_id` sintético es frágil ante exports **incrementales** | Conocido |

---

## 1. Errores y riesgos de corrección

### 1.1 [Alta] La reversión siempre deshace RCM — ✅ Resuelto (2026-06-29)

> **Resuelto.** Nuevo `services/reversal_matching.py` (matcher por bucket
> `(contribuyente, cuenta, activo, año)` con preferencia por coincidencia exacta y
> seguimiento de cantidad restante, que cubre reversiones totales y parciales).
> `ledger.py` ahora resta el `eur_value` de la reversión en la **categoría/base
> efectivas de la recompensa emparejada** (nada si era base cero); las reversiones
> sin par solo retiran unidades y quedan `PENDING`. `review_service` usa el mismo
> matcher, así que bandeja y fiscalidad coinciden. Tests en
> `backend/tests/test_reversal.py`.

`services/ledger.py` (rama `REVERSAL`) emitía siempre un ingreso negativo como
`IncomeCategory.RCM`:

```python
incomes.append(IncomeSpec(tx.id, tx.asset_out_id, tx.timestamp,
                          -qty, -fmv, IncomeCategory.RCM, tx.fiscal_year))
```

Dos problemas:

1. **No respeta las preferencias del contribuyente.** Si `STAKING_REWARD` o
   `REFERRAL` se configuran como `GANANCIA` (o `AIRDROP`, que por defecto es
   `GANANCIA`), la recompensa original sumó a *ganancia patrimonial* pero la
   reversión resta de *RCM*. Quedan dos grupos descuadrados.
2. **RCM fantasma con base cero.** Si la recompensa se configuró como
   `zero_cost_basis` (descuento, sin `IncomeSpec`), no se computó ningún
   ingreso; pero la reversión **sí** resta RCM que nunca existió, generando un
   RCM negativo espurio.

**Impacto real:** bajo en importes (las reversiones de cashback son céntimos),
pero es un error de modelo. **Recomendación:** que el `REVERSAL` consulte la
categoría/base efectiva del tipo de recompensa equivalente (vía
`reward_preference_service`) y solo reste ingreso si la recompensa lo generó.
El emparejamiento ya existe en `review_service.auto_resolve_reversals`; conviene
reutilizar esa lógica para localizar la recompensa original y deshacerla con su
misma categoría.

### 1.2 [Alta] El cierre de año no congela el cálculo en vivo — ✅ Resuelto (2026-06-29)

> **Resuelto (write-lock).** Cerrar un año lo deja **de solo lectura**: nuevo
> `fiscal_year_service.is_year_closed(...)` y guardas que rechazan con `409`/`400`
> editar/borrar transacciones de un año cerrado (`PATCH /transactions/{id}`,
> `DELETE /imports/{batch}`, `DELETE /imports`), añadir posiciones de apertura en
> él (`add_opening_position`) y resolver avisos P2P suyos (`review_service`). Para
> corregir, se reabre el año. La importación ya saltaba filas de años cerrados.
> Tests en `backend/tests/test_closed_year_lock.py`.
>
> **Matiz (limitación asumida):** se eligió bloquear ediciones, no servir las
> lecturas desde el snapshot. Persiste un caso raro: editar/importar en un año
> **abierto anterior** puede alterar el FIFO de un año cerrado posterior. Si en el
> futuro importa, la opción "lecturas desde snapshot" lo cerraría del todo.

`close_year` congela un `FiscalYearSummary` (snapshot), pero:

- `recompute_all` **borra y reconstruye todos** los lotes/enajenaciones/rentas
  de **todos** los años, incluidos los cerrados, en cada import, borrado de lote,
  edición de transacción o resolución de aviso.
- `compute_year`, `/fiscal-years/{año}/tax`, el dashboard y los informes calculan
  **en vivo** desde las tablas derivadas, no desde el snapshot.

Resultado: tras cualquier cambio, el resumen **congelado** (`list_years`,
columna `tax_due_eur`) y el cálculo **en vivo** (`/tax`) de un año cerrado pueden
**divergir** sin aviso. La importación sí salta filas de años cerrados
(`import_service`), pero editar/borrar no.

**Recomendación:**
- Decidir la semántica del "cierre": o bien (a) el cálculo en vivo de un año
  cerrado se sirve siempre desde el snapshot, o bien (b) cualquier operación que
  toque un año cerrado se bloquea (como ya hace la importación).
- Como mínimo, mostrar en la UI cuándo el snapshot y el cálculo en vivo difieren.

### 1.3 [Media] `PATCH /transactions/{id}` sin validaciones — ✅ Resuelto (2026-06-29)

> **Resuelto.** `patch_transaction` rechaza ahora editar transacciones de años
> cerrados (`409`, ver §1.2) y valida la **coherencia del nuevo tipo** con las
> patas existentes (`_validate_type`): un tipo de adquisición exige activo cripto
> de entrada, uno de enajenación exige cripto de salida, `SWAP` ambos y `TRANSFER`
> al menos uno; reclasificaciones incoherentes devuelven `400`. Tests en
> `backend/tests/test_patch_and_export_robustness.py`. *No aplica* la comprobación
> de contribuyente: el endpoint no recibe un contribuyente seleccionado y la app es
> monousuario; quedaría pendiente solo si se añade aislamiento multi-contribuyente real.

`api/transactions.py::patch_transaction`:

- **No comprueba el contribuyente**: cualquier `tx_id` es editable sin filtrar
  por el contribuyente seleccionado (irrelevante en monousuario, pero rompe el
  aislamiento multi-contribuyente).
- **No bloquea años cerrados** (ver §1.2).
- **No valida el nuevo `type`**: reclasificar p. ej. un `DEPOSIT` a `SELL` sin
  `asset_out`/`amount_out` produce una enajenación incoherente o silenciosa.
- Cambiar el tipo no toca `is_internal_transfer`; un `SWAP`→`TRANSFER` puede
  dejar el flag en un estado raro.

**Recomendación:** validar pertenencia al contribuyente, rechazar ediciones en
años cerrados y comprobar que el nuevo tipo es coherente con las patas presentes.

### 1.4 [Media] Dependencia `fpdf2` y export PDF — ✅ Resuelto (2026-06-29)

> **Resuelto.** El test del PDF usa `pytest.importorskip("fpdf")` (se omite si no
> está instalado, en vez de fallar) y `export_service._build_pdf` lanza
> `PdfExportUnavailable` si falta `fpdf2`, que el endpoint traduce a un `503` con
> mensaje claro ("instala fpdf2 o exporta a CSV"); el CSV nunca depende de `fpdf2`.
> Tests en `backend/tests/test_patch_and_export_robustness.py`.

`pytest` falla en `test_phase2_features.py::test_export_transactions_pdf` con
`ModuleNoFoundError: No module named 'fpdf'`. La dependencia **sí** está en
`requirements.txt` (`fpdf2>=2.8`), así que en Docker funciona; el venv local no
la tiene instalada.

Dos mejoras:
- El test debería usar `pytest.importorskip("fpdf")` para no dar falso rojo.
- El endpoint de export PDF hace `from fpdf import FPDF` dentro de `_build_pdf`;
  si falta, devuelve un **500** crudo. Mejor capturarlo y responder un 503/400
  con un mensaje claro ("instala fpdf2 para exportar a PDF"). El CSV no depende
  de fpdf y funciona siempre.

### 1.5 [Media] Avisos de precio ausente no automáticos

`generate_missing_price_items` solo se invoca desde `POST /reviews/generate?year=`.
No forma parte de `recompute_all` (que sí genera P2P, reversiones y avisos FIFO).
Por tanto, tras importar, el Modelo 721 puede tener activos sin cotización a
31/12 **sin** que aparezca un aviso en la bandeja salvo que el usuario pulse
"regenerar" con un año. **Recomendación:** generarlos también tras recompute para
los años con saldo en el extranjero, o documentar que requiere acción manual.

### 1.6 [Baja] Saldos por cuenta y Modelo 721

`reporting_service.account_balances` calcula cantidad neta por
`(account_id, asset_id)` sumando `amount_in` y restando `amount_out`/`fee`. El
FIFO es **global por contribuyente**, pero el 721 trabaja **por cuenta**. Una
transferencia interna entre dos cuentas propias aparece como salida en una y
entrada en otra; si solo se importa el extracto de una de ellas, la cuenta
emisora puede quedar a **saldo negativo** (se ignora porque el 721 filtra
`qty > 0`) y la receptora no existe. El total puede **descuadrar** respecto a la
cartera FIFO global. Es un caso límite; conviene avisar cuando un saldo por
cuenta es negativo.

### 1.7 [Baja] Deduplicación de exports incrementales

Ya documentado en `docs/SUGGESTIONS.md` §3.3: el `external_id` sintético de
Crypto.com Bank usa un contador de ocurrencia por fila idéntica. Un **re-export
incremental** (mismo histórico + filas nuevas) que altere el orden relativo de
filas idénticas puede duplicar o perder movimientos. Mitigado pero no resuelto;
lo ideal es usar el *Transaction Hash* cuando exista.

---

## 2. Riesgos fiscales a validar (criterio del asesor)

Estos no son bugs de código, sino decisiones de modelo que conviene confirmar:

- **Declaración conjunta**: `compute_year` con varios `taxpayer_ids` **agrega**
  las bases del ahorro y aplica los tramos una sola vez sobre la base combinada.
  Para la base del ahorro en tributación conjunta es defendible (no se duplican
  tramos), pero la compensación de pérdidas entre cónyuges es una simplificación.
- **Compensación de pérdidas a 4 años**: el `tax_calculator` **anota** el saldo
  negativo compensable pero **no lo arrastra** automáticamente al ejercicio
  siguiente. Hoy es responsabilidad del usuario.
- **Recompensas → RCM por defecto**: cashback, staking y referidos se tratan como
  RCM; airdrops como ganancia patrimonial. Todo configurable por contribuyente
  (`Taxpayers → Preferencias`). Confirmar antes de cerrar el ejercicio.
- **P2P a terceros**: neutros por defecto, marcados para revisión. Si no se
  resuelven, la cartera queda sobrevalorada (no se retiran unidades).

---

## 3. Mejoras (no urgentes)

- **Migraciones Alembic**: hoy el esquema se crea con `create_all` + una
  migración idempotente manual en `core/db.py`. Funciona, pero no cubre cambios
  de constraints ni *downgrades*.
- **Arrastre real de pérdidas** (4 ejercicios) en `tax_calculator`.
- **CoinGecko**: añadir *rate limiting*/reintentos con backoff (la API gratuita
  limita a ~10-30 req/min y las llamadas son secuenciales por activo×año);
  persistir los IDs descubiertos (`_DISCOVERED_IDS`) en `Asset.coingecko_id`;
  ampliar `COIN_ID_MAP`.
- **Fase 2 — `SimulationService`**: el motor FIFO ya es puro y reutilizable;
  clonar el estado de lotes y aplicar enajenaciones hipotéticas ("¿cuánto pagaría
  si vendo X hoy?").
- **UI para resumen manual y posición de apertura**: hoy solo vía API
  (`POST /fiscal-years/manual-summary` y `/opening-position`).
- **Conector Crypto.com Bank**: validar que `Native Currency == EUR` antes de
  usar `Native Amount` como valor EUR (hoy se asume EUR; ver SUGGESTIONS §3.4).
- **`REVOLUT_EXCHANGE`**: sigue siendo un esqueleto provisional sin export real.
- **Tests pendientes**: reclasificación vía `PATCH` con recálculo, preview de
  importación, export con dependencia ausente, y los casos de §1.1/§1.2.
- **Seguridad/operación local**: sin autenticación ni límite de tamaño de subida
  (aceptable en local, conviene documentarlo).

---

## 4. Discrepancias de documentación detectadas

Corregidas o pendientes de corregir en `DOCUMENTO-TECNICO.md` / `ESTADO.md`:

- **Nombres de fichero de conectores**: el doc citaba `crypto_com.py` /
  `crypto_com.yaml`; los reales son `crypto_com_bank.py` / `crypto_com_bank.yaml`.
- **Firma de `build_ledger`**: ahora es `build_ledger(db, transactions)` (recibe
  la sesión para consultar preferencias), no `build_ledger(transactions)`.
- **Clasificación de rentas**: ya no hay `INCOME_CATEGORY_MAP`; se decide en
  `reward_preference_service` (configurable por contribuyente).
- **Endpoints no documentados**: `POST /imports/preview`,
  `PATCH /transactions/{id}`, `GET /exports/{summary|transactions|model721}`,
  `POST /prices/fetch-current`, `POST /reviews/{id}/revert`.
- **Enums incompletos**: `AccountPlatform` incluye `CRYPTO_EXCHANGE`; faltaban
  `ReviewCategory`, `ReviewStatus`, `ReviewSeverity`.
- **Puerto del backend en Docker**: `docker-compose.yml` mapea `8008:8000`, pero
  el README y el propio comentario del compose dicen `8000`. El puerto real en el
  host es **8008**.
- **Nº de tests**: el handoff hablaba de 49/54; hoy son **61** (60 verdes + 1
  dependiente de `fpdf2`).
