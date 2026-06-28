# Plan: Botón para eliminar importaciones y limpiar base de datos

## Objetivo
Permitir al usuario borrar importaciones individuales o todas las importaciones de un contribuyente desde la UI, dejando la base de datos fiscal consistente.

## Alcance
- Backend: nuevos endpoints `DELETE /api/imports/{batch_id}` y `DELETE /api/imports?taxpayer_id=X`.
- Frontend: botón "Eliminar" por fila de importación y botón "Limpiar todas las importaciones" con confirmación.
- Tests unitarios/e2e.
- Reconstrucción Docker y verificación manual.

## Backend

### 1. `backend/app/api/imports.py`
Añadir:
- `DELETE /api/imports/{batch_id}`:
  - Recuperar el batch. Si no existe → 404.
  - Opcional: validar que `taxpayer_id` del batch coincida con el contribuyente activo (usaremos el `taxpayer_id` del propio batch para evitar errores, ya que la API no tiene autenticación).
  - Borrar todas las `Transaction` con `import_batch_id == batch.id`.
  - Borrar el `ImportBatch`.
  - Llamar `recompute_all(db)` para regenerar lotes, disposals, income events y reviews.
  - Devolver `{deleted: true, recomputed: {...}}`.
- `DELETE /api/imports?taxpayer_id=X`:
  - Si no se pasa `taxpayer_id` → 400.
  - Borrar todas las `Transaction` cuyo `taxpayer_id == X`.
  - Borrar todos los `ImportBatch` de ese contribuyente.
  - Llamar `recompute_all(db)`.
  - Devolver `{deleted: true, transactions_deleted: N, batches_deleted: M}`.

Razón de usar borrado manual + recompute: las tablas derivadas (`Lot`, `Disposal`, `IncomeEvent`, `ReviewItem`) se reconstruyen desde cero en `recompute_all`, por lo que no hace falta configurar cascadas de borrado en la base de datos.

### 2. `backend/app/services/import_service.py`
No requiere cambios; el borrado se hará directamente en el endpoint.

## Frontend

### `frontend/src/pages/Import.tsx`
- Añadir dos mutaciones:
  - `deleteBatch`: `api.del(`/imports/${batch.id}`)`.
  - `clearAllImports`: `api.del(`/imports?taxpayer_id=${importTaxpayerId}`)`.
- En la tabla de importaciones, añadir columna "Acciones" con botón rojo "Eliminar".
- Añadir encima de la tabla un botón "Limpiar todas las importaciones" con `window.confirm`.
- Tras éxito, invalidar queries (`["batches", ...]`, `["transactions"]`, `["dashboard"]`, etc.).
- Mostrar estado de carga y errores.

## Tests

### `backend/tests/test_import_deletion.py`
- `test_delete_single_batch_removes_transactions_and_recomputes`:
  - Importar XLSX con 5 filas.
  - Verificar 5 transacciones, lotes e ingresos.
  - Llamar DELETE del batch.
  - Verificar 0 transacciones, 0 lotes, 0 disposals, 0 income events, 0 batches.
- `test_clear_all_imports_for_taxpayer`:
  - Importar dos batches para el mismo contribuyente.
  - Verificar transacciones.
  - Llamar DELETE `/imports?taxpayer_id=X`.
  - Verificar 0 transacciones y 0 batches para ese contribuyente.
- `test_delete_batch_of_other_taxpayer_is_not_allowed`:
  - Crear dos contribuyentes, importar a uno.
  - Intentar borrar el batch usando el `taxpayer_id` del otro → 403/400.

### Actualizar `test_import_flow.py`
No se espera cambios; los tests existentes deben seguir pasando.

## Documentación
- Actualizar `docs/DOCUMENTO-TECNICO.md`:
  - Sección 9.4: mencionar eliminación de importaciones.
  - Sección 10.1: añadir paso de borrado.
  - Incrementar conteo de tests (43 + N nuevos).

## Docker
- Reconstruir imágenes y levantar el stack.
- Importar un fichero, verificar dashboard.
- Borrar la importación desde la UI y verificar que el dashboard vuelve a cero.

## Riesgos y decisiones
- **Riesgo**: Borrar transacciones manualmente sin recompute dejaría lotes/disposals huérfanos. **Mitigación**: siempre llamar `recompute_all` después.
- **Decisión**: No borraremos `Asset` ni `FiscalYear` aunque queden sin uso, para evitar side effects; son entidades de referencia baratas.
- **Decisión**: La "limpieza de base de datos" se limita al contribuyente seleccionado, no a toda la aplicación, para respetar el modelo multi-contribuyente.

## Archivos a modificar
1. `backend/app/api/imports.py`
2. `frontend/src/pages/Import.tsx`
3. `backend/tests/test_import_deletion.py` (nuevo)
4. `docs/DOCUMENTO-TECNICO.md`
5. Posible ajuste menor en `frontend/src/api.ts` si hace falta algún helper de query string (no es necesario, usaremos template strings).
