# Review: task/T02

## Verdict
APPROVE

## Functional Verification
- Ejecutado `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`: `19 passed, 1 warning` en 3.68 s.
- Ejecutado `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`: `484 passed, 3 skipped` en 15.28 s.
- Revisados el brief, el report del implementer, las restricciones globales, la receta y los tres archivos nuevos.

## Spec Compliance
- Se cumplen las firmas congeladas, validación de `user_id`, homes 0700 por tenant, restauración atómica 0600, JSONL por `id`, handlers, timeouts, límites, snapshot cifrado, stderr aislado y shutdown/evicción en los escenarios cubiertos.
- `CODEX_HOME_ROOT`, `CODEX_TERMINATE_GRACE_SECONDS`, el shim `.py` y `CodexTimeoutError` son desviaciones aditivas razonables y no alteran el contrato runtime por defecto.
- La evicción LRU elimina el registro antes de terminar y limpiar completamente el home; esta carrera real de ciclo de vida (F01) quedó resuelta en la remediación revisada.

## Code Quality
- La implementación es clara y usa limpieza en `finally`, semáforos y una reader-task por proceso.
- El test de concurrencia resuelve respuestas por id, pero el fake responde secuencialmente; no verifica respuestas fuera de orden. El código del reader sí hace lookup por id, por lo que queda como limitación de cobertura y no como defecto confirmado.

## Named Risk Checks
- **Aislamiento multi-tenant:** validación `fullmatch` y paths derivados del `user_id` en `backend/codex_app_server.py:343-346,463-478`; no se observan rutas compartidas por defecto.
- **Credenciales:** `_atomic_write` usa temp+`os.replace` y 0600 en `:99-117`; restore/snapshot son best-effort y no registran blobs. Snapshot cifra antes del upsert en `:604-629`.
- **JSONL/concurrencia:** una reader-task, `_pending` indexado por id y eliminación en timeout/finally en `:159-214,215-284`; semáforo por proceso en `:174-175`.
- **Capacidad/LRU:** semáforo global, evicción de inactivos y liberación idempotente revisados en `:424-461,636-639`; F01 afecta la sincronización del cleanup, no la atomicidad del `dict.pop`.
- **Shutdown:** termina, espera reader, intenta snapshot, limpia home y libera slots mediante `finally` en `:388-410,549-566`.

## Required Changes
- `F01` | Scope: same-task | Classification: blocking | Owner hint: `CodexAppServerManager._evict_lru_idle` / `evict` | `backend/codex_app_server.py:498-522,348-403` | Problem: la evicción hacía `self._servers.pop(...)` y después esperaba `_terminate_and_cleanup(...)` sin tomar el lock del tenant. Durante ese `await`, otro `acquire` del mismo `user_id` podía obtener el lock, ver que no había server y hacer spawn usando el mismo `CODEX_HOME` mientras el proceso anterior aún estaba snapshotando/limpiando. | Required change: serializar la evicción y el acquire del tenant objetivo durante todo el terminate/snapshot/cleanup, sin ciclo de locks, y añadir una prueba de acquire concurrente durante cleanup. | Status: resolved

## Remediation History
### Round 1
- Implementer report/diff: `plans/chatgpt-codex-auth/task-T02-report.md:239-292`; remediación en `backend/codex_app_server.py:321-327,348-403,405-428,462-522` y test en `tests/backend/test_codex_app_server.py:412-495`.
- IDs checked: `F01`.
- Result: `F01` resolved. `_evict_lru_idle` y `evict` adquieren el lock de evicción del tenant objetivo antes de retirar el registro y lo mantienen durante `_terminate_and_cleanup` completo; `acquire` toma primero el slot global y luego espera el lock de evicción del mismo tenant antes del spawn/restauración. El lock de evicción es hoja y no anida otros locks, por lo que no se observa ciclo de locks. El test gatea el snapshot, lanza el acquire concurrente y exige restore solo después de `snapshot_done` y `home_cleaned`; el reporte documenta que falló con el código pre-fix y pasó tras la corrección.

## Evidence
- El lookup/pop del LRU es síncrono y por ello no hay una carrera de diccionario entre dos callbacks del event loop en `:452-459`; el defecto aparece porque el `await` posterior permite que el `user_id` sea adquirido de nuevo antes de finalizar el cleanup.
- `19 passed` en la suite específica y `484 passed, 3 skipped` en backend; las pruebas existentes no intercalan acquire del tenant evictado durante snapshot/cleanup.
- Re-review ejecutado: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q` → `20 passed, 1 warning in 5.18s`.
- Re-review ejecutado: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q` → `485 passed, 3 skipped in 16.64s`.

## Limitations
- No se ejecutó el binario Codex real ni un flujo autenticado; la receta indica que requieren credenciales y corresponden al gate live T10.
- No se modificó código de producción ni tests.
