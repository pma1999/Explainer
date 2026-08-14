# Review: task/T04

## Verdict
APPROVE

## Functional Verification
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_link_endpoints.py -q` — **14 passed**.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q` — **512 passed, 3 skipped**.
- Revisé el diff aislado de `main.py` y `tests/backend/test_codex_link_endpoints.py`, el brief, el reporte, las restricciones y la receta.

## Spec Compliance
- Los cuatro endpoints usan `@api_key_rate_limit` y `Depends(get_current_user_id)`; no aceptan identidad en el body.
- El flujo feliz cifra `auth.json` mediante `encrypt_user_api_key`, persiste `linked` y obtiene `planType` best-effort.
- Verificados por código y tests: 400/409/503, cold start dentro/fuera de grace, timeout, cancelación y DELETE idempotentes.
- La suite completa confirma que la importación perezosa evita la regresión de T02; no observé ciclo de importación ni coste adicional en el camino no-Codex.
- RC-01 resuelto: el registro idempotente sobrevive a la recarga del módulo.

## Code Quality
- El manejo de secretos es correcto en los puntos revisados: no se imprimen `auth.json`, credenciales cifradas, códigos completos, `login_id` ni stderr; las respuestas usan mensajes UX.
- La separación de timeout, cancelación best-effort y limpieza local es clara y los tests cubren sus rutas principales.

## Named Risk Checks
- **Identidad/aislamiento:** inspección de firmas, decoradores y `_codex_home_dir`; la identidad procede del JWT y el path exige UUID completo.
- **Persistencia OAuth:** test feliz descifra el blob persistido y confirma `linked`/`plan_type`.
- **Errores y reintentos:** tests confirman 400/409/503 y que el spawn fallido no crea fila; no hay reintento silencioso.
- **Cold start/timeout:** tests confirman pending durante grace, failed con el mensaje exacto fuera de grace y failed+cancel tras timeout.
- **Cancel/delete:** tests confirman idempotencia, logout fallido no bloqueante, borrado de fila, evict y `CODEX_HOME`.
- **Registro del handler:** `_register_codex_login_completed_handler` usa una marca en la propia función handler; el test de estado post-reload confirma un único registro.

## Required Changes
- `RC-01` | Scope: same-task / Owner hint: `main.py:_register_codex_login_completed_handler` | `main.py:753-771` | Problem: el guardado de idempotencia anterior dependía de un booleano global y de identidad de función, provocando duplicación tras `importlib.reload(main)`. | Why: riesgo de doble procesamiento de `account/login/completed`. | Required change: marca estable en el handler y prueba de registro repetido/reload. | Status: resolved

## Remediation History
### Round 1
- Implementer report/diff: `plans/chatgpt-codex-auth/task-T04-report.md:219-251`
- IDs checked: `RC-01`
- Result: **resolved**. `main.py:753-771` elimina el booleano global y la comparación por identidad; detecta la marca estable del handler conservado por el manager. `tests/backend/test_codex_link_endpoints.py:389-430` siembra un handler stale, distinto de la función actual, con la marca y verifica exactamente un handler.

## Evidence
- `main.py:802-1002`: endpoints y formas de respuesta revisados.
- `main.py:620-751`: cancelación, timeout, lectura/cifrado de `auth.json` y handler revisados.
- `tests/backend/test_codex_link_endpoints.py:180-386`: 13 escenarios de aceptación revisados.
- Suite backend ejecutada en esta re-review: `512 passed, 3 skipped`.
- Archivo T04 ejecutado en esta re-review: `14 passed`.

## Limitations
- No se ejecutó un flujo contra el binario/servidor Codex real; RC-01 sí quedó verificado mediante el test de registro post-reload y las suites indicadas.
