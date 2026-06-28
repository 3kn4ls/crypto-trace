# Sugerencias y cuestiones abiertas — conector Crypto.com Bank (CSV)

> Documento de trabajo creado al integrar el primer conector real
> (`informes/crypto_transactions_record_*.csv`). Recoge **lo que se ha
> implementado**, las **decisiones fiscales** que conviene que valides y los
> **huecos del modelo** que quedan pendientes. No es asesoramiento fiscal.

Fecha: 2026-06-24 · Fichero analizado: 436 movimientos (abr–dic 2025), todos en CRO
y recompensas asociadas.

---

## 1. Qué se ha implementado en esta iteración

- **Importación de CSV** (antes solo XLSX). El conector autodetecta el formato
  por contenido (XLSX = ZIP `PK…`; el resto se lee como CSV). Mismo conector
  para ambos formatos. → `connectors/base.py`.
- **Tratamiento fiscal configurable de recompensas** (`services/reward_preference_service.py`):
  staking, cashback/referidos y airdrops pueden clasificarse como RCM, ganancia patrimonial
  o actividad, y opcionalmente entrar en FIFO con base cero (descuento). Las preferencias
  se editan por contribuyente en `Taxpayers → Preferencias` y persisten en
  `taxpayer_reward_preferences`.
- **Envíos P2P a terceros como enajenación**: las transferencias `TRANSFER` con nota P2P
  se importan neutras por defecto y se marcan para revisión. Desde `Reviews` se pueden
  resolver como `MARK_THIRD_PARTY_SEND` para que el débito retire unidades del FIFO
  con base de coste cero. La acción `MARK_OWN_ACCOUNT` mantiene el comportamiento neutro.
- **Coste de adquisición explícito**: `Transaction.cost_basis_eur` permite a los
  depósitos/aperturas llevar su coste real. Se expone en la API (`PATCH /api/transactions/{id}`)
  y en la UI (`Transactions → Editar`). El endpoint de posición de apertura lo rellena
  automáticamente.
- **Mapeo completo de los 13 _Transaction Kind_** presentes en tu export: ya no
  hay filas con error «Transaction Kind no soportado». → `mappings/crypto_com_bank.yaml`.
- **Cashback** (`referral_card_cashback`) y demás recompensas → **ingreso** a
  valor de mercado (EUR de la columna *Native Amount*) + alta de lote FIFO.
- **Reversión de cashback** (`card_cashback_reverted`, importes negativos):
  nuevo tipo canónico `REVERSAL`. Retira las unidades de la cartera **sin generar
  ganancia/pérdida** (nuevo `MoveType.REMOVE`) y **resta el ingreso** previamente
  computado (RCM negativo). → `fifo_engine.py`, `ledger.py`.
- **Movimientos internos** (`supercharger_deposit/withdrawal`,
  `finance.lockup.dpos_lock`, `finance.dpos.staking`) → `TRANSFER`: **sin efecto
  fiscal** (el CRO sigue siendo tuyo, solo cambia de "cajón").
- **Transferencias P2P** (`transfer.p2p_transfer…credit/debit`) → `TRANSFER`
  **neutro** y **marcado para revisión** (campo `notes`). Ver §2.5.
- **Deduplicación robusta**: el export no trae *Transaction Hash*, así que el id
  sintético ahora incluye el valor en EUR y un contador de ocurrencia. Antes se
  descartaban como "duplicadas" 2 recompensas legítimas (p. ej. dos premios XPL
  el mismo segundo con distinto valor EUR); ahora se conservan las 436 y el
  reimport sigue siendo idempotente.
- Frontend: el selector de fichero acepta `.csv` además de `.xlsx`.
- Tests nuevos: `backend/tests/test_crypto_com_csv.py` (cashback+reversión,
  transfers internos/P2P, e import del CSV real sin errores).

Resultado del CSV real (ejercicio 2025): **RCM 209,73 €**, sin enajenaciones
(no hay ventas/permutas), **cuota estimada 39,85 €**, 0 avisos de saldo
insuficiente, ~7.543 CRO en cartera.

---

## 2. Decisiones fiscales — **conviene que las confirmes**

La calificación fiscal de las cripto-recompensas en España **no es pacífica**.
He tomado defaults razonables y **configurables por contribuyente** desde la UI/API.
Ajusta las preferencias (`Taxpayers → Preferencias`) antes de cerrar un ejercicio.

### 2.1 Cashback de tarjeta → actualmente **RCM** (rendimiento del capital mobiliario)
Es la partida más grande (240 movimientos). Hay dos lecturas posibles:
- **Ingreso** (lo aplicado): premio/retribución → RCM a valor de mercado al
  recibirlo; coste de adquisición del CRO = ese valor.
- **Descuento/rebaja** sobre tu propio consumo → **no tributa** como ingreso;
  el CRO entraría con coste 0 y solo tributaría al venderlo.

  👉 *Decisión tuya.* En la UI/API (`Taxpayers → Preferencias`) puedes cambiar
  `REFERRAL` a **base cero**; el CRO entrará con coste 0 y solo tributará al venderlo.

### 2.2 Mystery Box / Welcome Bonus (`rewards_platform_deposit_credited`) → **RCM**
Lo he equiparado al cashback (`REFERRAL → RCM`). Puedes cambiarlo en las
preferencias a `AIRDROP` (→ `GANANCIA`) o a base cero.

### 2.3 Recompensas de staking/pool (`supercharger_reward`, `dpos…interest`) → **RCM**
Criterio mayoritario. Puedes reclasificarlo como `GANANCIA` o `ACTIVIDAD`,
o marcarlo como base cero desde las preferencias.

### 2.4 Reversión de cashback → **RCM negativo + retirada de unidades**
- Asume que la reversión es del **mismo ejercicio** que el cashback original
  (en tu fichero siempre lo es, a menudo el mismo segundo). Si alguna vez
  cruzara de año, habría que ajustar el ejercicio del ingreso negativo.
- La retirada consume lotes en orden **FIFO** (los más antiguos), no
  necesariamente el lote del cashback revertido. Como no hay hecho imponible y
  los importes son mínimos, el efecto es inmaterial; se documenta por rigor.

### 2.5 Transferencias P2P (enviado/recibido de "Nancy") → **neutras + marcadas**
Son 8 movimientos con un tercero. **No se puede saber automáticamente** su
naturaleza, y cada una tributa distinto:
- **Cuenta propia** (otra wallet tuya) → neutro (lo aplicado).
- **Donación** recibida/entregada → puede haber **ISD** y/o ganancia patrimonial.
- **Pago** por bienes/servicios → ingreso (recibido) o enajenación (entregado).

  👉 *Decisión tuya, movimiento a movimiento.* Hoy se importan como `TRANSFER`
  neutro y con nota «P2P con tercero: revisar…». Desde `Reviews` resuelve cada
  envío a tercero con `MARK_THIRD_PARTY_SEND` para que el débito retire unidades
  del FIFO. Si son entre tus propias wallets, usa `MARK_OWN_ACCOUNT`.

### 2.6 CRO bloqueado en staking/tarjeta sigue contando para el **Modelo 721**
Los locks son `TRANSFER` (no salen de tu patrimonio). Asegúrate de que el saldo
a 31/12 del 721 incluya el CRO bloqueado (hoy sí, porque los lotes permanecen).

---

## 3. Huecos del modelo / robustez (recomendaciones)

### 3.1 `WITHDRAWAL`/salidas no retiran unidades (FIFO global) ✅ Implementado
Las `TRANSFER` se importan como internas por defecto. Para un **envío real a un
tercero**, resuelve el aviso P2P con `MARK_THIRD_PARTY_SEND`: el débito se
convierte en una disposición (`DISPOSE`) que consume lotes FIFO. Si no se resuelve,
la cartera queda sobrevalorada. Ver §2.5.

### 3.2 Coste de adquisición en `crypto_deposit` ✅ Implementado
`Transaction.cost_basis_eur` permite a los depósitos/aperturas llevar su coste
real. La UI (`Transactions → Editar`) y la API (`PATCH /api/transactions/{id}`)
permiten ajustarlo; el endpoint de posición de apertura lo rellena
automáticamente. Si no se indica, `DEPOSIT` sigue usando `eur_value`.

### 3.3 Deduplicación de exports sin id
Mitigada (incluye valor EUR + ocurrencia). Pero un **export incremental** (mismo
histórico + filas nuevas) depende de que el orden relativo de filas idénticas se
mantenga. Lo ideal: usar *Transaction Hash* cuando exista, o guardar un hash de
fichero + offset. Recomendación menor: avisar en UI cuando se detecten filas
idénticas sin id.

### 3.4 Moneda nativa asumida = EUR
El conector fija `FIAT = "EUR"` y usa *Native Amount*. El export trae además
*Native Currency* y *Native Amount (in USD)* (ignorada). Si tu *Native Currency*
no fuese EUR, los importes serían incorrectos. Recomendación: **leer y validar
`Native Currency == EUR`** y, si no, convertir o avisar.

### 3.5 Reclasificación manual en la UI
Dadas las ambigüedades de §2, sería muy útil poder **editar el tipo/categoría de
un movimiento** (o de un grupo) desde la pantalla de Transacciones, con
recálculo. Es probablemente la mejora con más impacto fiscal.

### 3.6 Visibilidad de avisos y movimientos marcados ✅ Implementado
- Nueva entidad `ReviewItem` y tabla `review_items`.
- Pantalla **Revisar** (`/reviews`) con bandeja única: P2P, reversiones, saldo
  insuficiente y precios ausentes.
- Acciones inline: marcar como cuenta propia, envío a tercero, pago, aceptar
  base 0, crear posición de apertura, añadir cotización, ignorar.
- Resolución masiva y regeneración manual de avisos.
- Los `errors` por fila siguen disponibles en el resultado de importación.

### 3.7 Cotizaciones para valoración
Para el 721 (saldo a 31/12 en EUR) y para valorar ingresos cuando falte el
*Native Amount*, hace falta cargar `PriceQuote`. Hoy es manual vía `POST /api/prices`.
Valorar integrar una fuente (p. ej. CoinGecko, ids ya sembrados en los activos).

---

## 4. Sobre "CRYPTO.COM/BANCO"

En `informes/` solo está el **export de la Crypto.com App** (incluye los
movimientos de la **tarjeta**: cashback, etc.). **No hay un extracto bancario
fiat aparte.** Si por "banco" te refieres a:
- **La tarjeta Crypto.com** → ya queda cubierta por el conector `CRYPTO_COM_BANK`.
- **Un extracto de banco tradicional** (entradas/salidas de EUR, compras SEPA a
  un exchange) → es **otro conector** distinto; aporta el CSV y lo diseñamos
  (normalmente solo afecta a aportaciones/retiradas de fiat, no genera lotes
  cripto salvo que registre compras).

Indícame cuál es el caso y seguimos.

---

## 5. Cómo probarlo

```bash
# Tests (incluye import del CSV real):
cd backend && .venv/Scripts/python -m pytest -q

# Vía la app (http://localhost:5173): pestaña Importar →
#   1) crea cuenta "Crypto.com" (marca "en el extranjero" para el 721)
#   2) conector CRYPTO_COM_BANK, sube el .csv → Importar
```
