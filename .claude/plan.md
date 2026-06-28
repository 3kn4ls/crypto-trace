# Plan: Panel general (Dashboard) completo

## Objetivo
Transformar el Dashboard actual de 3 tarjetas y 2 gráficos en un centro de control fiscal/crypto con KPIs, filtros por año, evolución histórica, patrimonio, ganancias, ingresos y avisos.

## 1. Backend — nuevo endpoint `/reports/dashboard`

Añadir `GET /api/reports/dashboard` en `backend/app/api/reports.py` que devuelva un JSON agregado para los contribuyentes seleccionados y, opcionalmente, un año fiscal.

### Datos a devolver

#### 1.1 Fiscal (desde Disposal + IncomeEvent + FiscalYearSummary)
- `years`: array por año con:
  - `year`
  - `total_gains`, `total_losses`, `net_capital_gain`
  - `rcm_income`, `ganancia_income`, `actividad_income`
  - `savings_base`, `tax_due_eur`, `effective_rate`
- `fiscal_totals`: sumas globales de lo anterior
- `closed_years_count`, `open_years_count`

#### 1.2 Patrimonio actual (desde Lot + PriceQuote)
- `portfolio_total_value_eur`
- `portfolio_total_cost_basis_eur`
- `portfolio_unrealized_gain_eur`
- `portfolio_assets_count`
- `assets_with_price`, `assets_without_price`
- `top_assets`: array con `{asset, quantity, price_eur, value_eur, cost_basis_eur, unrealized_eur, pct}`

#### 1.3 Actividad (desde Transaction + IncomeEvent)
- `total_transactions`
- `transactions_by_type`: conteo por tipo
- `total_income_events`
- `income_by_category`: RCM / GANANCIA / ACTIVIDAD con cantidad y valor EUR
- `last_transactions`: las 5 últimas

#### 1.4 Avisos (desde ReviewItem)
- `reviews_summary`: pending, resolved, ignored, total
- `reviews_by_category`: conteo por categoría y estado
- `pending_reviews`: últimos 5 pendientes

#### 1.5 Modelo 721 (desde model721_service)
- `model721_total_abroad_eur`
- `model721_obligated`
- `model721_accounts_count`

### Implementación
- Crear `dashboard()` en `backend/app/services/reporting_service.py`.
- Reutilizar `yearly_summary()`, `portfolio()`, `realized_by_asset()`, `account_balances()` y `review_service.summary()`.
- Para datos históricos de patrimonio, calcular patrimonio a cierre de cada año fiscal usando `account_balances(as_of=date(year,12,31))` y precios a 31/12 (con `get_price`). Devolver `portfolio_evolution: [{year, value_eur, cost_basis_eur}]`.

## 2. Frontend — `frontend/src/pages/Dashboard.tsx`

### 2.1 Filtros
- Selector de año fiscal: "Todos", "Año actual", y años disponibles.
- Cuando se selecciona un año, los KPIs fiscales se filtran a ese año; patrimonio se muestra al cierre del año.

### 2.2 Layout en secciones
```
┌─ Filtros ──────────────────────────────┐
├─ KPIs (4-6 tarjetas grandes) ──────────┤
├─ Gráfico evolución fiscal + patrimonio ──┤
├─ Gráficos: cartera, ingresos, avisos ────┤
├─ Tablas: top activos, últimas txs, avisos ┘
```

### 2.3 KPIs a mostrar
1. **Patrimonio actual**: valor de cartera con badge de ganancia/pérdida no realizada.
2. **Ganancia neta realizada**: suma neta de todos los ejercicios o del año filtrado.
3. **Impuesto estimado**: acumulado o del año.
4. **Ingresos (RCM + ganancias)**: total recibido.
5. **Avisos pendientes**: con enlace a /reviews.
6. **Modelo 721**: valor en el extranjero y si supera el umbral de 50.000 €.

### 2.4 Gráficos (recharts)
- **Evolución fiscal**: línea con `net_capital_gain` y `tax_due_eur` por año.
- **Evolución patrimonio**: línea con `value_eur` y `cost_basis_eur` por año.
- **Distribución cartera**: pie/treemap por valor.
- **Ingresos por categoría**: barras apiladas por año.
- **Avisos por estado**: donut chart.

### 2.5 Tablas
- Top 5 activos por valor (con precio, cantidad, coste, no realizado).
- Últimas 5 transacciones (tipo, activo, EUR, fecha).
- Últimos 5 avisos pendientes con link a abrir ReviewDialog.

## 3. Tests
- Añadir test en `backend/tests/test_reviews.py` o crear `backend/tests/test_reporting.py`:
  - `test_dashboard_returns_expected_keys`: importar un CSV, llamar `/api/reports/dashboard` y verificar que las claves esperadas existen.
  - `test_dashboard_filters_by_year`: verificar que al pasar `year` los totales fiscales corresponden a ese año.

## 4. Estilos
- Reutilizar `.card`, `.grid`, `.badge`, `.stat` existentes.
- Añadir clases nuevas mínimas: `.kpi-grid`, `.chart-grid`, `.kpi-trend`.

## 5. Documentación
- Actualizar `docs/SUGGESTIONS.md` (si procede) y `docs/DOCUMENTO-TECNICO.md` para reflejar el nuevo endpoint y KPIs.

## 6. Docker
- Reconstruir contenedores tras cambios en frontend/backend.

## Alternativas descartadas
- Hacer múltiples endpoints separados: más limpio para la API pero más lento y complejo en el frontend. Se prefiere un único endpoint `dashboard` para carga de una sola página.
- Calcular patrimonio histórico desde transacciones acumuladas año a año: es lo mismo que haremos, pero usando `account_balances` a 31/12 de cada año con precios históricas (o actuales si no hay). Se documentará la limitación de precios históricos.

## Orden de implementación
1. Backend: implementar `dashboard()` en `reporting_service.py` y endpoint en `reports.py`.
2. Backend: tests del endpoint.
3. Frontend: refactorizar `Dashboard.tsx` con filtros, KPIs y gráficos.
4. Frontend: tablas y estilos.
5. Documentación.
6. Reconstruir Docker y verificar.
