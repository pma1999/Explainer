# Review: task/T03

## Verdict
APPROVE

## Functional Verification
- `13 passed, 1 warning` en `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q`.
- `33 passed, 1 warning` en `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py tests/backend/test_codex_client.py -q`.
- Revisados el diff aislado (los archivos T03 son nuevos/untracked), el brief, report, constraints, receta y fixtures.

## Spec Compliance
- Cumple routing exacto de `gpt-5.6-luna` y sus aliases.
- `call_codex_chat` es `async`, espera directamente al manager y a `request`, sin `asyncio.to_thread`.
- Cumple `thread/start` + `turn/start`, override de modelo, sin tools y retry conversacional acotado sin reenviar fuente/system.
- `CodexUsage` conserva coste cero, fuente `chatgpt_quota`, una petición por llamada y parseo defensivo de conteos reportados.
- Jerarquía y mensajes UX de cuota, auth y saturación cumplen; timeout y errores no mapeados conservan su tratamiento tipado de T02.
- Los 13 tests cubren los escenarios solicitados, incluyendo uso completo/parcial/ausente, retry, agotamiento, timeout y capacidad.

## Code Quality
- Pass; la implementación es acotada, reutiliza las constantes y tipos de T02, y no altera el fake ni código de producción ajeno a T03.

## Named Risk Checks
- Asincronía: inspección de `call_codex_chat`; no hay `asyncio.to_thread` y todas las operaciones del app-server se esperan con `await`.
- Wire contract: inspeccionados `_turn_params`, extracción de `threadID`, texto final y fixtures; los tests codex combinados pasan.
- Usage: `_parse_usage` solo toma campos presentes y deja ceros ante ausencia; no calcula totales ni coste inventados.
- Errores: inspeccionados `_map_request_error` y los tipos de T02; `UsageLimitExceeded`/auth-refresh se mapean y errores restantes se relanzan.
- Seguridad de logs/retry: los logs solo incluyen identificador truncado, modelo, tamaños y error de parseo truncado; el turno correctivo no contiene fuente ni system prompt, verificado por test.
- Modelo: `backend/codex_model_routing.py` expone exactamente el modelo y aliases requeridos.

## Required Changes
- None.

## Remediation History
None until re-review.

## Evidence
- `backend/codex_client.py:329-424` implementa el flujo async, retry, mapeo y conversión de timeout/spawn.
- `backend/codex_client.py:104-194` implementa `CodexUsage` y parseo defensivo.
- `backend/codex_model_routing.py:11-14` contiene las constantes requeridas.
- `tests/backend/test_codex_client.py` contiene 13 tests y verifica requests correctivos, mensajes y usage.

## Limitations
- No se ejecutó la suite backend completa; el alcance de esta review se verificó con las dos suites codex relevantes. El propio report documenta fallos de T02 por interferencia de `main.py` de T04, fuera del alcance de T03.
- No se hizo llamada autenticada contra el binario Codex real; la receta identifica esa validación como gate posterior y los tests usan el fake autorizado.
