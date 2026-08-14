# Task T02: CodexAppServerManager — subproceso por tenant, JSONL, aislamiento y ciclo de vida (ENMENDADO — FR-01)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Crear `backend/codex_app_server.py`: el gestor de procesos `codex app-server --stdio` por
usuario con restauración/snapshot cifrado de `auth.json`, transporte JSONL concurrente, límites
de memoria y evicción; más el fixture `tests/backend/fake_codex_app_server.py` que **emula el
ciclo de turno STREAMING real del app-server 0.147.0** (verificado en source, commit `08e482e2`
/ `rust-v0.147.0-alpha.9`, receta §"Turn lifecycle verification (reconciliación FR-01)") para
verificar todo sin credenciales reales.

## Acceptance Criteria

### Manager (sin cambios de API — decisión FR-01)
- `codex_manager = CodexAppServerManager()` (singleton de módulo) con las firmas congeladas:
  `async acquire(user_id) -> CodexAppServer`, `async evict(user_id) -> None`,
  `async shutdown() -> None`, `add_notification_handler(method, handler)` y contador
  `active_count`. **Decisión FR-01: NO se añade API nueva al manager.** La correlación de
  notificaciones por `turnId` la hace el cliente (T03) con futures propios sobre
  `add_notification_handler(method, handler)` donde `handler(user_id, params) ->
  Awaitable[None]`; el manager solo debe despachar cada notificación con `user_id` y `params`
  intactos, en orden de llegada por proceso, sin bloquear el reader-task.
- `acquire` valida `user_id` con `re.fullmatch(r"[0-9a-fA-F-]{36}", ...)` (rechazo de no-UUID),
  crea `CODEX_HOME=/tmp/codex/<user_id>` con modo **0700**, restaura `auth.json` desde
  `get_user_provider_connection(user_id)["encrypted_credentials"]` (descifrado con
  `decrypt_user_api_key`, escritura atómica temp+rename) cuando `status="linked"`, y lanza
  `asyncio.create_subprocess_exec(<CODEX_BIN_PATH|env>, "app-server", "--stdio", ...)` con
  `CODEX_HOME` en el env. Un proceso vivo se devuelve sin re-spawn.
- Transporte JSONL: requests `{"jsonrpc":"2.0","id":N,"method","params"}`; una reader-task por
  proceso despacha respuestas por `id` a futures y notificaciones (sin `id`) a los handlers
  registrados (`handler(user_id, params)`). `CodexAppServer.request(method, params=None,
  timeout=CODEX_REQUEST_TIMEOUT_SECONDS)` espera su future con timeout; un error object del
  server lanza `CodexRequestError` con `.code/.message/.data`.
- Límites: semáforo global `CODEX_MAX_PROCESSES=3` con espera `CODEX_SPAWN_WAIT_SECONDS=60` y
  evicción LRU de procesos inactivos antes de lanzar `CodexSpawnError`; semáforo por proceso de
  `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`; `CODEX_IDLE_TTL_SECONDS=600` con loop de evicción
  (task asíncrona iniciada en el primer acquire).
- `evict`/`shutdown`: terminan el proceso (SIGTERM → SIGKILL tras grace), re-sincronizan
  `auth.json` cifrado a `user_provider_connections` si `status="linked"` (leer el fichero →
  `encrypt_user_api_key` → `upsert_user_provider_connection(..., status="linked")`), borran
  `CODEX_HOME` y liberan los semáforos. `shutdown` cierra todos los procesos; es idempotente y
  nunca lanza excepción.
- stderr del subproceso → `<CODEX_HOME>/app-server.stderr.log` (truncado por spawn), nunca a los
  logs de la app; nada de `auth.json`, `encrypted_credentials` o stderr crudo se loguea
  (previews con truncado, patrón `user_id[:8]`).

### Fake app-server — wire-format STREAMING (autoridad de tests, read-only para el resto)
- `tests/backend/fake_codex_app_server.py`: script Python ejecutable que lee JSONL de stdin y
  escribe JSONL en stdout; responde con id-correlación. Escenarios base por env
  `FAKE_CODEX_SCENARIO`: `echo`, `login_completes` (emite notificación
  `account/login/completed` tras N s), `login_pending`, `logout_ok`, `account_read_plan`,
  `invalid_json`, `slow_turn`, `scripted_turn`, `usage_limit`, `stalled_turn` y
  `scripted_error`. Este fixture es la autoridad del wire-format de tests: las tareas
  siguientes solo lo consumen (read-only).
- **`scripted_turn` — secuencia streaming completa** (shapes exactos verificados en la receta
  §Turn lifecycle verification; el fake NO añade campos inventados):
  - `thread/start` → `{"result": {"thread": {"id": "thread_<n>"}}}` (contador `<n>` por
    proceso, desde 1).
  - `turn/start` → response inmediata `{"result": {"turn": {"id": "turn_<n>",
    "status": "inProgress", "items": []}}}` — **sin texto ni usage en la response**.
  - A continuación, en este orden exacto, notificaciones (todas con `threadId` y `turnId`):
    1. `turn/started` → `{"threadId": T, "turn": {"id": "turn_<n>", "status": "inProgress"}}`
    2. `item/started` → `{"item": {"type": "agentMessage", "id": "item_<n>"}, "threadId": T,
       "turnId": "turn_<n>", "startedAtMs": <int>}`
    3. `item/agentMessage/delta` (al menos 1; el fake emite 1 delta con el texto completo) →
       `{"threadId": T, "turnId": "turn_<n>", "itemId": "item_<n>", "delta": "<texto>"}`
    4. `item/completed` (autoritativo) → `{"item": {"type": "agentMessage", "id": "item_<n>",
       "text": "<texto final>"}, "threadId": T, "turnId": "turn_<n>", "completedAtMs": <int>}`
       — `<texto final>` es el contenido del fichero de salida del turno, **leído como texto
       plano UTF-8 (sin `json.load`)**.
    5. `thread/tokenUsage/updated` (SOLO si hay fichero de usage para el turno; ver abajo) →
       `{"threadId": T, "turnId": "turn_<n>", "tokenUsage": <contenido del fichero>}` donde
       `<contenido>` debe tener el shape real: `{"total": <breakdown>, "last": <breakdown>,
       "modelContextWindow": <int>}` y cada breakdown
       `{"inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens",
       "reasoningOutputTokens", "totalTokens"}` (enteros).
    6. `turn/completed` → `{"threadId": T, "turn": {"id": "turn_<n>", "status": "completed",
       "items": []}}`
  - Fuente del texto: el turno N lee `<FAKE_CODEX_TURN_OUTPUT_FILE>.<N>` si existe; si no,
    `FAKE_CODEX_TURN_OUTPUT_FILE`. Fichero ausente/ilegible → error object `TurnOutputReadError`
    en la **response** de `turn/start` (error de aceptación, no notificación).
  - Fuente del usage: el turno N lee `<FAKE_CODEX_TOKEN_USAGE_FILE>.<N>` si existe; si no,
    `FAKE_CODEX_TOKEN_USAGE_FILE`. Si no hay fichero de usage → **no se emite**
    `thread/tokenUsage/updated` (el cliente defensivo debe devolver conteos a cero).
  - `threadId` usado en las notificaciones: `params.get("threadId") or
    params.get("threadID")` del request de `turn/start`; si ninguno existe, el fake usa
    `thread_<n>` del `thread/start` previo (defensivo).
- **`usage_limit` — cuota descubierta DURANTE la ejecución** (no confundir con error de
  aceptación):
  - `turn/start` → response `{"result": {"turn": {"id": "turn_<n>", "status": "inProgress",
    "items": []}}}` y después, en orden:
    1. notificación `error` → `{"error": {"message": "Usage limit exceeded for this ChatGPT
       plan", "codexErrorInfo": "usageLimitExceeded", "additionalDetails": null},
       "willRetry": false, "threadId": T, "turnId": "turn_<n>"}`
    2. `turn/completed` fallido → `{"threadId": T, "turn": {"id": "turn_<n>",
       "status": "failed", "error": {"message": "Usage limit exceeded for this ChatGPT plan",
       "codexErrorInfo": "usageLimitExceeded", "additionalDetails": null}, "items": []}}`
  - `thread/start` → response de thread normal (`{"thread": {"id": "thread_<n>"}}`).
  - Cualquier OTRO método (p. ej. `account/logout`) → error object `UsageLimitExceeded` en la
    response, como antes (conserva el test de T04 "logout fallido no bloquea el borrado").
- **`stalled_turn`** (nuevo): `thread/start` → response de thread normal; `turn/start` →
  response `{turn:{id:"turn_<n>",status:"inProgress",items:[]}}` y **ninguna** notificación
  posterior (el cliente debe caer en timeout esperando `turn/completed`).
- **`scripted_error`** (sin cambios): error object en la **response** de cualquier request, con
  `code` desde `FAKE_CODEX_ERROR_CODE`. Modela el error de aceptación de `turn/start`
  (JSON-RPC error), que SÍ puede venir en la response y es distinto de la cuota en ejecución.
- `slow_turn` (sin cambios): responde tras `FAKE_CODEX_SLOW_DELAY_SECONDS` (timeout de RPC).
  `invalid_json` (sin cambios): línea JSON inválida tolerada por el reader.

### Tests
- `tests/backend/test_codex_app_server.py` (usando `CODEX_BIN_PATH` apuntando al fake) cubre:
  spawn/0700/restauración, request+respuesta y request concurrente por id, error object →
  `CodexRequestError`, timeout de RPC (`slow_turn`), semáforo 5, capacidad 3 →
  `CodexSpawnError`, evicción LRU, shutdown con snapshot cifrado, user_id inválido rechazado,
  notificación despachada con `user_id` + `params` (`login_completes`).
- **Nuevos/actualizados al flujo streaming:**
  - `scripted_turn`: la response de `turn/start` es `{turn:{id,status:"inProgress",items:[]}}`
    (sin `text`/`usage` en la response); la secuencia de notificaciones observada por handlers
    registrados es, en orden: `turn/started`, `item/started`, `item/agentMessage/delta` (con
    `itemId`), `item/completed` (item `agentMessage` cuyo `text` == contenido del fichero de
    salida, sin parseo), `turn/completed` con `status:"completed"`; el `turnId`/`threadId` de
    todas las notificaciones correlaciona con el turno.
  - Usage: con `FAKE_CODEX_TOKEN_USAGE_FILE` fijado, se emite `thread/tokenUsage/updated` con
    el shape real (`total`/`last`/`modelContextWindow` y breakdown con los 6 campos
    verificados); sin él, NO se emite.
  - Convención por turno: dos `turn/start` secuenciales leen `<FILE>.1` y `<FILE>.2` cuando
    existen.
  - `usage_limit`: turno → notificación `error` con `codexErrorInfo:"usageLimitExceeded"` +
    `turn/completed` con `status:"failed"` y `turn.error.codexErrorInfo:"usageLimitExceeded"`;
    y guard de regresión: un request no-turn (p. ej. `account/logout`) sigue devolviendo error
    object `UsageLimitExceeded`.
  - `stalled_turn`: la response de `turn/start` llega y no se emite ninguna notificación.
  - `scripted_turn` sin fichero de salida → error object `TurnOutputReadError` en la response.
- Señal roja antes de implementar: no existen los módulos. Señal verde: todos los escenarios del
  fake pasan con `CODEX_BIN_PATH` apuntando al fixture (sin binario real ni red).

## Scope
Touch:
- `backend/codex_app_server.py` (nuevo)
- `tests/backend/fake_codex_app_server.py` (nuevo)
- `tests/backend/test_codex_app_server.py` (nuevo)

Do not touch:
- `main.py` (el wiring de lifespan lo hace T04), `supabase_data.py`, `backend/crypto.py`,
  `backend/codex_client.py` (T03), agentes, frontend, Dockerfile/koyeb.yaml/DEPLOY.md,
  `tests/backend/fixtures_codex/` (T03 reescribe los fixtures)

## Constraints
- Solo los invariantes de `global-constraints.md` → "Tenant isolation and process lifecycle",
  "Container runtime" y "Fake app-server (fixture de test)". Los nombres de clase/método y los
  límites por env son contrato.
- El fake NO añade campos inventados a las notificaciones: los shapes son exactamente los
  verificados en `integration-codex-appserver.md` §Turn lifecycle verification.
- Import de `supabase_data` y `crypto` de forma perezosa dentro de funciones si hace falta
  evitar ciclos de import; nunca importar `main.py`.
- `evict`/`shutdown` nunca fallan por Supabase caído: el snapshot se intenta best-effort y se
  loguea el fallo sin datos sensibles.

## Interfaces
Consumes:
- T01: `get_user_provider_connection`, `upsert_user_provider_connection` (persistencia del
  snapshot), `decrypt_user_api_key`/`encrypt_user_api_key` (`backend/crypto.py:115-159`).
- Receta: `plans/chatgpt-codex-auth/integration-codex-appserver.md` (§Chosen Approach, §Setup,
  §Gotchas 1-2: aislamiento por CODEX_HOME, stdio sin TTY, un proceso por tenant) y §"Turn
  lifecycle verification (reconciliación FR-01)" para los shapes del streaming.

Produces (contrato congelado para T03/T04/T07):
- `CodexAppServerError`, `CodexSpawnError`, `CodexRequestError(code, message, data)`
- `CodexAppServer.home_dir` + `async CodexAppServer.request(method, params=None, timeout=...) -> Any`
- `CodexAppServerManager.acquire/evict/shutdown/add_notification_handler` + `active_count`
  (SIN API nueva para esperar notificaciones: el cliente correlaciona con sus futures).
- `codex_manager` singleton del módulo
- Fixture `fake_codex_app_server.py` (CLI JSONL, escenario por env, streaming verificado)

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/chatgpt-codex-auth/integration-codex-appserver.md` | Turn lifecycle verification (reconciliación FR-01); stdio/device-code/aislamiento/env | completo | Única fuente externa autorizada; shapes streaming |
| `plans/chatgpt-codex-auth/global-constraints.md` | Tenant isolation; Container runtime; Fake app-server | secciones | Límites y semántica fijos |
| `backend/supabase_data.py` | `get/set_user_api_key` | 918-967 | Forma de acceso a datos + cifrado |
| `backend/crypto.py` | `encrypt/decrypt_user_api_key` | 115-159 | Uso correcto para auth.json |
| `main.py` | `lifespan` (lugar donde T04 colgará shutdown) | 288-306 | Saber qué no tocar |
| `backend/sse_manager.py` | (referencia) singletons de módulo | 27-45 | Estilo de singleton en el repo |

## Existing Patterns To Reuse
- Singleton de módulo + lock como `sse_manager`; `asyncio.create_subprocess_exec` con reader
  task (sin hilos bloqueantes); `mask_api_key`/truncados de `user_id` para logs.
- Patrón de errores tipados de `backend/deepseek_client.py` (341-460) para la jerarquía de
  excepciones.
- El fake actual emite notificaciones secuenciales tras responder (patrón
  `login_completes`); se extiende a la secuencia de turno.

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_app_server.py`
- Señal verde: todos los escenarios del fake pasan con `CODEX_BIN_PATH` apuntando al fixture
  (sin binario real ni red).

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: ciclo de vida de credenciales, aislamiento multi-tenant, concurrencia y autoridad del
wire-format de tests; un fallo aquí es fuga o corrupción de estado de vínculo o un fake que
no pincha el protocolo real.

## Named Risks
- El wire-format STREAMING está verificado en source (`08e482e2` / `rust-v0.147.0-alpha.9`);
  el gate live (T10) es la única confirmación contra el binario real.
- `asyncio.create_subprocess_exec` + semáforos deben convivir con el loop de uvicorn; no usar
  `run_in_executor` para lecturas de pipe.
- La correlación `(user_id, turnId)` es responsabilidad de T03; el manager solo garantiza
  despacho en orden por proceso con `user_id`/`params` intactos.

## Report Path
`plans/chatgpt-codex-auth/task-T02-report.md`
