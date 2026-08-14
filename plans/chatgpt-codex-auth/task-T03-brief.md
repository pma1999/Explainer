# Task T03: Cliente Codex tipado y routing de modelos (ENMENDADO — FR-01)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Crear `backend/codex_client.py` (cliente de chat sobre el app-server con errores tipados,
`CodexUsage` y reintentos conversacionales) y `backend/codex_model_routing.py` (modelo único
`gpt-5.6-luna`), el contrato que todos los agentes Codex consumirán. El cliente implementa el
**ciclo de turno STREAMING** verificado en source (commit `08e482e2` /
`rust-v0.147.0-alpha.9`): la response de `turn/start` solo acepta el turno; el texto final, el
usage y los errores llegan por NOTIFICACIONES, correlacionadas por `turnId`.

## Acceptance Criteria
- `backend/codex_model_routing.py` expone exactamente `CODEX_MODEL = "gpt-5.6-luna"`,
  `CODEX_MODEL_AUXILIARY = CODEX_MODEL`, `CODEX_EXPLAINER_MODELS = frozenset({CODEX_MODEL})`.
- `backend/codex_client.py` define la jerarquía congelada `CodexError` (base, con `.message`),
  `CodexRateLimitError`, `CodexAuthError`, `CodexBusyError`, `CodexTimeoutError` y re-usa
  `CodexSpawnError`/`CodexRequestError` de T02. Los mensajes UX congelados
  (`CODEX_RATE_LIMIT_MESSAGE`, `CODEX_AUTH_MESSAGE`, `CODEX_BUSY_MESSAGE`,
  `CODEX_TIMEOUT_MESSAGE`) NO cambian. Se añade UNA constante nueva (aditiva, no modifica las
  existentes): `CODEX_TURN_FAILED_MESSAGE = "Codex no pudo completar el turno. Espera un poco e
  inténtalo de nuevo."` para fallos de turno sin mapeo conocido.
- `CodexUsage` con los atributos congelados en `global-constraints.md`
  (`prompt_token_count`, `tool_use_prompt_token_count`, `candidates_token_count`,
  `thoughts_token_count`, `total_token_count`, `cost_usd=0.0`, `cost_source="chatgpt_quota"`,
  `quota_requests=1`). Los conteos se rellenan SOLO desde la notificación
  `thread/tokenUsage/updated` correlacionada con el turno (parse defensivo, ceros si falta
  cualquier campo; nunca valores inventados), con el mapeo congelado:
  `prompt_token_count ← inputTokens`, `tool_use_prompt_token_count ← cacheWriteInputTokens`,
  `candidates_token_count ← outputTokens`, `thoughts_token_count ← reasoningOutputTokens`,
  `total_token_count ← totalTokens`. Se prefiere `tokenUsage.last`; si no existe, se usa
  `tokenUsage.total`. Un valor no numérico/bool/negativo cuenta como 0.
- `async def call_codex_chat(*, user_id, messages, system_prompt, model=CODEX_MODEL,
  response_format="json_object", temperature=..., timeout=CODEX_REQUEST_TIMEOUT_SECONDS) ->
  tuple[Any, CodexUsage]` — **firma pública congelada, sin cambios**. Flujo por llamada:
  1. `await codex_manager.acquire(user_id)` (`CodexSpawnError` → `CodexBusyError`).
  2. `thread/start` → extraer `thread.id` (defensivo).
  3. Por intento (turno inicial + turnos correctivos, máx.
     `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES` correctivos): `turn/start` en el MISMO thread
     (correctivo = texto corto sin reenviar la fuente ni el system prompt, patrón
     `_DeepSeekExplainerConversation`) → de la response tomar SOLO el `turnId` (defensivo:
     `result["turn"]["id"]` o `result["id"]`); la response NO lleva texto ni usage. Registrar
     **sincrónicamente (sin `await` intermedio)** el contexto de espera del intento y esperar
     la notificación `turn/completed` con `(user_id, turnId)` coincidente, con el `timeout` de
     `call_codex_chat` aplicado a la espera (`asyncio.wait_for`) → agotado →
     `CodexTimeoutError`.
  4. Mientras se espera, las notificaciones correlacionadas (mismas `user_id`+`turnId`; el
     cliente las recibe vía `add_notification_handler` de T02 y un registro propio de
     esperas/futures por `(user_id, turnId)`; una notificación de turno desconocido se ignora
     sin error) rellenan el contexto del intento:
     - `item/completed` con `item.type == "agentMessage"` → texto final desde `item.text`
       (si llegan varios, gana el último; el texto es autoritativo SOLO aquí).
     - `thread/tokenUsage/updated` → usage según el mapeo congelado (si llegan varios, gana el
       último correlacionado).
     - `error` → se registra el error de la notificación.
     - `turn/started`, `item/started`, `item/agentMessage/delta` → **ignoradas en v1** (solo
       sirven para UI/progreso; el texto final NUNCA se reconstruye acumulando deltas). El
       cliente registra handlers SOLO para `turn/completed`, `item/completed`,
       `thread/tokenUsage/updated` y `error`.
  5. Al llegar `turn/completed` correlacionado: `status == "completed"` → éxito (devolver
     `texto_final` y usage del intento; con `response_format="json_object"` ejecutar
     `json.loads`; si falla → reintento conversacional). `status == "failed"` → lanzar el error
     mapeado desde `turn.error` (preferido) o desde la notificación `error` registrada:
     `codexErrorInfo` comparado case-insensitive: `usageLimitExceeded` →
     `CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)`; `unauthorized` →
     `CodexAuthError(CODEX_AUTH_MESSAGE)`; cualquier otro (o `turn.error` ausente) →
     `CodexError(CODEX_TURN_FAILED_MESSAGE)`. Un `status` distinto de
     `completed`/`failed` en `turn/completed` se trata como fallo genérico (defensivo).
  6. Un error object JSON-RPC en la **response** de `turn/start`/`thread/start` (error de
     aceptación) se mapea como hasta ahora: por `code` (`UsageLimitExceeded`/`RateLimitExceeded`
     → `CodexRateLimitError`; subcadenas auth/refresh → `CodexAuthError`; el resto se re-lanza
     como `CodexRequestError`). NO confundir con la cuota en ejecución (notificación).
  7. En `finally` de cada intento se retira la entrada del registro de esperas (sin fugas).
- **NO existe `turn/end` ni `turn/poll`** en ningún punto del cliente (ni requests ni esperas);
  la terminación se detecta solo por la notificación `turn/completed`. El cliente NUNCA lee
  texto o usage de la response de `turn/start`.
- **Concurrencia estanca:** varias llamadas simultáneas del mismo usuario en el mismo proceso
  (hasta `CODEX_PER_PROCESS_MAX_CONCURRENCY`) se correlacionan por `(user_id, turnId)` — cada
  `turn/start` produce un `turnId` distinto y cada llamada tiene su propio contexto de espera;
  no puede haber cruces de texto, usage ni errores entre llamadas. Los handlers de notificación
  se registran UNA vez a nivel de módulo (guard idempotente contra doble registro).
- Sin credenciales en logs: se loguean solo `user_id[:8]`, `model`, longitudes y previews
  truncados de prompts; nunca `auth.json` ni el contenido completo de mensajes fuente.
- **Fixtures** (`tests/backend/fixtures_codex/`, propiedad de esta tarea): los ficheros
  `turn_*.json` pasan a contener SOLO el texto final (UTF-8 plano, sin wrapper
  `role/content/usage`); los valores de usage se mueven a ficheros de usage separados con el
  shape real (`{"total": {...}, "last": {...}, "modelContextWindow": N}`, breakdown con
  `inputTokens`/`cachedInputTokens`/`cacheWriteInputTokens`/`outputTokens`/
  `reasoningOutputTokens`/`totalTokens`). Los fixtures de texto existentes se conservan con los
  mismos nombres (los consumen T05/T06/T07).
- **Ediciones de consecuencia (acotadas):** actualizar SOLO la parte de usage de
  `tests/backend/test_codex_agents_core.py` y `tests/backend/test_codex_agents_family.py` para
  el nuevo mecanismo: fijar `FAKE_CODEX_TOKEN_USAGE_FILE` apuntando a los ficheros de usage
  compañeros cuando el test aserta conteos, y alinear los conteos esperados al mapeo congelado
  (p. ej. `prompt_token_count` ← `inputTokens`). No se toca ningún agente de producción ni
  ninguna otra aserción.

## Scope
Touch:
- `backend/codex_client.py` (nuevo)
- `backend/codex_model_routing.py` (nuevo)
- `tests/backend/test_codex_client.py` (nuevo) + fixtures bajo `tests/backend/fixtures_codex/`
  (reescritura a texto final + ficheros de usage nuevos; nunca editar
  `fake_codex_app_server.py`)
- `tests/backend/test_codex_agents_core.py` y `tests/backend/test_codex_agents_family.py`:
  SOLO el bloque de setup/aserciones de usage (consecuencia del cambio de wire-format).

Do not touch:
- `backend/codex_app_server.py`, `backend/agents/**` (producción), `supabase_data.py`,
  `main.py`, frontend, despliegue, `tests/backend/fake_codex_app_server.py`

## Constraints
- Solo los invariantes de `global-constraints.md` → "Codex client and errors" y "Fake app-server
  (fixture de test)". Firmas exactas en `plan.md` → Cross-task interfaces.
- No usar `requests`/httpx aquí: todo el transporte pasa por `CodexAppServer.request` y por los
  handlers de notificación de T02 (`add_notification_handler`). NO se añade API nueva al
  manager; la correlación es con futures propios del cliente.
- El cliente es **async** y se espera directo; nunca se envuelve en `asyncio.to_thread` (la
  asincronía es decisión de diseño del plan, no negociable en esta tarea).
- El `timeout` de `call_codex_chat` aplica tanto a cada request RPC como a la espera de
  `turn/completed` de cada intento.

## Interfaces
Consumes:
- T02: `codex_manager`, `CodexAppServer.request`, `CodexAppServerManager.add_notification_handler`
  (`handler(user_id, params) -> Awaitable[None]`), `CodexSpawnError`, `CodexRequestError`,
  `CodexTimeoutError` (de T02), `CODEX_REQUEST_TIMEOUT_SECONDS`.
- Fake de T02 (read-only): escenarios `scripted_turn` (streaming con
  `FAKE_CODEX_TURN_OUTPUT_FILE` + `FAKE_CODEX_TOKEN_USAGE_FILE`), `usage_limit` (notificación
  `error` + `turn/completed` failed), `stalled_turn` (sin `turn/completed`), `scripted_error`
  (error object en response), `slow_turn`.
- `backend/agents/explainer_openrouter.py`: `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`,
  `OPENROUTER_EXPLAINER_TEMPERATURE` (constantes de reintento/temperatura del repo).

Produces:
- `call_codex_chat(...) -> tuple[Any, CodexUsage]` (firma congelada)
- `CodexUsage`, `CodexError` + subtipos, `CODEX_TURN_FAILED_MESSAGE` (nueva, aditiva)
- `CODEX_MODEL`, `CODEX_MODEL_AUXILIARY`, `CODEX_EXPLAINER_MODELS`

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/chatgpt-codex-auth/integration-codex-appserver.md` | Turn lifecycle verification (reconciliación FR-01) | sección completa | Shapes autoritativos del streaming (turn/completed, item/completed, tokenUsage, error) |
| `plans/chatgpt-codex-auth/global-constraints.md` | Codex client and errors | sección | Contratos congelados + mapeo de usage/errores |
| `backend/codex_app_server.py` | `add_notification_handler`, `_dispatch_notification`, `CodexRequestError`, `CodexTimeoutError` | 322-330, 389-460, 856-879 | API exacta de notificaciones y errores de T02 |
| `backend/deepseek_client.py` | `call_deepseek_chat`, retries 429/5xx, `DeepSeekUsage` | 341-460, 528-560, 755-784 | Closest analog de cliente + usage |
| `backend/agents/explainer_deepseek.py` | `_DeepSeekExplainerConversation` | 280-379 | Reintento conversacional a replicar |
| `backend/agents/explainer_openrouter.py` | constantes retries/temperature | grep `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES` | Reuso de constantes |

## Existing Patterns To Reuse
- `deepseek_client.py`: forma de errores tipados, parseo defensivo de usage, timeouts y retries.
- `_DeepSeekExplainerConversation`: append de turno correctivo sin reenviar el prefijo
  (cache-friendly).
- Futures + registro por clave como los del transporte JSONL de T02 (mismo estilo, en el
  cliente).

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_client.py`
- Cobertura exigida (todos sin red ni credenciales; `scripted_turn` con
  `FAKE_CODEX_TURN_OUTPUT_FILE`/`FAKE_CODEX_TOKEN_USAGE_FILE`, `usage_limit`, `stalled_turn`,
  `scripted_error`, `slow_turn`):
  - Turno feliz JSON válido: data parseada == fixture; usage con los conteos del fichero de
    usage (mapeo congelado verificado campo a campo: `inputTokens`→prompt, `outputTokens`→
    candidates, `reasoningOutputTokens`→thoughts, `cacheWriteInputTokens`→tool_use,
    `totalTokens`→total); la response de `turn/start` no contiene texto ni usage.
  - Sin notificación de usage → todos los conteos a 0 (`cost_usd=0.0`,
    `cost_source="chatgpt_quota"`, `quota_requests=1`).
  - Usage parcial (solo algunos campos del breakdown) → ceros en los ausentes.
  - Modo `response_format="text"` → devuelve el texto de `item/completed` tal cual.
  - JSON inválido → reintento correctivo (segundo `turn/start` en el mismo thread; el fake lee
    `<FILE>.2`) → éxito; agotamiento → `CodexError` (mensaje de JSON, no un subtipo mapeado);
    el turno correctivo no reenvía la fuente ni `system`; el usage devuelto es el del intento
    exitoso.
  - `usage_limit` → notificación `error` + `turn/completed` failed →
    `CodexRateLimitError(CODEX_RATE_LIMIT_MESSAGE)`.
  - Mapper unitario: `codexErrorInfo == "unauthorized"` → `CodexAuthError`; desconocido →
    `CodexError(CODEX_TURN_FAILED_MESSAGE)`; `turn/completed` con status inesperado → genérico.
  - `scripted_error` (response): `UsageLimitExceeded` → `CodexRateLimitError`;
    `AuthRefreshFailed` → `CodexAuthError`; código desconocido → `CodexRequestError`
    (aceptación, sin cambios).
  - `stalled_turn` + timeout pequeño → `CodexTimeoutError`.
  - Spawn sin hueco → `CodexBusyError`.
  - **Concurrencia estanca:** dos `call_codex_chat` simultáneas del MISMO usuario, con
    `<FILE>.1`/`<FILE>.2` y usage `.1`/`.2` distintos → cada llamada devuelve exactamente su
    texto y su usage (sin cruces), y ambas resuelven dentro de su timeout.
- Señal roja antes de implementar: no existen los módulos. Señal verde: los tests nuevos pasan
  y los tests de agentes (core/family/pipeline) y link-endpoints siguen verdes con los fixtures
  y escenarios actualizados.

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: contrato de cliente y errores consumido por los 7+ agentes Codex y el pipeline; la
correlación por notificaciones y la concurrencia son el corazón del cambio FR-01; un fallo
aquí re-secuenciaría las olas 3-4.

## Named Risks
- **Request-params (FUERA del alcance de FR-01):** la verificación de source muestra que
  `TurnStartParams` v2 real usa `input: [{type:"text",text}]`/`threadId` (camelCase) y no los
  campos `message`/`system`/`temperature`/`threadID` que el cliente emite hoy. FR-01 enmienda
  SOLO el ciclo de vida (response + notificaciones); el shape de parámetros del request queda
  pineado por el fake tal como está y pendiente de validación en el live gate (T10). NO se
  cambia aquí; se registra en el decision ledger si el live gate lo confirma como divergencia.
- Variantes de `codexErrorInfo` distintas de `usageLimitExceeded`/`unauthorized` (p. ej.
  `sessionBudgetExceeded`, `serverOverloaded`) caen en el mensaje genérico en v1; ajustarlas
  exige evidencia live.
- El turno correctivo es un `turn/start` nuevo en el mismo thread: si el app-server no admite
  otro turno con uno en curso, el error se vería solo en el gate live.

## Report Path
`plans/chatgpt-codex-auth/task-T03-report.md`
