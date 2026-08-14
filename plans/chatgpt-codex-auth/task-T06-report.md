# Task T06 Report

## Status
DONE

## Outcome
Añadidas las cuatro variantes Codex de la familia con el contrato congelado de
`plan.md` → Cross-task interfaces y `global-constraints.md` §Agent variants,
como corrutinas `async` que se esperan directo (nunca `asyncio.to_thread`),
con `user_id` en la posición de `api_key` de las `_ds` y devolviendo
`(data, CodexUsage)` (el formatter `(dict, dict)`):

- `backend/agents/recorrido.py`: `async def run_recorrido_codex(user_id,
  source_text, identificacion, model=CODEX_MODEL, target_language="es-ES")` —
  espejo de `run_recorrido_ds` vía `await call_codex_chat` con
  `build_recorrido_openrouter_system_instruction` y la validación existente
  (`isinstance(content, dict)` → `CodexError`).
- `backend/agents/resources.py`: `async def run_resources_codex(user_id,
  source_text, identificacion, model=CODEX_MODEL, target_language="es-ES")` —
  espejo de `run_resources_ds` **sin Tavily ni tools en v1**: nuevo builder
  `build_resources_codex_system_instruction` (base compartida
  `build_resources_system_instruction` + `CODEX_CONTRACT_SUFFIX` que declara
  "recomienda desde tu conocimiento, sin búsqueda web" y el JSON contract con
  la URL condicionada a "alta confianza de tu conocimiento"); el user message
  también elimina la mención de rondas de búsqueda de la variante `_ds`.
- `backend/agents/review.py`: `async def run_review_codex(user_id,
  explainer_content, part_title, target_language="es-ES", model=CODEX_MODEL)`
  — espejo de `run_review_ds` con `build_review_system_instruction`, el
  validador existente `_validate_review_payload` y el patrón de reintentos de
  review vía un nuevo helper async `_call_codex_with_validation_retries`
  (espejo de `_call_deepseek_with_validation_retries`; `call_operation()` queda
  FUERA del try → los errores tipados del cliente se propagan sin envolver).
- `backend/agents/formatter.py`: `async def format_explainer_content_codex(
  user_id, explainer_data, target_language="es-ES")` — espejo de
  `format_explainer_content_ds`: campos en paralelo vía `asyncio.gather` de
  `_format_text_codex` (await directo de `call_codex_chat` por campo, fail-safe
  como la `_ds`), mismo `_apply_parallel_formatter_results` y
  `_build_formatter_usage_summary` con `model=CODEX_MODEL`: coste 0.0
  (`CodexUsage.cost_usd=0.0`) y conteos reportados por campo si existen;
  `_empty_formatter_usage()` sin campos.

Logs sin prompts fuente completos ni credenciales: `user_id[:8]`, longitudes,
previews truncados (`identificacion[:150]`, `part_title[:80]`, `context[:80]`)
y conteos — mismo patrón de las `_ds` y del cliente T03.

`tests/backend/test_codex_agents_family.py` (nuevo, 12 tests asyncio sobre el
fake de T02 read-only con `scripted_turn` y fixtures JSON propios en
`tests/backend/fixtures_codex/`): felices deterministas, inválido →
reintento → éxito/`CodexError`, `CodexRateLimitError` propagado (incluido el
bucle de reintentos de review), formatter con campos paralelos (5 llamadas,
conteos agregados ×5, coste 0) y `_empty_formatter_usage()` sin campos.

## Acceptance Criteria
- `run_recorrido_codex` con la firma congelada, espejo de `run_recorrido_ds`
  con `call_codex_chat` + `build_recorrido_openrouter_system_instruction` y la
  validación de payload existente -> pass
  (`TestRecorridoCodex::test_happy_path_returns_payload_and_usage` verifica
  payload determinista, `CodexUsage` con conteos, `user_id`/`model`/`system`
  capturados; `test_non_object_json_raises_codex_error`).
- `run_resources_codex` sin Tavily ni herramientas, prompt del sistema con
  "sin búsqueda web", validador de resources existente -> pass
  (`TestResourcesCodex::test_happy_path_without_web_search` + aserciones sobre
  el system prompt capturado: contiene "sin búsqueda web", ni "tavily" ni
  "openrouter_web_search"; `test_codex_system_instruction_declares_no_web_search`;
  `test_non_object_json_raises_codex_error`).
- `run_review_codex` con `build_review_system_instruction` y la
  validación/retries de review existentes -> pass (`TestReviewCodex`: feliz
  validado con 5 preguntas; inválido → reintento → éxito con 2 llamadas;
  agotado → `CodexError` con `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES + 1`
  llamadas; `CodexRateLimitError` propagado sin ser envuelto por el retry loop).
- `format_explainer_content_codex` con campos en paralelo vía
  `await call_codex_chat`, mismo `_build_formatter_usage_summary` con coste 0
  y conteos reportados -> pass (`TestFormatterCodex::test_parallel_fields_and_usage_summary`:
  5 llamadas, todos los campos reemplazados, títulos intactos, conteos ×5,
  `cost == 0.0`; `test_no_fields_returns_empty_formatter_usage`).
- Logs sin prompts fuente completos ni credenciales -> pass por construcción
  (mismo patrón de log de las `_ds` + cliente T03: solo `user_id[:8]`,
  longitudes y previews truncados; sin contenido de fuente ni credenciales).
- Tests `tests/backend/test_codex_agents_family.py` con el fake vía
  `CODEX_BIN_PATH`, `scripted_turn` y fixtures propios -> pass (12/12; ver Tests).
- Scope: solo los 4 agentes + test nuevo + fixtures propios -> pass
  (git status: mis cambios son `recorrido.py`, `resources.py`, `review.py`,
  `formatter.py`, `test_codex_agents_family.py`, `fixtures_codex/`; T05 ha
  tocado en paralelo `segmentador.py`/`page_classifier.py`/`explainer_codex.py`/
  `test_codex_agents_core.py` — archivos disjuntos, no los toqué).

## Files Changed
- `backend/agents/recorrido.py` - modified; imports codex + `run_recorrido_codex`
  (espejo async de `run_recorrido_ds`).
- `backend/agents/resources.py` - modified; imports codex, `CODEX_CONTRACT_SUFFIX`,
  `build_resources_codex_system_instruction` (sin búsqueda web) +
  `run_resources_codex` (sin Tavily/tools).
- `backend/agents/review.py` - modified; imports codex (+`Awaitable`),
  `_call_codex_with_validation_retries` (async) + `run_review_codex`.
- `backend/agents/formatter.py` - modified; imports codex, `_format_text_codex`
  (await directo por campo, fail-safe) + `format_explainer_content_codex`
  (campos en paralelo, usage con coste 0).
- `tests/backend/test_codex_agents_family.py` - created; 12 tests asyncio sobre
  el fake de T02 (scripted_turn/usage_limit) y patcheos puntuales del
  `call_codex_chat` de cada módulo (captura de kwargs / conteo / fakes de
  payload para los reintentos de review).
- `tests/backend/fixtures_codex/turn_recorrido_valid.json` - created; turno
  `scripted_turn` con payload determinista de recorrido.
- `tests/backend/fixtures_codex/turn_recorrido_array_json.json` - created;
  turno con JSON array (no-objeto) para el caso `CodexError`.
- `tests/backend/fixtures_codex/turn_resources_valid.json` - created; turno con
  payload determinista de resources.
- `tests/backend/fixtures_codex/turn_review_valid.json` - created; turno con 5
  preguntas válidas (contrato de review).
- `tests/backend/fixtures_codex/turn_formatter_markdown.json` - created; turno
  con `{"markdown": ...}` y usage reportado.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/agents/recorrido.py` | `run_recorrido_codex(user_id, source_text, identificacion, model=CODEX_MODEL, target_language="es-ES") -> tuple[dict, CodexUsage]` | Nuevo: corrutina async, espejo de `run_recorrido_ds` |
| `backend/agents/resources.py` | `CODEX_CONTRACT_SUFFIX` | Nuevo: política "sin búsqueda web" + JSON contract codex |
| `backend/agents/resources.py` | `build_resources_codex_system_instruction(target_language)` | Nuevo: base compartida + suffix codex (sin tools) |
| `backend/agents/resources.py` | `run_resources_codex(user_id, source_text, identificacion, model=CODEX_MODEL, target_language="es-ES") -> tuple[dict, CodexUsage]` | Nuevo: corrutina async, sin Tavily en v1 |
| `backend/agents/review.py` | `_call_codex_with_validation_retries(*, call_operation, validate_payload, operation_label)` | Nuevo: espejo async de `_call_deepseek_with_validation_retries`; `call_operation()` fuera del try |
| `backend/agents/review.py` | `run_review_codex(user_id, explainer_content, part_title, target_language="es-ES", model=CODEX_MODEL) -> tuple[dict, CodexUsage]` | Nuevo: corrutina async, espejo de `run_review_ds` |
| `backend/agents/formatter.py` | `_format_text_codex(user_id, text, context, target_language) -> tuple[str, Any]` | Nuevo: campo único vía `await call_codex_chat`, fail-safe |
| `backend/agents/formatter.py` | `format_explainer_content_codex(user_id, explainer_data, target_language="es-ES") -> tuple[dict, dict]` | Nuevo: campos en paralelo, usage coste 0 |
| `tests/backend/test_codex_agents_family.py` | 12 tests + helpers `_uid`/`_turn_payload`/`_set_scripted_turn`/`_install_capturing_wrapper` | Nuevo: suite del contrato T06 |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_family.py -q`
  Result: pass — `12 passed, 1 warning in 1.16s` (warning esperado:
  `APP_ENCRYPTION_KEY` no configurada).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py tests/backend/test_codex_agents_family.py -q`
  Result: pass — `25 passed, 1 warning in 2.70s` (T03 + T06, singleton
  compartido en cualquier orden).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_api.py tests/backend/test_codex_agents_family.py -q`
  Result: pass — `47 passed in 1.64s` (orden de colección adverso con
  `main.py` de T04: mi suite es inmune, parche por test del singleton).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_deepseek_aux_agents.py tests/backend/test_review.py tests/backend/test_formatter.py tests/backend/test_formatter_deepseek.py tests/backend/test_formatter_openrouter.py tests/backend/test_openrouter_aux_agents.py tests/backend/test_resources_url_sanitization.py -q`
  Result: pass — `76 passed in 2.62s` (suites `_ds`/`_or` de los 4 módulos: sin
  regresiones por los imports/variantes nuevas).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
  Result: fail — `512 passed, 22 failed, 3 skipped in 33.66s`. Los 22 fallos
  NO son míos: 17 en `tests/backend/test_codex_app_server.py` (T02 read-only,
  interferencia de `main.py` de T04 en la colección — exactamente el baseline
  documentado en el reporte de T03) y 5 en `tests/backend/test_codex_agents_core.py`
  (T05, archivo creado DURANTE mi sesión por el implementador paralelo; 1 de
  esos 5 falla incluso en solitario — suite de T05 en curso, no toqué esos
  archivos).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend --ignore=tests/backend/test_codex_agents_core.py -q`
  Result: pass — `507 passed, 17 failed, 3 skipped in 28.68s`. Los 17 fallos
  restantes son exactamente los de T02/T04 ya conocidos (mismo fichero y
  recuento que el reporte de T03); ningún fallo en archivos de mi alcance.
- Command: `.venv-win/Scripts/python.exe -m py_compile backend/agents/recorrido.py backend/agents/resources.py backend/agents/review.py backend/agents/formatter.py tests/backend/test_codex_agents_family.py`
  Result: pass — `compile OK`.

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_family.py -q`
  → `ImportError: cannot import name 'format_explainer_content_codex' from
  'backend.agents.formatter'` (1 error en colección) — fallo por el motivo
  esperado: las variantes aún no existían.
- GREEN: mismo comando tras implementar las 4 variantes → `12 passed,
  1 warning`. Verificación adicional intermedia: las suites `_ds`/`_or` de los
  4 módulos siguen en verde (76 passed) y T03+T06 juntas (25 passed).

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T06-brief.md` (completo)
- `plans/chatgpt-codex-auth/global-constraints.md` §Agent variants (además
  §Codex client and errors y §Fake app-server para el contrato de T03)
- `plans/chatgpt-codex-auth/context-map.md` (orientación)
- `plans/chatgpt-codex-auth/plan.md` 172-256 (Cross-task interfaces, firmas
  exactas)
- `plans/chatgpt-codex-auth/task-T03-report.md` (contrato de T03 y baseline de
  fallos de la suite completa)
- `backend/agents/recorrido.py` 1-619 (run_recorrido_ds 563-619)
- `backend/agents/resources.py` 1-730 (builders 240-300, run_resources_ds
  648-730)
- `backend/agents/review.py` 1-519 (helpers 169-319, run_review_ds 468-518)
- `backend/agents/formatter.py` 1-730 (collect/empty/summary/apply 309-457,
  _format_text_ds_sync 525-576, format_explainer_content_ds 693-730)
- `backend/codex_client.py` (completo: call_codex_chat, CodexUsage, errores)
- `backend/codex_model_routing.py` (CODEX_MODEL)
- `tests/backend/fake_codex_app_server.py` (escenarios scripted_turn/usage_limit;
  read-only)
- `tests/backend/test_codex_client.py` 1-328 (patrón de suite: env antes del
  import, singleton parcheado por test, loop de sesión)

Extra reads:
- `backend/codex_app_server.py` 160-204, 340-459 - semáforo por proceso y
  `acquire` serializado por usuario: confirmar que `gather` de campos del
  formatter no deadlockea con el límite 5 (riesgo nombrado del brief) y que los
  acquires concurrentes del mismo `user_id` son seguros.
- `tests/backend/test_formatter_deepseek.py` 1-80 - patrón de tests del
  formatter `_ds` (paylohad de campos y fail-safe) para espejar el escenario.
- `pytest.ini` + `scripts/run_pytest.py` - runner y loop scope (function).
- `tests/backend/test_codex_agents_core.py` (solo para diagnosticar los 5
  fallos de la suite completa) - confirmar que son de T05 (assert de grabación
  de requests en su propio test; 1 fallo incluso en solitario) y no de mis
  cambios.

Pack gaps:
- None (todo el Context Pack existía y coincidía; el fake de T02 cubre
  `scripted_turn` y `usage_limit` sin editarlo).

## Decisions
- **`build_resources_codex_system_instruction` nuevo en resources.py**: la
  variante `_ds` reusa `build_resources_deepseek_system_instruction`, cuyo
  suffix describe la herramienta `tavily_search` y una URL "de tus resultados
  de búsqueda Tavily" — inaceptable para v1 sin tools. El builder codex reusa
  la base compartida `build_resources_system_instruction` + un
  `CODEX_CONTRACT_SUFFIX` propio que declara "recomienda desde tu conocimiento,
  sin búsqueda web" y condiciona `url` a "alta confianza de tu conocimiento".
  El user message también omite la mención de "rondas de búsqueda web" de la
  `_ds`. La base compartida sigue mencionando "Verificación via Google
  Search"; el suffix codex la anula explícitamente (mismo mecanismo con el que
  cada suffix de proveedor ajusta la base).
- **`_call_codex_with_validation_retries` (async) en review.py**: espejo de
  `_call_deepseek_with_validation_retries`; `call_operation()` queda FUERA del
  try (igual que en la `_ds`), así `CodexRateLimitError`/`CodexAuthError` se
  propagan sin ser envueltos ni reintentados. Los fallos de validación
  retryables (`_is_retryable_payload_validation_error`) reintentan y lanzan
  `CodexError` al agotar — el test
  `test_rate_limit_error_not_swallowed_by_retry_loop` lo fija explícitamente.
- **Formatter fail-safe (espejo `_ds`)**: `_format_text_codex` captura
  `CodexError` y devuelve el texto original (semántica documentada del módulo
  "Every call is fail-safe"). A diferencia de recorrido/resources/review, el
  formatter NO propaga `CodexRateLimitError` — mismo comportamiento que la
  variante `_ds` con `DeepSeekError`.
- **Concurrencia del formatter**: el `gather` lanza una llamada por campo sin
  cap adicional — idéntico a `format_explainer_content_ds` (el riesgo nombrado
  pide "no acotar MÁS que la `_ds`"). El semáforo por proceso
  (`CODEX_PER_PROCESS_MAX_CONCURRENCY=5`) serializa los excesos sin deadlock
  (verificado: `request()` lo adquiere por llamada y `acquire` se serializa
  por usuario). El test de 5 campos corre contra el fake real y pasa.
- **Tests de reintentos de review con fake de `call_codex_chat` parcheado**
  (no vía `scripted_turn`): el bucle de validación de review está EN el agente
  (re-invoca `call_codex_chat` completo), no en el cliente; un fake async que
  devuelve payload inválido→válido (o siempre inválido, o lanza
  `CodexRateLimitError`) prueba exactamente esa lógica con conteo determinista
  de llamadas. Los caminos felices y los errores tipados sí pasan por el fake
  real de T02 con `scripted_turn`/`usage_limit` (salidas vía fixtures propios).
- **Sin logs de prompts completos**: todas las variantes loguean solo
  `user_id[:8]`, longitudes (`source_chars`, `identificacion_length`,
  `explainer_chars`) y previews truncados (`identificacion[:150]`,
  `part_title[:80]`, `context[:80]`) — mismo patrón de las `_ds` y del cliente
  T03; el contenido fuente nunca se loguea.

## Concerns / Follow-ups
- **Frescura de resources sin búsqueda (riesgo R-RESOURCES del plan, ya
  decidido en el brief)**: v1 recomienda desde el conocimiento del modelo; la
  verificación de URLs/títulos queda al estándar "alta confianza" del prompt.
  Documentado en el docstring de `run_resources_codex` y en el prompt.
- **Suite backend completa NO verde por causas ajenas**: (a) los 17 fallos de
  `tests/backend/test_codex_app_server.py` (T02 read-only) por la
  interferencia de `main.py` de T04 en la colección — baseline ya documentado
  en el reporte de T03; (b) `tests/backend/test_codex_agents_core.py` (T05,
  creado durante mi sesión) tiene 5 fallos en la suite completa y 1 en
  solitario (assert de grabación de requests en su propio test) — suite de T05
  en curso, archivos disjuntos que no toqué. Mi suite pasa en todos los
  órdenes probados (solo, con test_api.py, con T03, y en la suite completa).
- `format_explainer_content_codex` usa `model=CODEX_MODEL` fijo en el campo y
  en el resumen de usage (el contrato congelado no expone parámetro `model`);
  T07 no necesita override.

## Remediation History
None for the initial implementation.
