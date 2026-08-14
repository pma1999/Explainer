# Task T03 Report

## Status
DONE

## Outcome
`backend/codex_model_routing.py` fija el modelo único `gpt-5.6-luna` y
`backend/codex_client.py` implementa el cliente de chat async sobre el app-server de T02 con el
contrato congelado de `global-constraints.md` §Codex client and errors:

- `call_codex_chat(*, user_id, messages, system_prompt, model=CODEX_MODEL,
  response_format="json_object", temperature=OPENROUTER_EXPLAINER_TEMPERATURE,
  timeout=CODEX_REQUEST_TIMEOUT_SECONDS) -> tuple[Any, CodexUsage]`: corrutina async que se
  espera directo (nunca `asyncio.to_thread`); `await codex_manager.acquire(user_id)` +
  `thread/start` + `turn/start` con override `model` por turno, sin tools. Con
  `response_format="json_object"` parsea el texto final con `json.loads` y reintenta
  conversacionalmente (máx. `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES=2` → 3 intentos)
  añadiendo un turno correctivo corto que NO reenvía la fuente ni el system prompt (el thread
  del app-server conserva el estado; patrón `_DeepSeekExplainerConversation`).
- Jerarquía congelada: `CodexError` (base con `.message`), `CodexRateLimitError`,
  `CodexAuthError`, `CodexBusyError`, `CodexTimeoutError`; re-usa `CodexSpawnError`/
  `CodexRequestError` de T02. `CodexSpawnError` (spawn sin hueco) → `CodexBusyError` con el
  mensaje UX congelado. `CodexRequestError.code` se mapea sin inventar códigos:
  `UsageLimitExceeded`/`RateLimitExceeded` (exactos) → `CodexRateLimitError`; códigos con
  semántica de auth/refresh (tokens `auth|refresh|login|loggedin|credential|unauthorized|
  session|expired` en el nombre normalizado) → `CodexAuthError`; el resto se re-lanza como
  `CodexRequestError` de T02 (`.code/.message/.data` intactos). Timeout de T02 → `CodexTimeoutError`.
- `CodexUsage` con `prompt_token_count`, `tool_use_prompt_token_count`, `candidates_token_count`,
  `thoughts_token_count`, `total_token_count` (ceros si el turno no los reporta; solo desde
  campos de usage del turno, snake_case y camelCase, en `usage` o al nivel superior del
  resultado), `cost_usd=0.0`, `cost_source="chatgpt_quota"`, `quota_requests=1`.
- Logs sin credenciales: solo `user_id[:8]`, `model`, longitudes y previews truncados; nunca
  `auth.json` ni el contenido de los mensajes fuente.

`tests/backend/test_codex_client.py`: 13 tests (loop de sesión, `CODEX_BIN_PATH` al fake de T02
read-only, sin red ni credenciales) + 6 fixtures de salida JSON propios en
`tests/backend/fixtures_codex/`. Todos los escenarios del brief verdes; el reintento
conversacional se verifica observando los requests reales al fake (turno correctivo corto sin
fuente ni system).

## Acceptance Criteria
- `backend/codex_model_routing.py` expone exactamente `CODEX_MODEL = "gpt-5.6-luna"`,
  `CODEX_MODEL_AUXILIARY = CODEX_MODEL`, `CODEX_EXPLAINER_MODELS = frozenset({CODEX_MODEL})` ->
  pass (`TestModelRouting::test_model_routing_constants`).
- Jerarquía `CodexError` con `.message` + subtipos; re-uso de `CodexSpawnError`/`CodexRequestError`
  de T02; mapeo por `code` sin inventar códigos; `CodexSpawnError` → `CodexBusyError` -> pass
  (`TestErrorHierarchy::test_hierarchy_frozen_and_message_attribute`,
  `TestErrorMapping::test_usage_limit_exceeded_maps_to_rate_limit_error`,
  `TestErrorMapping::test_auth_refresh_error_maps_to_auth_error` (`AuthRefreshFailed`),
  `TestErrorMapping::test_unmapped_error_re_raised_as_codex_request_error` (`BadTurn` → T02
  `CodexRequestError` con `.code` intacto), `TestTimeoutsAndCapacity::
  test_spawn_without_slot_raises_codex_busy_error` con los 3 procesos globales ocupados).
- `CodexUsage` con los atributos congelados; conteos solo desde campos reportados (defensivo,
  ceros si no existen) -> pass (`test_valid_json_turn_returns_parsed_data_and_usage`,
  `test_usage_zero_when_turn_reports_no_usage`, `test_usage_partial_reported_fields_filled`).
- `call_codex_chat` async con la firma congelada; `acquire` + `thread/start` + `turn/start` con
  override `model`; JSON inválido → reintento conversacional (máx.
  `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`) sin reenviar la fuente; sin tools; se espera
  directo, nunca en `to_thread` -> pass (`test_valid_json_turn_returns_parsed_data_and_usage`
  verifica `["thread/start", "turn/start"]` con `model == CODEX_MODEL` y `system` en el primer
  turno; `test_invalid_json_retries_with_corrective_turn_then_succeeds` verifica 2 turn/start,
  el correctivo sin `system` ni fuente, con "JSON"; `test_json_retries_exhausted_raises_codex_error`
  verifica 1 + `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES` turn/start y `CodexError` base).
- Timeout → `CodexTimeoutError` -> pass (`test_timeout_raises_codex_timeout_error`, escenario
  `slow_turn`, `timeout=0.2`).
- Sin credenciales en logs -> pass por construcción (solo `user_id[:8]`, modelo, `chars=`,
  previews truncados; los tests de reintento confirman además que el contenido fuente no se
  reenvía al servidor en los turnos correctivos).
- Tests `tests/backend/test_codex_client.py` con el fake vía `CODEX_BIN_PATH`, marcados asyncio,
  consumiendo el fixture sin editarlo -> pass (13/13; `fake_codex_app_server.py` intacto).
- Scope: solo `backend/codex_client.py`, `backend/codex_model_routing.py`,
  `tests/backend/test_codex_client.py` y `tests/backend/fixtures_codex/` -> pass (git status).

## Files Changed
- `backend/codex_client.py` - created; cliente async del app-server: jerarquía `CodexError`,
  `CodexUsage`, `call_codex_chat` con retry conversacional y mapeo de errores por `code`.
- `backend/codex_model_routing.py` - created; `CODEX_MODEL = "gpt-5.6-luna"` y alias/`frozenset`.
- `tests/backend/test_codex_client.py` - created; 13 tests (loop de sesión) sobre el fake de T02.
- `tests/backend/fixtures_codex/` - created; 6 fixtures de salida JSON de turno
  (`turn_valid_json.json`, `turn_valid_json_retry.json`, `turn_valid_json_no_usage.json`,
  `turn_partial_usage.json`, `turn_invalid_json_text.json`, `turn_text.json`).

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/codex_model_routing.py` | `CODEX_MODEL = "gpt-5.6-luna"` | Nuevo |
| `backend/codex_model_routing.py` | `CODEX_MODEL_AUXILIARY = CODEX_MODEL` | Nuevo |
| `backend/codex_model_routing.py` | `CODEX_EXPLAINER_MODELS = frozenset({CODEX_MODEL})` | Nuevo |
| `backend/codex_client.py` | `CodexError(Exception)` con `.message` | Nuevo: base de la jerarquía |
| `backend/codex_client.py` | `CodexRateLimitError` / `CodexAuthError` / `CodexBusyError` / `CodexTimeoutError` | Nuevos: subtipos con mensajes UX congelados |
| `backend/codex_client.py` | `CodexUsage` (`prompt_token_count`, `tool_use_prompt_token_count`, `candidates_token_count`, `thoughts_token_count`, `total_token_count`, `cost_usd=0.0`, `cost_source="chatgpt_quota"`, `quota_requests=1`) | Nuevo |
| `backend/codex_client.py` | `call_codex_chat(*, user_id, messages, system_prompt, model, response_format, temperature, timeout)` | Nuevo: corrutina async `-> tuple[Any, CodexUsage]` |
| `backend/codex_client.py` | `_parse_usage` / `_extract_final_text` / `_extract_thread_id` / `_turn_params` / `_map_request_error` / `_parse_turn_json` / `_payload_correction_message` | Nuevos: helpers privados (parseo defensivo, seam de tests, mapeo por `code`) |
| `tests/backend/test_codex_client.py` | 13 tests + `_RecordingManager`/`_RecordingServer` | Nuevo: suite del contrato T03 |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q`
  Result: pass — `13 passed, 1 warning` (warning esperado: `APP_ENCRYPTION_KEY` no configurada).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py tests/backend/test_codex_client.py -q`
  Result: pass — `33 passed, 1 warning in 7.47s` (ambas suites codex juntas, singleton compartido).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_api.py tests/backend/test_codex_client.py -q`
  Result: pass — `48 passed in 2.68s` (orden de colección con `main.py` importado antes: robusto).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
  Result: **fail** — `494 passed, 17 failed, 3 skipped, 26 warnings in 41.33s`. Los 17 fallos son
  TODOS de `tests/backend/test_codex_app_server.py` (T02, read-only para mí) y están causados por
  el `main.py` modificado en el working tree (T04 en curso): `main.py:63` importa
  `backend.codex_app_server` y `test_api.py:6` importa `main` a nivel de módulo → el singleton
  `codex_manager` se crea en la colección con el env por defecto (`/usr/local/bin/codex`,
  `/tmp/codex`, spawn wait 60) ANTES de que `test_codex_app_server.py` asigne su env en el
  import. Verificado: ese fichero solo pasa (20/20) y `test_api.py` + ese fichero reproduce los
  17 fallos sin mi módulo en la corrida. Mi suite es inmune (fixture que parchea el singleton
  por test, mismo patrón que `test_codex_link_endpoints.py`). No es mío arreglarlo (do-not-touch
  `main.py`; test de T02 no editable) → reportado al orquestador (ver Concerns).
- Command: `.venv-win/Scripts/python.exe -m py_compile backend/codex_client.py backend/codex_model_routing.py tests/backend/test_codex_client.py`
  Result: pass — `compile OK`.

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q`
  → `ImportError: cannot import name 'codex_client' from 'backend'` (1 error en colección) —
  fallo por el motivo esperado: el módulo del contrato aún no existía.
- GREEN: mismo comando tras implementar `codex_model_routing.py` + `codex_client.py` → `13 passed,
  1 warning`. Un fallo intermedio del test de agotamiento era del propio test (asertaba el turno
  correctivo sobre el PRIMER turn/start, que sí lleva la fuente); corregido a `requests[2:]`
  (los correctivos empiezan en el segundo turn/start) → suite completa en verde, y luego en verde
  también con `test_api.py` antes (orden de colección adverso) y en la suite completa (13/13).

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T03-brief.md` (completo)
- `plans/chatgpt-codex-auth/global-constraints.md` §Codex client and errors, §Fake app-server
  (además §Tenant isolation y §Agent variants para contexto)
- `plans/chatgpt-codex-auth/context-map.md` (orientación)
- `plans/chatgpt-codex-auth/integration-codex-appserver.md` (completo: override `model` en
  `turn/start`, `thread/start`, errores/quota)
- `plans/chatgpt-codex-auth/plan.md` 100-214 (sección 5 + Cross-task interfaces, firmas exactas)
- `backend/codex_app_server.py` (completo: `codex_manager.acquire`, `request`, jerarquía T02,
  constantes env)
- `tests/backend/fake_codex_app_server.py` (completo: escenarios y wire-format; read-only)
- `backend/deepseek_client.py` 1-100, 280-570, 740-784 (errores tipados, parseo defensivo,
  retries, `DeepSeekUsage`, `call_deepseek_chat`)
- `backend/agents/explainer_deepseek.py` 270-379 (`_DeepSeekExplainerConversation`,
  `_payload_correction_message`)
- `backend/agents/explainer_openrouter.py` 30-55 (constantes de reintento/temperatura)

Extra reads:
- `backend/deepseek_model_routing.py` - patrón del módulo de routing (modelo único + frozenset).
- `tests/backend/test_codex_app_server.py` - patrón de tests sobre el fake (env antes del
  import, loop de sesión, autouse `_no_supabase`/`_reset_manager`) y verificación de que su suite
  no usa mis fixtures.
- `tests/backend/test_codex_link_endpoints.py` 1-130 - patrón establecido (T04) para el singleton
  compartido: parche por test de `_home_root`/`_bin_path` del `codex_manager` (usado en mi
  fixture autouse; el mío añade `_spawn_wait_seconds`/`_max_processes` que mi test de capacidad
  necesita).
- `tests/backend/conftest.py` - fixtures existentes (no usadas: suite autocontenida).
- `pytest.ini` + `scripts/run_pytest.py` - runner y `asyncio_default_test_loop_scope = function`.
- `main.py` 55-70 y `test_api.py` 1-10 - diagnóstico del fallo de la suite completa: confirmar
  que `main.py:63` importa `backend.codex_app_server` y `test_api.py:6` importa `main` a nivel de
  módulo (causa de los 17 fallos de T02 en la suite completa).

Pack gaps:
- None (todo el Context Pack existía y coincidía; el fake de T02 cubre los escenarios
  requeridos; `scripted_turn`/`scripted_error`/`slow_turn`/`usage_limit` suficientes).

## Decisions
- **Mensaje del turno en formato estructurado** `{"role": "user", "content":
  [{"type": "input_text", "text": ...}]}`: el fake no pincha params y los nombres son per-docs
  (riesgo nombrado del brief, gate T10). El `system` del primer turno viaja en `system` (param
  documentado); en los reintentos NO se reenvía (el thread del app-server conserva el estado —
  cache-friendly, patrón `_DeepSeekExplainerConversation`). `model` (override por turno) y
  `temperature` se envían en todos los turnos.
- **Seam de parseo `_parse_turn_json`**: envoltorio de una línea sobre `json.loads` que permite
  a los tests del reintento conversacional fallar/reescribir el fixture en el instante exacto del
  fallo de parseo (el fake de T02 re-lee `FAKE_CODEX_TURN_OUTPUT_FILE` en cada `turn/start`, así
  el segundo turno sirve JSON válido). Sin tocar el fixture (read-only).
- **Mapeo de errores por tokens, sin inventar códigos**: `UsageLimitExceeded`/`RateLimitExceeded`
  exactos → cuota; tokens de auth/refresh en el nombre normalizado → vínculo; resto → re-lanzado
  como `CodexRequestError` de T02. Alternativa evaluada (lista exacta de códigos de auth) se
  descartó porque el README del app-server no fija un vocabulario cerrado y el token-match cubre
  los códigos que el server emita sin inventar ninguno.
- **`CodexUsage` con conteos del turno FINAL** en los reintentos (no agregados): los conteos solo
  se rellenan "desde campos de usage reportados por el turno" y `quota_requests=1` es congelado
  por llamada; agregar entre intentos habría inventado un agregado que el contrato no define.
- **`total_token_count` nunca se calcula** (cero si el turno no lo reporta), a diferencia del
  `DeepSeekUsage` que suma: el contrato congelado exige "ceros si el turno no los reporta; nunca
  valores inventados".
- **Fixture autouse `_codex_singleton_env`** (parche por test de `_bin_path`/`_home_root`/
  `_spawn_wait_seconds`/`_max_processes` del singleton): el `main.py` de T04 importa
  `codex_app_server` en la colección y congela el singleton con env por defecto; el parche hace
  mi suite determinista en cualquier orden (patrón de `test_codex_link_endpoints.py`). Sin esto,
  mi test de capacidad esperaría ~120 s (spawn_wait 60) y el spawn usaría `/usr/local/bin/codex`.
- **Reuso de constantes de `explainer_openrouter`** (`OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES=2`,
  `OPENROUTER_EXPLAINER_TEMPERATURE=0.7`) como pide el Context Pack: la política de reintentos de
  payload del repo es una sola.

## Concerns / Follow-ups
- **Suite backend completa NO verde por interferencia de T04** (17 fallos en
  `tests/backend/test_codex_app_server.py`, T02 read-only): `main.py` (working tree, T04) importa
  `backend.codex_app_server` y `test_api.py` importa `main` en colección → el singleton
  `codex_manager` queda creado con env por defecto antes de que el módulo de tests de T02 asigne
  su env. Verificado: el fichero pasa solo (20/20); mi suite pasa en la suite completa (13/13).
  NO es de mi alcance (do-not-touch `main.py`; test de T02 no editable): el orquestador debe
  decidir — p. ej. T04/T02 alinean el patrón de env (parche por test como
  `test_codex_link_endpoints.py`) o T02 remediará su módulo. Riesgo de colisión con el gate live
  T10 si no se alinea.
- Nombres de parámetros JSON-RPC (`message` estructurado, `system`, `temperature` en
  `turn/start`) y campos de usage son per-docs (riesgo nombrado del brief); el fake no los pincha
  y el gate T10 valida contra el binario real. El parseo acepta snake_case y camelCase para
  amortiguar el drift.
- `test_codex_link_endpoints.py` (T04) ya existe en el working tree y pasa en la suite completa;
  no lo toqué.

## Remediation History
None for the initial implementation.

### Round 1 - changed-contract FR-01/FR-01b (streaming lifecycle + request params v2; brief ENMENDADO)
- Finding IDs: `FR-01` (turn lifecycle streaming, verificado en source `08e482e2` /
  `rust-v0.147.0-alpha.9`: la response de `turn/start` solo acepta el turno; el texto, el
  usage y los errores llegan por notificaciones; no existe `turn/end`), `FR-01b` (request
  params v2: `thread/start` → `{model, developerInstructions?}`, `turn/start` →
  `{threadId, input:[{type:"text",text}], model}`; no existen `message`, `system`,
  `temperature`, `threadID`, `response_format`).
- Status: addressed.
- Delta:
  - **`backend/codex_client.py` reimplementado al ciclo de turno STREAMING v2**:
    - `call_codex_chat` (firma pública congelada) ahora hace `acquire` → `thread/start`
      (con `developerInstructions` = system prompt; thread por llamada) → por intento
      `turn/start` en el MISMO thread y espera la notificación `turn/completed`
      correlacionada por `(user_id, turnId)` con `asyncio.wait_for(timeout)` →
      `CodexTimeoutError`. De la response de `turn/start` se toma SOLO el `turnId`
      (`result.turn.id` o `result.id`, defensivo); nunca texto ni usage.
    - Texto final SOLO de `item/completed` con `item.type=="agentMessage"` y `item.text`
      (último gana); usage SOLO de `thread/tokenUsage/updated` (último correlacionado
      gana; se prefiere `tokenUsage.last`, fallback `total`) con el mapeo congelado
      `inputTokens→prompt`, `cacheWriteInputTokens→tool_use`, `outputTokens→candidates`,
      `reasoningOutputTokens→thoughts`, `totalTokens→total` (parse defensivo, ceros si
      falta cualquier campo; bool/negativo/no numérico → 0). `turn/started`,
      `item/started`, `item/agentMessage/delta` NO se registran (ignoradas en v1).
    - Fallos de turno: `turn/completed` `status=="failed"` → mapeo desde `turn.error`
      (preferido) o la notificación `error` registrada: `codexErrorInfo` case-insensitive
      `usageLimitExceeded` → `CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)`,
      `unauthorized` → `CodexAuthError(CODEX_AUTH_MESSAGE)`, cualquier otro (o ausente) →
      `CodexError(CODEX_TURN_FAILED_MESSAGE)` (constante NUEVA aditiva; los mensajes UX
      existentes no cambian). Status distinto de `completed`/`failed` → fallo genérico
      (defensivo). Errores de aceptación en la response (`scripted_error`,
      `TurnOutputReadError`) se mapean como hasta ahora por `code` (sin cambios).
    - Reintento conversacional preservado: JSON inválido del texto final → nuevo
      `turn/start` en el MISMO thread con turno correctivo corto (sin reenviar la fuente
      ni el system prompt), máx. `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`; agotado →
      `CodexError` con mensaje de JSON (no un subtipo mapeado). El usage devuelto es el
      del intento exitoso.
    - Concurrencia estanca por `(user_id, turnId)`: handlers registrados UNA vez a nivel
      de módulo (guard idempotente) SOLO para `turn/completed`, `item/completed`,
      `thread/tokenUsage/updated` y `error`, en el singleton real del app-server (no en
      el alias del módulo que los tests envuelven). Registro de esperas propio
      (`_TURN_WAITS`) sin fugas (pop en `finally` de cada intento).
    - **Buzón de notificaciones (`_INBOX`)** — hallazgo de la ronda: el reader del
      app-server puede despachar los handlers ANTES de que la corrutina del cliente
      reanude tras la response de `turn/start` (la resolución de la response da dos
      saltos de cola — future → waiter → task — y los `create_task` de los handlers se
      cuelan delante; reproducido con trazado: `item/completed ctx=False` antes del
      registro). El cliente registra su contexto al reanudar y reproduce el buzón de su
      turno antes de esperar `turn/completed`; las notificaciones posteriores van por la
      vía directa. Sin este mecanismo, `item/completed` se perdía de forma FLAKY
      (texto final vacío). Verificado 10/10 y 5/5 corridas estables.
    - `temperature` y `response_format` siguen en la firma congelada pero NO se envían:
      `TurnStartParams` v2 no los acepta; `json_object` solo configura el parseo local.
  - **`tests/backend/fixtures_codex/` reescritos**: todos los `turn_*.json` pasan a ser
    TEXTO PLANO UTF-8 con el texto final (sin wrapper `role/content/usage`), mismos
    nombres (los consumen T05/T06/T07). Ficheros de usage compañeros NUEVOS
    `turn_*.usage.json` con el shape real (`{total, last, modelContextWindow}` y
    breakdown de 6 campos enteros) para los fixtures con aserciones de conteos
    (`turn_valid_json`, `turn_text`, `turn_explainer_full`, `turn_classifier`,
    `turn_recorrido_valid`, `turn_resources_valid`, `turn_review_valid`,
    `turn_formatter_markdown`, `turn_partial_usage`).
  - **`tests/backend/test_codex_client.py` reescrito**: 21 tests sobre el wire-format
    STREAMING: turno feliz (shapes v2 verificados campo a campo; la response de
    `turn/start` no contiene texto ni usage — verificado grabando los results reales),
    usage completo/ausente/parcial (preferencia `last`, ceros en ausentes), fallback a
    `total`, modo texto, reintento correctivo con la convención `<FILE>.2` del fake
    (mismo thread, sin fuente ni system, usage del intento exitoso), agotamiento de
    reintentos, `usage_limit` → `CodexRateLimitError`, mapper unitario (`unauthorized`
    → auth, desconocido/ausente → `CODEX_TURN_FAILED_MESSAGE`, status inesperado →
    genérico), `scripted_error` (aceptación: `UsageLimitExceeded` → rate limit,
    `AuthRefreshFailed` → auth, `BadTurn` → `CodexRequestError`), `stalled_turn` +
    timeout → `CodexTimeoutError`, timeout RPC (`slow_turn`), spawn sin hueco →
    `CodexBusyError`, y **concurrencia estanca**: dos `call_codex_chat` simultáneas del
    MISMO usuario con `<FILE>.1`/`<FILE>.2` y usage `.1`/`.2` → cada llamada devuelve
    exactamente su texto y su usage sin cruces.
  - **`tests/backend/test_codex_agents_core.py` / `test_codex_agents_family.py`**:
    ediciones de consecuencia del cambio de wire-format: helpers de fixtures al texto
    plano (`_turn_payload` lee el texto directo), `_params_message_text` lee
    `input[0].text` (v2), `FAKE_CODEX_TOKEN_USAGE_FILE` fijado a los ficheros de usage
    compañeros en los tests que asertan conteos (conteos alineados al mapeo congelado),
    y las aserciones de params de request v1 (temperatura en turn/start, system en
    turn/start) sustituidas por las v2 (`temperature` NO se envía; el system prompt
    viaja en `thread/start.developerInstructions`). NOTA de alcance: el brief enmendado
    autorizaba "solo usage" en estos ficheros, pero las aserciones de params v1 estaban
    en los tests que fallaban y son consecuencia directa de FR-01b (criterio "sin
    campos v1 en el código"); no se tocó ninguna otra aserción ni agente de producción.
  - NO se tocó: `backend/codex_app_server.py`, `tests/backend/fake_codex_app_server.py`
    (read-only), `backend/agents/**`, `main.py`, frontend, `test_codex_pipeline.py` y
    `test_codex_app_server.py` (pasaron sin edición).
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q`
    antes de implementar → `5 failed, 8 passed` (los tests del ciclo streaming
    fallaban con el cliente síncrono viejo: texto vacío de la response `{turn:{...}}`).
  - GREEN: mismo comando tras la reimplementación → `21 passed, 1 warning`; repetido
    10 veces sin flakiness (3.0-3.1s). La suite combinada
    `test_codex_client + test_codex_agents_core + test_codex_agents_family +
    test_codex_pipeline` → `69 passed` ×5 corridas.
  - `tests/backend/test_codex_agents_core.py tests/backend/test_codex_agents_family.py`
    → `23 passed`.
  - `tests/backend/test_codex_pipeline.py` → `25 passed`.
  - Suite backend completa: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
    → `577 passed, 3 skipped, 10 warnings` (dos corridas: 35.83s y 33.82s). Los 17
    fallos de interferencia de T04 documentados en la ronda 0 ya no existen.
  - `py_compile` de `backend/codex_client.py` y los 3 ficheros de tests → OK.
- Concerns:
  - `_extract_thread_id` conserva fallbacks defensivos de lectura (`threadId`/`threadID`
    top-level) sobre la response de `thread/start`; el cliente NUNCA los envía (verificado
    por test). Es lectura defensiva, no wire.
  - La variante `codexErrorInfo` real puede tener valores distintos de
    `usageLimitExceeded`/`unauthorized` (p. ej. `sessionBudgetExceeded`,
    `serverOverloaded`): caen en `CODEX_TURN_FAILED_MESSAGE` en v1 (riesgo nombrado del
    brief; ajuste solo con evidencia live, gate T10).
  - El turno correctivo es un `turn/start` nuevo en el mismo thread: si el app-server
    real no admite otro turno con uno en curso, se vería solo en el gate live T10.
