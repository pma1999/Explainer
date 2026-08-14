# Review: task/T01

## Verdict
APPROVE

## Functional Verification
- Ejecutado `.venv-win/Scripts/python.exe scripts/run_pytest.py -q`: **610 passed, 3 skipped**.
- Ejecutado `npx vitest run`: **347 passed** (19 archivos).
- Revisada la traza `FAKE_CODEX_TRACE_FILE` en los tests de cliente y agentes: `turn/start` lleva `effort` cuando se proporciona, el retry conserva el valor y `thread/start` no lleva `effort` ni `config.model_reasoning_effort`.

## Spec Compliance
- Cumple allowlist `low/medium/high/xhigh/max`, default `medium`, firmas keyword finales, forwarding a las variantes, persistencia, validación por provider, degradación defensiva en review/reformat y nombres JSON cross-task (`codex_effort` / `codexEffort`).
- Cumple el contrato de wire y la evidencia de tracing requerida.
- Re-review: la semántica quedó unificada con el contrato congelado: `None` y `""` normalizan a `medium`; solo strings no vacíos fuera de la allowlist producen `ValueError`.

## Code Quality
- La implementación es consistente en el pipeline y las suites relevantes están verdes.
- Re-review: `call_codex_chat` valida localmente el `effort` no-None antes de adquirir/tocar el server y conserva `None` como campo ausente en el wire.

## Named Risk Checks
- **Wire/ordering:** revisados `_thread_start_params`, `_turn_params`, el bucle de retry y las firmas; el parámetro queda al final sin alterar orden posicional y el effort se reenvía a ambos turnos.
- **API/persistencia:** `api_process_project` valida solo Codex y persiste `codex_effort`; providers no-Codex lo dejan en `None`. Review/reformat resuelven config ausente/corrupta a medium con warning.
- **Frontend cross-task:** `landing.js` restaura valores inválidos/ausentes a `medium`, solo ofrece la allowlist y envía `codex_effort` únicamente para Codex; no hay una ruta UI observada que envíe `""`.
- **Compatibilidad del bundle previo:** no se alteran los órdenes posicionales de las variantes ni `ReviewRequest`; la adición de `ProcessProjectRequest.codex_effort` es la extensión prevista por el bundle de effort.

## Required Changes
- `RC-01` | Scope: changed-contract | Owner hint: `normalize_codex_effort` / contrato T02 | `backend/codex_model_routing.py:26-42`, `plans/codex-effort-selector/global-constraints.md:19-21`, `plans/codex-effort-selector/plan.md:49-52` | Problem: el código y tests hacen que `""` sea inválido y la API responda 400, mientras el contrato congelado dice explícitamente `None/'' -> medium`; la UI no envía vacío, pero la discrepancia puede romper consumidores directos y deja T01/T02 con contratos distintos. | Required change: decidir y registrar una única semántica; si se conserva el 400 exigido por aceptación, actualizar/re-secuenciar el contrato congelado y sus consumidores; si manda el contrato de normalización, hacer `""` medium y ajustar la aceptación/tests. | Status: resolved — `normalize_codex_effort(None)` y `normalize_codex_effort("")` devuelven `medium`; valores no vacíos fuera de `CODEX_EFFORT_LEVELS` lanzan `ValueError`. Brief, plan y ledger ahora declaran la misma semántica; tests de wire/API cubren `""` → `medium`.
- `RC-02` | Scope: same-task | Owner hint: `call_codex_chat` / `_turn_params` | `backend/codex_client.py:573-580, 635-639` | Problem: la documentación exige normalización y la restricción de calidad dice que el wire solo recibe allowlist, pero una llamada directa con `effort` arbitrario se reenvía sin validación. | Required change: validar en el límite compartido (o demostrar y garantizar que todos los callers externos pasan por `normalize_codex_effort`) antes de construir `turn/start`, preservando `None` como campo ausente. | Status: resolved — `call_codex_chat` llama a `normalize_codex_effort` para `effort` no-None antes de `codex_manager.acquire`; valores inválidos lanzan `ValueError` sin tocar el server, y `None` mantiene ausente la clave wire.

## Remediation History

### Round 1
- Implementer report/diff: `plans/codex-effort-selector/task-T01-report.md:216-256`
- IDs checked: `RC-01`, `RC-02`
- Result: ambos findings resolved. La implementación, tests y brief/plan/ledger son coherentes; no se identificaron regresiones directas en esta re-review.

## Evidence
- `git diff HEAD` revisado para backend, tests y el espejo frontend integrado; el diff muestra `effort` condicional únicamente en `_turn_params` y forwarding en todas las variantes/call sites Codex.
- `backend/codex_model_routing.py:22-42` confirma la allowlist/default, `None/""` → `medium` y `ValueError` solo para strings no vacíos fuera de allowlist.
- `backend/codex_client.py:610-617` confirma la validación local antes de `codex_manager.acquire`; `backend/codex_client.py:651-655` confirma forwarding al wire, y `tests/backend/test_codex_client.py:765-843` cubre `""`, valores inválidos y ausencia de contacto con server.
- `plans/codex-effort-selector/task-T01-brief.md:23-26`, `plan.md:49-52`, `progress.md:29-43` son coherentes con la implementación corregida.
- Re-run `.venv-win/Scripts/python.exe scripts/run_pytest.py -q`: **622 passed, 3 skipped**.
- Re-run `npx vitest run`: **347 passed** (19 archivos).
- `main.py:4863-4875` confirma validación exclusiva para provider Codex; el payload frontend usa `codex_effort` en `frontend/js/landing.js:1247-1250`.
- `frontend/js/landing.js:307-310` confirma fallback de restore a medium y la suite frontend cruza el contrato con 347 tests.

## Limitations
- No se ejecutó live gate contra el binario Codex autenticado; la compatibilidad real del servidor queda fuera de esta review y permanece como riesgo documentado de la receta.
