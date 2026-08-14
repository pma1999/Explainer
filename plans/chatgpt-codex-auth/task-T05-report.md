# Task T05 Report

## Status
DONE_WITH_CONCERNS

## Outcome
Variantes Codex de los agentes núcleo implementadas como **corrutinas `async`** que se esperan
directo (nunca `asyncio.to_thread`), espejo posicional de las `_ds` sobre `call_codex_chat`
(T03, contrato intacto):

- `backend/agents/explainer_codex.py` (nuevo) con las cinco firmas congeladas de `plan.md` →
  Cross-task interfaces: `run_explainer_codex`, `run_subpart_explainer_codex`,
  `run_explainer_codex_validated`, `run_subpart_explainer_codex_validated`,
  `run_with_codex_explainer_validation`. `user_id` ocupa la posición de `api_key`;
  `validator_user_id` la de `validator_api_key`. Sin import de `deepseek_client` ni key de
  DeepSeek: todo pasa por `await call_codex_chat(...)`.
- El reintento conversacional replica `_DeepSeekExplainerConversation` (`_CodexExplainerConversation`):
  system + primer user message byte-idénticos; cada regeneración añade el turno `assistant`
  anterior + el feedback (`format_explainer_retry_context`, `include_previous_result=False`).
  El validador de completitud se ejecuta vía Codex (`check_explainer_validation_codex` +
  `run_with_codex_explainer_validation`, fail-open como el resto de validadores).
- `backend/agents/segmentador.py` gana `run_segmentador_codex(api_key, source_text, description,
  source_kind="pdf", model=CODEX_MODEL, target_language="es-ES", *, conversation=None,
  correction=None) -> tuple[dict, CodexUsage, list]` con los mismos builders
  `_openrouter_segmentador_*`; el retry por cobertura mantiene el prefijo byte-idéntico.
- `backend/agents/page_classifier.py` gana `run_page_classifier_codex(api_key, source_text,
  total_pages, model=CODEX_MODEL) -> tuple[frozenset, CodexUsage, dict]`.
- Logs sin prompts fuente completos ni credenciales: solo `user_id[:8]`, modelo, longitudes y
  previews truncados (mismo patrón que las `_ds`).
- `tests/backend/test_codex_agents_core.py` (10 tests, loop de sesión, fake de T02 read-only vía
  `CODEX_BIN_PATH`, salidas deterministas con `scripted_turn` + 8 fixtures JSON propios) — 10/10
  verdes.

## Acceptance Criteria
- Las 5 funciones de `explainer_codex.py` con firmas congeladas, corrutinas async, `user_id`/
  `validator_user_id` en la posición de `api_key`/`validator_api_key` -> pass (verificado con
  `inspect.iscoroutinefunction` y `inspect.signature` para las 7 variantes; defaults
  `model=CODEX_MODEL`).
- Reutiliza helpers sin duplicar prompts/validación: `_build_inline_source_message` y
  `_payload_correction_message`/`_is_retryable_payload_validation_error` (de
  `explainer_deepseek.py`), builders y validadores de payload (de `explainer_openrouter.py`),
  `ExplainerValidationContext`/`ExplainerValidationReport`/`format_explainer_retry_context` y el
  prompt base del revisor + parseo/aceptación fail-open (de `completeness_validator.py`) ->
  pass (imports directos, sin copiar lógica; la única constante nueva es
  `_CODEX_VALIDATOR_SYSTEM_PROMPT`, que reutiliza `_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION`
  en un bloque `<codex_json_mode_contract>`).
- Reintento conversacional: system + primer user message byte-idénticos; cada regeneración añade
  turno anterior + feedback; validador vía Codex sin key de DeepSeek ->
  pass (`test_run_explainer_codex_validated_retries_on_incomplete`: el texto del turno de
  reintento empieza con el primer user message y contiene `explicacion_anterior_no_valida`;
  `test_run_explainer_codex_validated_exhausted_raises_validation_error`: 6 llamadas con
  `ExplainerValidationError`; ningún import de `deepseek_client` en el módulo).
- `run_segmentador_codex` con la firma exacta, espejo posicional sobre `call_codex_chat` con los
  mismos `_openrouter_*` builders y prefijo byte-idéntico ->
  pass (`test_run_segmentador_codex_happy_path_and_conversation_retry`: `conversation[0]`/
  `[1]` idénticos entre llamadas, system y temperature idénticos en el wire, `turn_texts[1]
  .startswith(turn_texts[0])`).
- `run_page_classifier_codex` con la firma exacta -> pass (`test_run_page_classifier_codex_happy_path`).
- Logs sin prompts fuente completos ni credenciales -> pass por construcción (solo `user_id[:8]`,
  longitudes y previews truncados; revisado en los 3 módulos).
- Tests `tests/backend/test_codex_agents_core.py` (asyncio; fake de T02 read-only; fixtures JSON
  propios): cada variante devuelve `(data, CodexUsage)` con payload válido; payload inválido →
  reintento y luego `CodexError`; validación de completitud con reintento vía
  `run_with_codex_explainer_validation`; segmentador con retry de conversación; classifier feliz
  y con error (UsageLimitExceeded → `CodexRateLimitError`) -> pass (10/10; `fake_codex_app_server.py`
  intacto).
- Scope: solo los archivos del brief -> pass (git status; `segmentador.py`/`page_classifier.py`
  solo adiciones; `backend/codex_client.py`, `codex_model_routing.py`, `codex_app_server.py`,
  `main.py` y el resto intactos).

## Files Changed
- `backend/agents/explainer_codex.py` - created; las 5 funciones del contrato + helpers privados
  (`_call_codex_with_validation_retries`, `_call_codex_json_with_pdf_fallback`,
  `_CodexExplainerConversation`, `check_explainer_validation_codex`) y
  `_CODEX_VALIDATOR_SYSTEM_PROMPT`.
- `backend/agents/segmentador.py` - modified; +imports de `codex_client`/`codex_model_routing` y
  `run_segmentador_codex` (aditivo, 87 líneas).
- `backend/agents/page_classifier.py` - modified; +imports y `run_page_classifier_codex`
  (aditivo, 65 líneas).
- `tests/backend/test_codex_agents_core.py` - created; 10 tests (loop de sesión, recording
  manager con wrapper cacheado por `user_id`, scripting secuencial de turnos vía
  `_parse_turn_json`).
- `tests/backend/fixtures_codex/` - created (8 fixtures nuevos):
  `turn_explainer_full.json`, `turn_explainer_subpart.json`, `turn_explainer_invalid.json`,
  `turn_segmentador.json`, `turn_classifier.json`, `turn_validator_accept.json`,
  `turn_validator_reject.json`, `turn_json_array.json`. Sin colisión con los de T03.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/agents/explainer_codex.py` | `run_explainer_codex(source_path, identificacion, model=CODEX_MODEL, mime_type="application/pdf", user_id="", pdf_cache_entry=None, page_numbers=None, target_language="es-ES") -> tuple[dict, CodexUsage]` | created (async) |
| `backend/agents/explainer_codex.py` | `run_subpart_explainer_codex(...) -> tuple[dict, CodexUsage]` | created (async) |
| `backend/agents/explainer_codex.py` | `run_explainer_codex_validated(..., user_id="", validator_user_id="", ..., validation_context=None, ...) -> tuple[dict, CodexUsage, list]` | created (async) |
| `backend/agents/explainer_codex.py` | `run_subpart_explainer_codex_validated(...) -> tuple[dict, CodexUsage, list]` | created (async) |
| `backend/agents/explainer_codex.py` | `run_with_codex_explainer_validation(*, initial_call, retry_call, user_id, label, validation_context=None) -> tuple[dict, CodexUsage, list]` | created (async; `user_id` en la posición de `deepseek_api_key`) |
| `backend/agents/explainer_codex.py` | `check_explainer_validation_codex(explanation, user_id, validation_context=None, model=CODEX_MODEL_AUXILIARY) -> tuple[ExplainerValidationReport, CodexUsage \| None]` | created (async, fail-open) |
| `backend/agents/segmentador.py` | `run_segmentador_codex(api_key, source_text, description, source_kind="pdf", model=CODEX_MODEL, target_language="es-ES", *, conversation=None, correction=None) -> tuple[dict, CodexUsage, list]` | created (async) |
| `backend/agents/page_classifier.py` | `run_page_classifier_codex(api_key, source_text, total_pages, model=CODEX_MODEL) -> tuple[frozenset, CodexUsage, dict]` | created (async) |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_core.py`
  Result: pass — 10 passed, 1 warning (RuntimeWarning de `APP_ENCRYPTION_KEY` en crypto.py,
  pre-existente y esperado en tests).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py tests/backend/test_codex_link_endpoints.py tests/backend/test_deepseek_aux_agents.py`
  Result: pass — 31 passed (regresión de T03/T04 y de los agentes `_ds` cuyos módulos toqué).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py`
  Result: pass — 20/20 en aislamiento.
- Verificación de contrato: `inspect.iscoroutinefunction` en las 7 variantes (todas corrutinas);
  `inspect.signature` de segmentador/classifier/explainer_validated (orden posicional exacto);
  fixtures validados con `_validate_full_explainer_payload`/`_validate_subpart_explainer_payload`
  antes de correr los tests.

## TDD Evidence
- RED: primera ejecución de `tests/backend/test_codex_agents_core.py` -> 5 failed, 5 passed.
  Causas: (1) mi `_RecordingManager.acquire` creaba un `_RecordingServer` nuevo por `acquire`
  con `setdefault`, perdiendo los requests de las llamadas 2..N del mismo `user_id` (fallaban
  las aserciones de secuencia en 4 tests); (2) `test_run_explainer_codex_invalid_payload_retries_then_codex_error`
  esperaba un único thread para todos los reintentos, pero el espejo de
  `_call_deepseek_with_validation_retries` re-lanza la llamada completa por intento
  (`thread/start` + `turn/start` por intento).
- GREEN: tras cachear el wrapper por `user_id` en `_RecordingManager` y corregir la secuencia
  esperada -> 10/10 pass en la misma sesión; sin cambios en el código de producción entre RED y
  GREEN (los fallos eran del helper de test y de una aserción).

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T05-brief.md`, `global-constraints.md` (§Agent variants, §Fake
  app-server, §Codex client), `context-map.md`, `plan.md` (Cross-task interfaces, §5, §6, §8).
- `backend/agents/explainer_deepseek.py` (plantilla completa), `backend/agents/segmentador.py`
  (1319-1420 `run_segmentador_ds` + builders 1077-1114 + contrato 989-1074),
  `backend/agents/page_classifier.py` (422-500 `run_page_classifier_ds` + imports + 101-213
  `OPENROUTER_SYSTEM_INSTRUCTION`/`_parse_classifier_result`).
- `backend/agents/completeness_validator.py` (validador y runner `_ds`; helpers privados
  reutilizados).
- `backend/codex_client.py` (contrato T03), `backend/codex_model_routing.py` (constantes),
  `tests/backend/fake_codex_app_server.py` (escenarios, read-only), `tests/backend/test_codex_client.py`
  (patrón de test: env, fixtures, recording, `_parse_turn_json` hook).
- `plans/chatgpt-codex-auth/task-T03-report.md` (formato de reporte del bundle).

Extra reads:
- `backend/agents/explainer_openrouter.py` 329-444 — validadores de payload exactos para
  construir fixtures válidas e inválidas (pregunta: ¿qué claves exige el contrato?).
- `backend/codex_app_server.py` (imports, `CODEX_HOME_ROOT`/`_home_root` init) — diagnóstico de
  la fragilidad de aislamiento de tests (ver Concerns).
- `tests/backend/test_codex_app_server.py` 1-120 — entender por qué falla en runs combinados.
- `pytest.ini` + `scripts/run_pytest.py` — configuración de marcadores/runner.
- `main.py` (grep `codex_app_server`) — confirmar import perezoso del runtime y la causa de la
  fragilidad pre-existente.
- `git stash` + runs combinados — prueba de que la fragilidad de T02 es pre-existente (baseline).

Pack gaps:
- None.

## Decisions
- `run_with_codex_explainer_validation` (firma `...` en plan.md): espejo async de
  `run_with_deepseek_explainer_validation` con `user_id` en la posición de `deepseek_api_key`;
  `initial_call`/`retry_call` son corrutinas; semántica idéntica a
  `_run_with_explainer_validation_core` (inicial + `MAX_EXPLAINER_VALIDATION_RETRIES=2`,
  validador fail-open, `ExplainerValidationError` al agotar).
- `check_explainer_validation_codex` vive en `explainer_codex.py` (T05 es dueña del módulo y
  `completeness_validator.py` NO está en el touch-list): importa los helpers privados
  (`_VALIDATOR_SYSTEM_PROMPT`, `_build_validator_user_message`, `_parse_validation_report`,
  `_accepted_report`, `_OPENROUTER_VALIDATOR_JSON_RETRY_INSTRUCTION`) en lugar de duplicar
  lógica — mismo patrón de imports privados entre módulos del paquete que ya usan
  `explainer_deepseek.py`/`explainer_codex.py` con `explainer_openrouter.py`.
- `_CODEX_VALIDATOR_SYSTEM_PROMPT` = prompt base del revisor + bloque
  `<codex_json_mode_contract>` que reutiliza la instrucción JSON existente (patrón de
  `_DEEPSEEK_VALIDATOR_SYSTEM_PROMPT` sin copiar constantes `DEEPSEEK_*`).
- Turnos `assistant` de las conversaciones: `json.dumps(data, ensure_ascii=False)` del payload
  parseado, porque `call_codex_chat` devuelve `(data, usage)` sin exponer el texto crudo del
  turno. Desviación mecánica documentada respecto al replay crudo de DeepSeek; el requisito del
  brief ("system + primer user message byte-idénticos; cada regeneración añade el turno anterior
  + el feedback") se cumple y se verifica en tests. No es relajación de contrato de firma.
- Reintento de payload no conversacional (`run_explainer_codex`/`run_subpart_explainer_codex`):
  espejo exacto de `_call_deepseek_with_validation_retries` (llamada completa por intento); el
  reintento conversacional queda para las variantes `_validated`.
- Errores de agente: JSON no-objeto → `CodexError` (espejo del `DeepSeekError` de las `_ds`);
  los errores del servidor (cuota/auth) se propagan mapeados por el cliente T03 sin intervención
  del agente.

## Concerns / Follow-ups
- **Fragilidad de aislamiento pre-existente en `test_codex_app_server.py` (T02)**: el singleton
  `codex_manager` congela `_home_root` en el primer import de `backend.codex_app_server` (env
  leído en import), y los tests de T02 asumen ser el primer importador. Cualquier módulo que
  importe antes con otro `CODEX_HOME_ROOT` (p.ej. `test_api.py` → `main.py`, o cualquier test
  codex) rompe sus 3 tests que asertan contra su constante `_TEST_HOME_ROOT`. Verificado como
  **pre-existente**: con mis cambios stasheados, `test_api.py + test_codex_app_server.py` falla
  17 tests; `test_codex_app_server.py` en aislamiento pasa 20/20. Mi archivo sigue el mismo
  patrón de env a nivel de módulo que el aprobado `test_codex_client.py` (T03) y sus tests son
  deterministas en cualquier orden (fixture por test que parchea `_home_root`). No es
  arreglable dentro del scope de T05 (el archivo de T02 no está en el touch-list); el runner del
  suite completo debe conocerlo.
- `quota_requests` acumula >1 por llamada validada (riesgo nombrado del brief): 1 turno del
  explainer + 1 turno del validador por evaluación. Comportamiento esperado, verificado en
  `test_run_explainer_codex_validated_retries_on_incomplete` (usage final quota_requests=1 +
  `validator_usages` con 2× quota_requests=1).

## Remediation History
### Round 1 - `plans/chatgpt-codex-auth/task-T05-review.md` (RC-01)
- Finding IDs: `RC-01`
- Status: addressed
- Delta: `tests/backend/test_codex_agents_core.py` (modificado; sin cambios de
  producción): +imports `CODEX_TIMEOUT_MESSAGE`/`CodexTimeoutError` y nuevo test
  `TestExplainerCodex.test_run_explainer_codex_timeout_propagates_codex_timeout_error`
  (uid 311). El test fuerza un timeout determinista del cliente con el escenario
  `slow_turn` del fake de T02 (`FAKE_CODEX_SLOW_DELAY_SECONDS=5` > timeout de
  request 0.2s inyectado por monkeypatch sobre la referencia `call_codex_chat`
  del módulo del agente — la firma congelada no expone `timeout`; el cliente y
  el fake reales hacen el trabajo), verifica que `run_explainer_codex` propaga
  `CodexTimeoutError` sin remapearlo ni envolverlo (`type(exc) is
  CodexTimeoutError`; el flujo espera `call_codex_chat` fuera de cualquier
  try/except — los catches existentes son solo de validación de payload, tras
  la llamada) y verifica el contrato de usuario que consumirá el pipeline
  (`exc.value.message == CODEX_TIMEOUT_MESSAGE`, mismo shape `.message` que el
  test de rate-limit).
- Tests:
  - RED: ausencia del escenario documentada antes del cambio — `grep` en
    `tests/backend/test_codex_agents_core.py` solo encuentra los escenarios
    `scripted_turn`/`scripted_error` (sin `CodexTimeoutError` ni `slow_turn`),
    y el baseline corre `10 passed` sin caso de timeout; RC-01 es la evidencia
    del hueco.
  - GREEN: `scripts/run_pytest.py tests/backend/test_codex_agents_core.py -q -k timeout`
    -> 1 passed, 10 deselected; `scripts/run_pytest.py tests/backend/test_codex_agents_core.py -q`
    -> 11 passed, 1 warning (pre-existente de `APP_ENCRYPTION_KEY`).
  - Regresión: `scripts/run_pytest.py tests/backend -q` -> 536 passed, 3 skipped,
    10 warnings (535 + 1 del test nuevo).
- Concerns: None (el test pasó a la primera: la implementación ya propagaba el
  error tipado correctamente; el gap era exclusivamente de cobertura, como
  señalaba el finding).
