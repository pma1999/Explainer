# Task T02 Report

## Status
DONE

## Outcome
`backend/codex_app_server.py` implementa el gestor de procesos `codex app-server --stdio` por
tenant con el contrato congelado del brief: singleton de módulo `codex_manager` con
`acquire/evict/shutdown/add_notification_handler` y `active_count`; `CodexAppServer.home_dir` +
`request(method, params=None, timeout=CODEX_REQUEST_TIMEOUT_SECONDS)`; errores tipados
`CodexAppServerError` / `CodexSpawnError` / `CodexRequestError(code, message, data)` (+
`CodexTimeoutError`, aditivo para la jerarquía de T07 de `global-constraints.md` §Codex client).

Comportamiento verificado por tests (sin binario real ni red, `CODEX_BIN_PATH` apuntando al
fixture):
- `acquire` valida `user_id` con `re.fullmatch(r"[0-9a-fA-F-]{36}", ...)`, crea
  `CODEX_HOME = <CODEX_HOME_ROOT>/<user_id>` (default `/tmp/codex`) con modo **0700**, restaura
  `auth.json` desde `get_user_provider_connection(user_id)["encrypted_credentials"]`
  (descifrado con `decrypt_user_api_key`, escritura atómica temp+rename, fichero 0600) cuando
  `status="linked"`, y lanza `asyncio.create_subprocess_exec(<bin>, "app-server", "--stdio", ...)`
  con `CODEX_HOME` en el env. Un proceso vivo se devuelve sin re-spawn (también bajo acquires
  concurrentes del mismo tenant: lock por usuario).
- Transporte JSONL: requests `{"jsonrpc":"2.0","id":N,"method":...,"params":{...}}`; una
  reader-task por proceso resuelve respuestas por `id` (futures) y despacha notificaciones (sin
  `id`) a los handlers registrados `handler(user_id, params)`. Error object del server →
  `CodexRequestError` con `.code/.message/.data`; timeout → `CodexTimeoutError`; líneas JSON
  inválidas se toleran (log con preview truncado).
- Límites: semáforo global `CODEX_MAX_PROCESSES=3` con espera `CODEX_SPAWN_WAIT_SECONDS` y
  evicción LRU de un proceso inactivo antes de `CodexSpawnError`; semáforo por proceso de
  `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`; `CODEX_IDLE_TTL_SECONDS=600` con loop de evicción
  iniciado en el primer acquire.
- `evict`/`shutdown`: SIGTERM → SIGKILL tras grace (`CODEX_TERMINATE_GRACE_SECONDS=5`),
  re-sincronizan `auth.json` cifrado a `user_provider_connections` si `status="linked"` (leer
  fichero → `encrypt_user_api_key` → `upsert_user_provider_connection(status="linked", ...)`,
  preservando `plan_type` de la fila), borran `CODEX_HOME` y liberan los semáforos. `shutdown` es
  idempotente y nunca lanza excepción; el snapshot es best-effort (verificado en vivo: con
  Supabase inalcanzable el fallo se loguea sin datos sensibles y la evacuación continúa).
- stderr del subproceso → `<CODEX_HOME>/app-server.stderr.log` truncado por spawn; nunca a los
  logs de la app. Ningún log incluye `auth.json`, `encrypted_credentials` ni stderr crudo
  (previews truncados + `user_id[:8]`).

`tests/backend/fake_codex_app_server.py`: fixture ejecutable (shebang) que lee JSONL de stdin y
escribe JSONL en stdout con correlación por `id`; los 10 escenarios del brief (`echo`,
`login_completes` con notificación `account/login/completed` tras `FAKE_CODEX_LOGIN_DELAY_SECONDS`,
`login_pending`, `logout_ok`, `account_read_plan`, `usage_limit`, `invalid_json`, `slow_turn`,
`scripted_turn`, `scripted_error`) verificados. **Desde la remediación FR-01 (brief enmendado) el
wire-format es STREAMING verificado en source** (receta §Turn lifecycle verification, commit
`08e482e2` / `rust-v0.147.0-alpha.9`): `scripted_turn` responde a `turn/start` con
`{turn:{id,status:"inProgress",items:[]}}` sin texto ni usage y emite la secuencia
`turn/started` → `item/started` → `item/agentMessage/delta` → `item/completed` (texto final del
fichero de salida, plano) → opcional `thread/tokenUsage/updated` (shape real
`total/last/modelContextWindow`) → `turn/completed`; `usage_limit` es cuota descubierta en
ejecución (notificación `error` con `codexErrorInfo:"usageLimitExceeded"` + `turn/completed`
failed); `stalled_turn` acepta el turno sin notificaciones; convención por turno `<FILE>.<N>`.
`scripted_error`, `slow_turn` e `invalid_json` sin cambios. Ver Remediation History Round 3.

`tests/backend/test_codex_app_server.py`: 25 tests, todos los casos listados en el brief
(incluida la clase `TestStreamingTurn` con la secuencia streaming completa, usage con/sin
fichero, convención por turno, `usage_limit` y `stalled_turn`).

## Acceptance Criteria
- `codex_manager = CodexAppServerManager()` (singleton de módulo) con firmas congeladas
  `async acquire/evict/shutdown`, `add_notification_handler(method, handler)` y `active_count` ->
  pass (imports del singleton en la suite; `active_count` observado en spawn/evicción/shutdown).
- `acquire`: validación UUID estricta, `CODEX_HOME` 0700, restauración de `auth.json` cuando
  `status="linked"` (temp+rename), spawn `app-server --stdio` con `CODEX_HOME` en env, proceso
  vivo reutilizado sin re-spawn -> pass (`test_invalid_user_id_rejected`,
  `test_spawn_creates_home_0700_and_restores_auth_json`, `test_no_restore_when_not_linked`,
  `test_live_process_reused_without_respawn`; modo 0700 y 0600 verificados en POSIX).
- Transporte JSONL por id + notificaciones a handlers + `CodexRequestError(.code/.message/.data)`
  + timeout del future -> pass (`test_request_and_response`,
  `test_concurrent_requests_resolved_by_id` (10 peticiones concurrentes sin mezcla),
  `test_notification_dispatched_to_handlers`, `test_error_object_raises_codex_request_error`,
  `test_scripted_error_code_from_env`, `test_request_timeout_raises_codex_timeout_error`,
  `test_invalid_json_line_tolerated`, `test_scripted_turn_output_file`).
- Límites: semáforo global 3 + espera + evicción LRU antes de `CodexSpawnError`; semáforo por
  proceso 5; TTL 600 con loop iniciado en el primer acquire -> pass
  (`test_global_capacity_raises_spawn_error_when_all_busy`,
  `test_lru_eviction_frees_capacity_before_spawn_error`,
  `test_per_process_concurrency_semaphore_blocks_sixth`, `test_idle_ttl_eviction_loop` con
  instancia TTL=0.3).
- `evict`/`shutdown`: SIGTERM→SIGKILL, snapshot cifrado si `linked`, borrado de `CODEX_HOME`,
  liberación de semáforos; shutdown idempotente y sin excepciones -> pass
  (`test_evict_snapshots_encrypted_auth_json_and_cleans_home` verifica round-trip
  decrypt(encrypted_credentials)==contenido nuevo del fichero y `not home.exists()`;
  `test_shutdown_idempotent_and_never_raises` con shutdown doble y vacío).
- stderr → fichero truncado por spawn, nunca a logs de la app; nada sensible logueado -> pass
  (`test_spawn_creates_home_0700_and_restores_auth_json` (banner en el fichero),
  `test_stderr_log_truncated_per_spawn` (crash + respawn → exactamente 1 banner); por
  construcción el stderr del subproceso es un file object, nunca PIPE hacia la app).
- Fixture con los 10 escenarios -> pass (todos ejercitados; wire-format id-correlacionado).
- Tests nuevos con `CODEX_BIN_PATH` al fake sin binario real ni red -> pass (25/25; suite backend
  completa en verde salvo los 19 tests de T03 que dependen del wire-format antiguo — ver
  Remediation History Round 3).
- Scope: solo los 3 archivos del brief -> pass (git status: `backend/codex_app_server.py`,
  `tests/backend/fake_codex_app_server.py`, `tests/backend/test_codex_app_server.py`; no se tocó
  `main.py`, `supabase_data.py`, `crypto.py`, agentes, frontend, Dockerfile/koyeb.yaml/DEPLOY.md).

## Files Changed
- `backend/codex_app_server.py` - created; gestor de procesos por tenant (manager + server +
  errores tipados + singleton `codex_manager`). Sin cambios en la ronda FR-01 (el despacho de
  notificaciones ya cumplía el contrato enmendado; verificado, no tocado).
- `tests/backend/fake_codex_app_server.py` - created; fixture JSONL autoridad del wire-format
  (10 escenarios por env), read-only para el resto de tareas. Ronda FR-01: reescrito al
  wire-format STREAMING verificado en source (brief enmendado).
- `tests/backend/test_codex_app_server.py` - created; 25 tests unitarios/integración sobre el
  fixture (loop de sesión, sin red ni binario real). Ronda FR-01: `TestStreamingTurn` (6 tests)
  sustituye al test de `scripted_turn` síncrono.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/codex_app_server.py` | `CodexAppServerError(Exception)` | Nuevo: error base |
| `backend/codex_app_server.py` | `CodexSpawnError(CodexAppServerError)` | Nuevo: capacidad o lanzamiento fallido |
| `backend/codex_app_server.py` | `CodexTimeoutError(CodexAppServerError)` | Nuevo (aditivo): timeout de request; lo consume la jerarquía de T07 |
| `backend/codex_app_server.py` | `CodexRequestError(code, message, data)` | Nuevo: error object JSON-RPC del server |
| `backend/codex_app_server.py` | `CodexAppServer.home_dir` / `request(method, params=None, timeout=CODEX_REQUEST_TIMEOUT_SECONDS)` | Nuevo: proceso por tenant + transporte JSONL |
| `backend/codex_app_server.py` | `CodexAppServerManager.acquire/evict/shutdown/add_notification_handler/active_count` | Nuevo: ciclo de vida, límites, evicción, snapshot |
| `backend/codex_app_server.py` | `codex_manager` | Nuevo: singleton de módulo |
| `backend/codex_app_server.py` | Constantes env `CODEX_BIN_PATH`, `CODEX_HOME_ROOT`, `CODEX_MAX_PROCESSES=3`, `CODEX_SPAWN_WAIT_SECONDS=60`, `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`, `CODEX_IDLE_TTL_SECONDS=600`, `CODEX_REQUEST_TIMEOUT_SECONDS=900`, `CODEX_TERMINATE_GRACE_SECONDS=5` | Nuevas: límites por env (defaults = contrato) |
| `tests/backend/fake_codex_app_server.py` | CLI JSONL con escenarios por `FAKE_CODEX_SCENARIO` (+ `FAKE_CODEX_LOGIN_DELAY_SECONDS`, `FAKE_CODEX_SLOW_DELAY_SECONDS`, `FAKE_CODEX_TURN_OUTPUT_FILE`, `FAKE_CODEX_TOKEN_USAGE_FILE`, `FAKE_CODEX_ERROR_CODE`) | Nuevo: fixture autoridad del wire-format. R3 (FR-01): `scripted_turn` STREAMING (response inProgress sin texto/usage + secuencia de 6 notificaciones con shapes del source), `usage_limit` como cuota en ejecución (error notification + turn/completed failed), `stalled_turn` nuevo; convención por turno `<FILE>.<N>`; `_ScenarioHandler` con contadores por proceso |
| `tests/backend/test_codex_app_server.py` | 25 tests (19 + `TestStreamingTurn` ×6) | Nuevo: suite del contrato T02. R3 (FR-01): `TestStreamingTurn` verifica la secuencia streaming (orden, correlación, shapes), usage con/sin fichero, convención por turno, `usage_limit` y `stalled_turn` |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
  Result: pass — `25 passed, 1 warning` (warning: `APP_ENCRYPTION_KEY` no configurada, fallback
  temporal del módulo crypto; esperado en tests). Ejecutado 5 veces tras la ronda FR-01
  (6.06–6.23s), sin flakiness.
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
  Result: `550 passed, 3 skipped, 19 failed` — los 19 fallos son tests de T03 que dependen del
  wire-format antiguo del fake (client/agents/pipeline; T03 los arregla en su ronda); cero fallos
  en T02/env_lazy/link_endpoints. Ver Remediation History Round 3.
- Command: `.venv-win/Scripts/python.exe -m py_compile backend/codex_app_server.py tests/backend/fake_codex_app_server.py tests/backend/test_codex_app_server.py`
  Result: pass — `COMPILE_OK`.
- Smoke del fake standalone (Linux, `python3 tests/backend/fake_codex_app_server.py app-server --stdio`):
  `echo`, `scripted_turn` (secuencia streaming exacta del brief), convención `<FILE>.1`/`<FILE>.2`,
  `usage_limit` (error notification + turn/completed failed + error object en no-turn) y
  `stalled_turn` (solo response) con correlación por `id` correcta.
- Smoke del manager sobre el fixture (`.venv-win`): `login_pending`, `logout_ok`,
  `account_read_plan`, `scripted_error` (código por defecto `InternalError`) OK; con Supabase sin
  configurar, el snapshot best-effort falla y se loguea sin secretos y la evacuación continúa
  (`Snapshot de auth.json falló ... (best-effort): RuntimeError`) — comportamiento buscado.
- No ejecutados: tests marcados `integration` (requieren binario real/credenciales — gate T10).

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
  → `ModuleNotFoundError: No module named 'backend.codex_app_server'` (1 error en colección) —
  fallo por el motivo esperado: el módulo del contrato aún no existía.
- GREEN: mismo comando tras implementar fake + manager → `19 passed, 1 warning`. Un fallo
  intermedio por race de arranque (el banner de stderr del fake aún no escrito al leer el fichero)
  corregido con espera de polling en el test; suite completa en verde en 4 ejecuciones.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T02-brief.md` (completo)
- `plans/chatgpt-codex-auth/global-constraints.md` §Tenant isolation and process lifecycle y
  §Container runtime (además §Persistence, §Fake app-server, §Codex client and errors para
  firmas/contratos)
- `plans/chatgpt-codex-auth/context-map.md` (orientación)
- `plans/chatgpt-codex-auth/integration-codex-appserver.md` (completo: stdio/unix, device-code,
  aislamiento por CODEX_HOME, env)
- `backend/supabase_data.py` 1000-1108 (`get/upsert/delete_user_provider_connection`, contrato
  T01) y 1-60 (imports, `_client`)
- `backend/crypto.py` 91-159 (`derive_user_key`, `encrypt/decrypt_user_api_key`)
- `main.py` 288-306 (lifespan: dónde T04 colgará `codex_manager.shutdown()`; no tocado)
- `backend/sse_manager.py` 27-99 (estilo de singleton de módulo)
- `backend/deepseek_client.py` 1-100 y 341-464 (patrón de jerarquía de errores tipados)
- `backend/logging_config.py` 310-319 (`get_logger`)

Extra reads:
- `tests/backend/conftest.py` - fixtures existentes (no usadas: suite autocontenida).
- `pytest.ini` + `scripts/run_pytest.py` - runner y `asyncio_default_test_loop_scope = function`.
- `tests/backend/test_user_provider_connections.py` - patrón de mock de Supabase de T01
  (`patch("backend.supabase_data._client")` → en T02 se parchean las funciones directamente).
- Código fuente de `pytest_asyncio` instalado (v1.4.0) - diagnosticar el error de fixture async
  en strict mode: exige `@pytest_asyncio.fixture` (ver Decisions).
- Prototipos empíricos en `test_output/` y scripts temporales borrados: subprocess con
  `stderr=file` y `terminate/wait` en Windows (Proactor); spawn directo de un `.py` falla con
  `WinError 193` (base de la decisión del shim de intérprete); `loop_scope="session"` del mark.

Pack gaps:
- None (todo el Context Pack del brief existía y coincidía; el contrato T01 verificado en el
  working tree, `supabase_data.py` modificado por T01 con las firmas del brief).

## Decisions
- **`CODEX_HOME_ROOT` por env (default `/tmp/codex`)**: el brief fija `CODEX_HOME=/tmp/codex/<user_id>`;
  la raíz configurable permite tests herméticos sin tocar `/tmp` real. El default reproduce
  exactamente el contrato.
- **`CODEX_TERMINATE_GRACE_SECONDS=5` por env**: grace del SIGTERM → SIGKILL, no fijado en el
  brief pero necesario para "SIGTERM → SIGKILL tras grace"; en Windows `terminate()` ya es
  TerminateProcess (el grace es irrelevante, los tests lo confirman).
- **Shim de intérprete para binarios `.py`**: `_build_argv` antepone `sys.executable` cuando
  `CODEX_BIN_PATH` termina en `.py`. Razón verificada empíricamente: el runner de tests del repo
  es un venv de Windows, donde un script Python no es ejecutable directamente
  (`WinError 193` reproducido). En producción la ruta es un binario nativo
  (`/usr/local/bin/codex`) y el branch nunca se toma; también hace irrelevante el exec bit en CI
  Linux. Documentado en el código y en este reporte (desviación mínima del literal
  `create_subprocess_exec(<bin>, "app-server", "--stdio", ...)`, mismo proceso y argumentos).
- **`CodexTimeoutError` definido en este módulo (aditivo)**: `global-constraints.md` §Codex
  client and errors lista `CodexTimeoutError` en la jerarquía tipada que consumirá T07; el
  timeout de `request()` es el único origen posible de ese error, así que vive aquí. No cambia
  ningún nombre del contrato congelado (que solo lista los tres errores; añadir una clase no los
  rompe).
- **Lock por usuario + evicción LRU sin lock del objetivo**: `acquire` serializa por tenant
  (evita doble spawn bajo `MAX_CONCURRENT_PARTS`), pero la evicción LRU desde el camino de
  acquire hace pop+cleanup sin tomar el lock del tenant objetivo: dos acquires concurrentes en
  timeout de capacidad que se evictaran mutuamente formarían un ciclo de locks. El pop con
  verificación de identidad (`self._servers.get(uid) is candidate`) es atómico en el event loop
  (sin awaits entre verificación y pop), por lo que no puede evictar un server recién registrado.
  El `evict` público sí mantiene su lock por usuario (un solo lock, sin ciclos). **SUPERSEDED en
  la Round 1 de remediación (F01):** la atomicidad del pop no cubre el `await` posterior del
  cleanup, que dejaba abierta la carrera de doble ciclo de vida sobre el mismo CODEX_HOME;
  reemplazado por el lock de evicción por tenant descrito en Remediation History.
- **Limpieza a prueba de cancelación**: `acquire`/`_spawn`/`_terminate_and_cleanup` usan
  `except BaseException`/`finally` para que una cancelación de la tarea llamante (p.ej. shutdown
  con peticiones en vuelo) libere el slot global, mate el proceso, cancele la reader-task y
  borre el home — `asyncio.CancelledError` no deriva de `Exception` y habría dejado fugas.
- **Supabase/crypto importados de forma perezosa dentro de las funciones** (como permite el
  brief): evita dependencias de import y permite a los tests parchear
  `backend.supabase_data.get_user_provider_connection` / `upsert_user_provider_connection` con
  `monkeypatch`.
- **Snapshots best-effort**: `_snapshot_auth` y `_restore_auth_json` nunca rompen
  acquire/evict/shutdown (Supabase caído o blob corrupto → warning sin secretos y flujo
  continúa), cumpliendo "evict/shutdown nunca fallan por Supabase caído". El upsert del snapshot
  preserva `plan_type` de la fila leída (no lo pisa con `None`).
- **Fixture en loop de sesión**: el singleton de módulo posee primitivas asyncio ligadas al
  loop (semáforo/locks creados perezosamente), por lo que la suite corre entera con
  `@pytest.mark.asyncio(loop_scope="session")` (y `@pytest_asyncio.fixture(loop_scope="session")`
  en el cleanup autouse: pytest-asyncio 1.4 en strict mode exige el decorador `pytest_asyncio`
  para fixtures async). La fixture autouse llama `shutdown()` tras cada test, ejercitando la
  idempotencia en cada ejecución.
- **`active_count` cuenta solo procesos vivos** (un proceso muerto pendiente del finalizador de
  la reader-task no infla el contador).
- **`evict` con user_id inválido es no-op silencioso** (idempotencia del contrato DELETE).

## Concerns / Follow-ups
- **Actividad paralela observada**: durante esta sesión aparecieron modificados (no por mí)
  `Dockerfile`, `koyeb.yaml` y `DEPLOY.md` (mtimes 02:12–02:15, aditivos: instalación del binario
  codex pineado, etc.) — probablemente otra tarea del bundle en curso. No los toqué (el brief lo
  prohíbe); el orquestador debe coordinarlos con la revisión de T02.
- **Wire-format pineado por el fake**: la forma exacta de los mensajes del app-server real no
  está reproducida en la receta; el formato que emite este manager queda fijado por el fixture y
  solo el gate live (T10) podrá validarlo contra el binario. Los escenarios `login_completes` y
  `account_read_plan` usan shapes plausibles mínimos (`loginId`/`planType`) que T03 debe
  consumir tal cual (read-only) y ajustar en T10 si difieren.
- **Memoria del contenedor (R1 del context-map)**: con hasta 3 procesos `codex` + uvicorn en una
  instancia nano de Koyeb, la memoria es un riesgo conocido del bundle; no es accionable desde
  T02 (límite de procesos ya es el del contrato).
- **Timeout de `request` tras cancelación del future**: el future cancelado por
  `wait_for`/cancelled de la tarea se descarta con seguridad (pop + `future.done()` en la
  reader), verificado por los tests de timeout.

## Remediation History
None for the initial implementation.

### Round 1 - plans/chatgpt-codex-auth/task-T02-review.md
- Finding IDs: `F01` (blocking).
- Status: addressed.
- Delta:
  - **Nuevo mecanismo: lock de evicción por tenant** (`self._eviction_locks: dict[str, asyncio.Lock]`
    + helper `_eviction_lock(user_id)` en `backend/codex_app_server.py`). Invariante: es un lock
    **hoja** — quien lo sostiene no adquiere ningún otro lock (ni siquiera otro de evicción), por
    lo que no puede formarse un ciclo de locks entre acquires concurrentes (el AB-BA que motivó
    la decisión original de no tomar el lock del objetivo).
  - `_evict_lru_idle`: el candidato LRU se re-valida por identidad bajo el lock de evicción del
    tenant objetivo y el lock se mantiene durante TODO `_terminate_and_cleanup` (terminate +
    snapshot + borrado del home) — F01 cerrado.
  - `evict` público: ahora `user_lock` → `eviction_lock` del mismo tenant (verificación de
    identidad bajo el lock, para no re-evacuar un server que la LRU ya reclamó) → pop → cleanup
    bajo ambos locks. Con esto, shutdown (que delega en `evict` por usuario) queda bajo la misma
    serialización: un acquire concurrente del tenant en evacuación espera y las peticiones en
    vuelo mueren por diseño con su future resuelto como `server_closed`/`transport_closed`, sin
    intercalar restore/snapshot/borrado del home.
  - `acquire`: primero el slot global (`_wait_global_slot`, que puede evictar LRU a OTRO tenant
    tomando su lock de evicción sin anidar el propio), y después `async with
    self._eviction_lock(user_id)` alrededor del spawn completo (restauración + proceso). El
    `try/except BaseException` cubre también la espera del lock: una cancelación ahí libera el
    slot global (no se fuga capacidad). Tras el spawn, el registro del server ocurre fuera del
    lock de evicción; un LRU posterior que seleccionara el server recién creado fallaría la
    verificación de identidad (comportamiento LRU preexistente, sin carrera de ciclo de vida).
  - `_terminate_and_cleanup`: docstring que declara la precondición del lock de evicción (sus
    únicos llamadores son `evict` y `_evict_lru_idle`, ambos bajo el lock).
  - Comentarios obsoletos actualizados (`_wait_global_slot`, docstring de módulo, docstring de
    `acquire`).
  - Tests: +1 test `TestEvictionAcquireSerialization::test_lru_eviction_blocks_concurrent_acquire_until_cleanup_done`
    en `tests/backend/test_codex_app_server.py` (19 → 20). Intercala de forma determinista:
    hooks que compuertan `_snapshot_auth` (la evacuación LRU queda bloqueada a mitad del
    snapshot, con el server ya fuera del registro), lanza un `acquire` concurrente del mismo
    `user_id` y registra el orden de `snapshot_started/done`, `restore_began/done`,
    `home_cleaned`. Afirma que el restore del nuevo ciclo solo ocurre tras `snapshot_done` Y
    `home_cleaned` (nunca dos ciclos de vida sobre el mismo CODEX_HOME), y que el server final
    está vivo con el home presente.
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q -k TestEvictionAcquireSerialization`
    contra la implementación previa → `1 failed, 19 deselected` con `AssertionError: assert not
    True` en `assert not interleaved` (el acquire re-spawneó durante el snapshot compuertado,
    confirmando F01). El test añadido es el único cambio en ese momento.
  - GREEN: mismo comando tras la corrección → `1 passed, 19 deselected, 1 warning in 1.75s`
    (el acquire permanece bloqueado ~1.5 s hasta que termina la evacuación). Desaparece además
    el ruido de teardown `BaseSubprocessTransport.__del__ / Event loop is closed` que el estado
    huérfano del proceso re-spawneado dejaba en la corrida RED.
  - Regresión: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
    → `20 passed, 1 warning in 5.26s`; `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
    → `485 passed, 3 skipped in 19.31s` (484+1 previos); `py_compile` de ambos archivos → OK.
- Concerns: el caso "shutdown con peticiones en vuelo" se cubre por delegación (shutdown →
  `evict` → ambos locks durante el cleanup); la terminación de una petición en vuelo sigue
  siendo por diseño (el future falla con error tipado). La ventana `_servers` registrado fuera
  del lock de evicción en `acquire` es intencional y segura (análisis en Delta). Sin issues
  nuevos conocidos.

### Round 2 - plans/chatgpt-codex-auth/task-T02-remediation-env-lazy.md (cross-task, env lazy)
- Finding IDs: `RC-ENV-LAZY` (orquestador, cross-task T05/T06: lectura de env en el import).
- Status: addressed.
- Delta:
  - **`backend/codex_app_server.py`**: las env `CODEX_*` ya no se leen en el import. Los
    nombres públicos congelados (`CODEX_BIN_PATH`, `CODEX_HOME_ROOT`, `CODEX_MAX_PROCESSES=3`,
    `CODEX_SPAWN_WAIT_SECONDS=60`, `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`,
    `CODEX_IDLE_TTL_SECONDS=600`, `CODEX_REQUEST_TIMEOUT_SECONDS=900`,
    `CODEX_TERMINATE_GRACE_SECONDS=5`) pasan a ser los DEFAULTS del contrato (los tests los
    importan y comparan `== 3`/`== 5`; `codex_client.py` importa
    `CODEX_REQUEST_TIMEOUT_SECONDS` como default de `call_codex_chat`, que ningún test ejercita
    con el default), y los VALORES efectivos se resuelven en el momento de uso vía helpers
    nuevos `_env_*()` (`_env_bin_path`, `_env_home_root`, `_env_max_processes`,
    `_env_spawn_wait_seconds`, `_env_per_process_max_concurrency`, `_env_idle_ttl_seconds`,
    `_env_request_timeout_seconds`, `_env_terminate_grace_seconds`; sin caché: lectura barata y
    los tests no podrían invalidarla).
  - Los defaults del constructor de `CodexAppServerManager` pasan de las constantes (frozen en
    import) a `None` = "env en el momento de uso", con resolvers privados
    `_bin_path_value()`/`_home_root_value()`/`_max_processes_value()`/`_spawn_wait_seconds_value()`/
    `_per_process_max_concurrency_value()`/`_idle_ttl_seconds_value()`/
    `_terminate_grace_seconds_value()` que respetan el valor explícito del constructor SI lo hay
    (los fixtures de test_codex_client/agents/link_endpoints parchean `_bin_path`, `_home_root`,
    `_spawn_wait_seconds`, `_max_processes` por test y siguen ganando; `test_start_503` con
    `_bin_path="/nonexistent/codex-bin"` sigue fallando el spawn como espera). `_home_root_value`
    convierte a `Path` (los llamadores pasan `str` de `tempfile.mkdtemp`; el constructor original
    ya convertía).
  - Puntos de uso migrados: `_build_argv` (bin), `_spawn` (home root + concurrency por proceso),
    `_wait_global_slot` y mensaje de `acquire` (max procesos + spawn wait), `_terminate_process`
    (grace ×2), `_eviction_loop` (TTL leído por iteración), `CodexAppServer.__init__`
    (`per_process_max_concurrency`) y `CodexAppServer.request` (`timeout`). API pública congelada
    intacta: clases, errores, singleton, `acquire/evict/shutdown/add_notification_handler`,
    `active_count`, `home_dir`, `request(method, params, timeout)` (el default de `timeout` y
    `per_process_max_concurrency` ahora es `None` = env per-uso; ningún llamador pasa `None`
    explícito).
  - **`tests/backend/test_codex_env_lazy.py` (nuevo)**: test de regresión
    `test_env_read_at_use_time_not_at_import` — con el módulo YA importado (colección), borra
    todas las `CODEX_*`, setea `CODEX_BIN_PATH`/`CODEX_HOME_ROOT` DESPUÉS, y verifica que un
    spawn del singleton usa el fake y el home del env (lectura per-uso). Sin
    `importlib.reload`: recargar re-ejecuta el módulo y rompe la identidad de las clases de
    error para los módulos de test ya coleccionados (`pytest.raises` con la clase antigua no
    captura la nueva; reproducido con 5 fallos al usar reload — descartado).
  - **Estabilización del env compartido en `test_codex_env_lazy.py` (nivel de módulo)**: en la
    suite completa (orden alfabético), `test_codex_client.py` pisa `CODEX_HOME_ROOT` a nivel de
    módulo DESPUÉS de `test_codex_app_server.py` (los writes de módulo son permanentes en toda
    la corrida). Los tests de T02 dependen de SU env a nivel de módulo (no parchean el
    singleton por test), así que la lectura per-uso veía el home de otro módulo (3 fallos
    residuales: `test_spawn_creates_home_0700_and_restores_auth_json`,
    `test_stderr_log_truncated_per_spawn`, `test_evict_snapshots_encrypted_auth_json_and_cleans_home`).
    Este módulo (el último de la familia en colección) re-afirma `CODEX_HOME_ROOT` del módulo de
    T02 cuando está en la corrida (`if "test_codex_app_server" in sys.modules`); el resto de
    variables no se pisan (mismo fake en `CODEX_BIN_PATH`, valores idénticos en el resto).
    Alternativa evaluada y descartada: caché de la primera resolución (sigue viendo el env del
    último writer de la colección) y snapshot en el import (reproduce el bug original de 17
    fallos).
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_env_lazy.py -q`
    contra el código previo (env leído en import) → `1 failed` con
    `CodexSpawnError: No se pudo lanzar el proceso Codex: FileNotFoundError` (el spawn usó el
    binario por defecto `/usr/local/bin/codex` congelado en el import, no el fake seteado
    después).
  - GREEN: mismo comando tras el fix → `1 passed, 1 warning in 0.27s`.
  - Regresión T02: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
    → `20 passed, 1 warning in 5.22s` (sin cambios en el archivo).
  - Suite completa (criterio 1): `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
    → `535 passed, 3 skipped, 10 warnings` en 2 corridas (30.17s y 28.96s), 0 fallos.
  - Combo del orquestador: `test_api.py test_codex_client.py test_codex_link_endpoints.py test_codex_app_server.py`
    → `82 passed, 10 warnings`.
  - `py_compile` de `backend/codex_app_server.py` y `tests/backend/test_codex_env_lazy.py` → OK.
- Concerns:
  - La estabilización del env es un write a nivel de módulo en el test nuevo: depende del orden
    de colección alfabético (env_lazy después de client). Si el orden cambiara (renombres,
    xdist), habría que revisarlo. El combo `test_codex_client.py + test_codex_app_server.py`
    (alfabético, sin env_lazy) mantiene los 3 fallos de home: inherente a la lectura per-uso
    con writers de módulo fuera de scope; los criterios del brief (suite completa, T02 en
    solitario, combo del orquestador) quedan en verde.
  - `codex_client.py` (fuera de scope) sigue importando `CODEX_REQUEST_TIMEOUT_SECONDS` (ahora
    default estático 900.0) como default de `call_codex_chat`; ningún test ejercita ese default
    (todos pasan `timeout` explícito), verificado en la suite completa.

### Round 3 - changed-contract FR-01 (streaming fake; brief ENMENDADO)
- Finding IDs: `FR-01` (final review, changed-contract: el app-server real 0.147.0 es STREAMING;
  no existe `turn/end`; `turn/start` responde `{turn:{id,status:"inProgress",items:[]}}` sin texto
  ni usage y el resultado llega por notificaciones). El brief de T02 fue enmendado por el planner;
  esta ronda sigue el brief enmendado (no el original).
- Status: addressed.
- Delta:
  - **`tests/backend/fake_codex_app_server.py` reescrito al wire-format STREAMING** (única
    autoridad del wire-format en tests, read-only para el resto de tareas):
    - `scripted_turn` ahora emite la secuencia exacta del brief enmendado y de la receta
      `integration-codex-appserver.md` §Turn lifecycle verification (source `08e482e2` /
      `rust-v0.147.0-alpha.9`): `thread/start` → `{"result":{"thread":{"id":"thread_<n>"}}}`;
      `turn/start` → response inmediata `{"result":{"turn":{"id":"turn_<n>","status":"inProgress",
      "items":[]}}}` SIN texto ni usage; después, en orden: `turn/started`
      (`{threadId, turn:{id,status:"inProgress"}}` — sin campo `turnId`, shape verificado),
      `item/started` (item `agentMessage` + `startedAtMs` int), `item/agentMessage/delta` (1 delta
      con el texto completo, con `itemId`), `item/completed` (autoritativo: item `agentMessage`
      con `text` = contenido del fichero leído como TEXTO PLANO UTF-8, nunca `json.load`;
      `completedAtMs` int), opcionalmente `thread/tokenUsage/updated`, y `turn/completed`
      (`{threadId, turn:{id,status:"completed",items:[]}}` — sin `turnId`, shape verificado).
    - Convención por turno: el turno N lee `<FAKE_CODEX_TURN_OUTPUT_FILE>.<N>` si existe y si no
      el base (ídem `FAKE_CODEX_TOKEN_USAGE_FILE`); fichero de salida ausente/ilegible → error
      object `TurnOutputReadError` en la RESPONSE de `turn/start` (error de aceptación, no
      notificación); sin fichero de usage → NO se emite `thread/tokenUsage/updated`; el shape de
      `tokenUsage` es `{total, last, modelContextWindow}` con breakdowns de 6 campos enteros
      (`inputTokens`, `cachedInputTokens`, `cacheWriteInputTokens`, `outputTokens`,
      `reasoningOutputTokens`, `totalTokens`).
    - `threadId` de las notificaciones: `params.threadId` o `params.threadID` del request de
      `turn/start`; si ninguno existe, el del `thread/start` previo (defensivo).
    - `usage_limit` reescrito: cuota descubierta DURANTE la ejecución — `thread/start` responde
      normal; `turn/start` responde `inProgress` y después notificación `error` con
      `{error:{message,codexErrorInfo:"usageLimitExceeded",additionalDetails:null},
      willRetry:false,threadId,turnId}` + `turn/completed` `status:"failed"` con el mismo error en
      `turn.error`; cualquier OTRO método (p. ej. `account/logout`) → error object
      `UsageLimitExceeded` en la response (conserva el test de T04).
    - `stalled_turn` (nuevo): `thread/start` normal; `turn/start` responde `inProgress` y NO emite
      ninguna notificación posterior (el cliente cae en timeout esperando `turn/completed`).
    - `scripted_error`, `slow_turn`, `invalid_json`, `login_completes`, `login_pending`,
      `logout_ok`, `account_read_plan`, `echo` sin cambios de comportamiento.
    - Implementación: estado por proceso en `_ScenarioHandler` (contadores thread/turn/item desde
      1 + último thread id), `_per_turn_path` para la convención `<FILE>.<N>`, `_read_turn_output`
      (texto plano) y `_read_token_usage` (JSON) separadas.
  - **`tests/backend/test_codex_app_server.py`**: el antiguo `test_scripted_turn_output_file`
    (response síncrona con el JSON del fichero) se sustituye por la clase `TestStreamingTurn`
    (6 tests) + helper `_StreamingCollector` (registra un handler por método del ciclo en el
    singleton y recoge `(method, params)` en orden de llegada). Cubren: (a) secuencia completa
    con usage — response `turn/start` exacta `{turn:{id,status:"inProgress",items:[]}}`, orden de
    las 6 notificaciones, correlación `threadId` en todas y `turnId`/`turn.id` según el shape
    verificado (las notificaciones `turn/started` y `turn/completed` NO llevan `turnId`),
    `item/completed.item.text` == contenido del fichero sin parseo, shape real de `tokenUsage`
    con los 6 campos enteros por breakdown; (b) sin fichero de usage → NO se emite
    `thread/tokenUsage/updated`; (c) convención por turno con `<FILE>.1`/`<FILE>.2` (turn_1/
    item_1 y turn_2/item_2); (d) fichero de salida ausente → `CodexRequestError` con
    `code=="TurnOutputReadError"` en la response; (e) `usage_limit` → notificación `error` con
    `codexErrorInfo:"usageLimitExceeded"` + `turn/completed` `status:"failed"` con
    `turn.error.codexErrorInfo` + guard de regresión `account/logout` → error object
    `UsageLimitExceeded`; (f) `stalled_turn` → response `inProgress` y cero notificaciones.
    El resto de la suite (transport, límites, evicción, snapshot) sin cambios.
  - **`backend/codex_app_server.py` NO tocado** (el brief lo permite explícitamente): verificado
    que el manager ya soporta el flujo streaming — `_dispatch_notification` resuelve los handlers
    en el momento del despacho (registro previo al request funciona), despacha en orden de
    llegada por proceso (una sola reader-task; `asyncio.create_task` FIFO) con `user_id`/`params`
    intactos y sin bloquear el reader. Los tests de `TestStreamingTurn` lo prueban end-to-end:
    los handlers se registran ANTES del `turn/start` y reciben las notificaciones posteriores a
    la response.
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
    con el fake antiguo (solo los tests nuevos añadidos) → `5 failed, 20 passed`:
    `KeyError: 'thread'`/`KeyError: 'turn'` (el fake antiguo devolvía el JSON del fichero como
    result de `thread/start`/`turn/start`) y timeout esperando notificaciones que nunca llegaban.
    Un fallo intermedio adicional en `usage_limit` (collector sin handler del método `error`) y
    dos aserciones de correlación corregidas al shape verificado (`turn/started`/`turn/completed`
    no llevan `turnId`, correlacionan vía `turn.id`) — el fake siempre emitió los shapes exactos
    del brief; eran los tests los que sobre-asertaban.
  - GREEN: mismo comando con el fake reescrito → `25 passed, 1 warning in 6.23s`; repetido 4
    veces (6.23s / 6.11s / 6.12s / 6.06s) sin flakiness.
  - Regresión: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q` →
    `550 passed, 3 skipped, 19 failed, 10 warnings in 31.42s`. Los 19 fallos son TODOS de T03
    (dependencia del fake antiguo, ver abajo); cero fallos en T02/env_lazy/link_endpoints
    (T04). Comprobación causal: con el fake antiguo restaurado temporalmente, los 4 ficheros de
    T03 + link_endpoints + env_lazy pasan `76 passed` (los fallos los causa exclusivamente el
    cambio de wire-format, no otra cosa).
  - `py_compile` de `tests/backend/fake_codex_app_server.py` y
    `tests/backend/test_codex_app_server.py` → OK.
  - Smoke standalone del fake (Linux, `python3 fake_codex_app_server.py app-server --stdio`):
    `scripted_turn` emite la secuencia de 6 notificaciones exacta del brief con shapes del
    source; convención `<FILE>.1`/`<FILE>.2` verificada en vivo (turno 1 lee el base, turno 2 lee
    `<FILE>.2`); `usage_limit` emite `error` + `turn/completed` failed y `account/logout` →
    error object; `stalled_turn` emite solo la response.
- Concerns:
  - **Tests que quedan rojos por dependencia de T03 (19, todos del fake antiguo)**: T03 los
    arreglará en su ronda re-implementando `backend/codex_client.py` al flujo streaming
    (correlación por `turnId`, texto final de `item/completed`, usage de
    `thread/tokenUsage/updated`, cierre en `turn/completed`). Lista por fichero:
    - `tests/backend/test_codex_client.py` (6): `test_valid_json_turn_returns_parsed_data_and_usage`,
      `test_usage_zero_when_turn_reports_no_usage`, `test_usage_partial_reported_fields_filled`,
      `test_text_mode_returns_raw_text`, `test_invalid_json_retries_with_corrective_turn_then_succeeds`
      (y 1 más del mismo fichero en la suite completa).
    - `tests/backend/test_codex_agents_core.py` (8): los 6 de `TestExplainerCodex`
      (`test_run_explainer_codex_happy_path`, `test_run_explainer_codex_invalid_payload_retries_then_codex_error`,
      `test_run_subpart_explainer_codex_happy_path`, `test_run_explainer_codex_validated_retries_on_incomplete`,
      `test_run_subpart_explainer_codex_validated_happy_path`,
      `test_run_explainer_codex_validated_exhausted_raises_validation_error`) +
      `TestSegmentadorCodex::test_run_segmentador_codex_happy_path_and_conversation_retry` +
      `TestPageClassifierCodex::test_run_page_classifier_codex_happy_path`.
    - `tests/backend/test_codex_agents_family.py` (5): `TestRecorridoCodex` (2),
      `TestResourcesCodex::test_happy_path_without_web_search`,
      `TestReviewCodex::test_happy_path_returns_validated_payload`,
      `TestFormatterCodex::test_parallel_fields_and_usage_summary`.
    - `tests/backend/test_codex_pipeline.py` (1): `test_wired_codex_agents_run_against_fake_app_server`.
    Mecanismo de los fallos (verificado): `codex_client.py` (versión pre-T03) extrae el texto y
    el usage de la RESPONSE de `turn/start` (`_extract_final_text`/`_parse_usage`); con la
    response streaming `{turn:{...}}` devuelve `''` → `assert data == ...` falla y el modo JSON
    muere con `JSONDecodeError: Expecting value` en `_parse_turn_json`. Estos tests pasan con el
    fake antiguo (76 passed con el fake viejo restaurado). Además, `tests/backend/fixtures_codex/`
    (ficheros JSON con `content[0].text`/`usage`) los reescribe T03.
  - El shape de `turn/started` y `turn/completed` sin campo `turnId` (correlación vía `turn.id`)
    y la convención `<FILE>.<N>` son contrato del brief enmendado; T03 debe consumirlos tal cual.
  - `backend/codex_app_server.py` sin cambios en esta ronda (0 líneas tocadas): el despacho de
    notificaciones ya cumplía el contrato enmendado ("despacho con user_id/params intactos, en
    orden de llegada por proceso, sin bloquear el reader-task").

### Round 4 - live gate real: handshake `initialize` (remediación)
- Finding IDs: `LIVE-INIT` (orquestador, gate live contra `codex.exe` real 0.145.0; salida en
  `/tmp/opencode/codex_live.log`).
- Status: addressed.
- **Problema verificado con el binario real**: el gate live falló con
  `backend.codex_app_server.CodexRequestError: Not initialized` al enviar `account/login/start`
  justo tras `acquire` (trace del log: `tests\test_codex_live_login.py:133` →
  `codex_app_server.py:258` → `Future finished exception=CodexRequestError('Not initialized')`).
  El app-server real exige el handshake JSON-RPC al abrir la conexión — request `initialize` con
  `clientInfo` + notificación `initialized` — y rechaza CUALQUIER request anterior. El fake de
  tests no lo exigía, por eso la suite no lo detectó.
- **Handshake verificado empíricamente contra el binario real** (probe en
  `/tmp/opencode/handshake_probe.py`, binario `/mnt/c/Users/PcVIP/.codex/.sandbox-bin/codex.exe`,
  sin credenciales ni device code, solo transporte): `initialize` con exactamente el payload del
  fix → result `{"userAgent": "explainer/0.145.0-alpha.18 ...", "codexHome": ..., "platformFamily":
  "windows", "platformOs": "windows"}` (sin error object); la notificación `initialized` no
  recibe respuesta; `account/read` posterior ya NO devuelve "Not initialized". El shape del
  request coincide con el protocolo nativo del app-server (`InitializeParams { client_info:
  ClientInfo { name, title, version }, capabilities: Option }`, source de openai/codex:
  `codex-rs/app-server/tests/suite/v2/mcp_resource.rs`).
- Delta:
  - **`backend/codex_app_server.py`**:
    - Constante privada `_HANDSHAKE_TIMEOUT_SECONDS = 30.0`: timeout explícito y corto del
      handshake (los requests posteriores siguen usando `CODEX_REQUEST_TIMEOUT_SECONDS`).
    - `CodexAppServer._send_notification(method, params)`: método interno de escritura que
      reutiliza el canal de `request` (stdin del proceso + drain) SIN crear future ni esperar
      respuesta (el server no responde a notificaciones).
    - `_spawn`: tras crear `server._reader_task` y antes de `return server`, el handshake —
      `await server.request("initialize", {"clientInfo": {"name": "explainer", "title":
      "Explainer", "version": "0.1.0"}}, timeout=_HANDSHAKE_TIMEOUT_SECONDS)` y después
      `await server._send_notification("initialized", {})`. Si el binario no completa el
      handshake, `_spawn` falla y el `except BaseException` existente limpia proceso/reader/home
      (el error tipado `CodexRequestError`/`CodexTimeoutError` propaga por `acquire`, que libera
      el slot global). El lock por tenant de `acquire` cubre todo el spawn: ningún otro request
      puede intercalarse antes de la notificación `initialized`.
  - **`tests/backend/fake_codex_app_server.py`**: el fake responde a `initialize` con un result
    mínimo (`{}`) FUERA del escenario (el escenario modela métodos de aplicación, no el
    transporte: `slow_turn`/`scripted_error`/`invalid_json` no rompen el handshake; verificado en
    smoke con `slow_turn`) y NO responde a la notificación `initialized` (mensajes sin `id` se
    ignoran explícitamente con comentario, como el real). Nueva env `FAKE_CODEX_TRACE_FILE`
    (JSONL opcional de mensajes recibidos en orden de lectura) para verificar el orden del
    handshake.
  - **`tests/backend/test_codex_app_server.py`**: clase nueva `TestInitializeHandshake` (1 test):
    tras `acquire`, la traza del fake muestra que el PRIMER mensaje recibido es el request
    `initialize` (id 1, con `clientInfo` exacto), el segundo la notificación `initialized` (sin
    id), y solo después un request normal de la aplicación (`echo`) que funciona — los requests
    posteriores quedan cubiertos por los tests existentes, que ahora pasan todos con el
    handshake de por medio.
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q -k TestInitializeHandshake`
    contra la implementación previa (solo el test nuevo + trace del fake) → `1 failed, 25
    deselected`: `AssertionError: assert 1 >= 3` — la traza solo contenía
    `{"id": 1, "method": "echo", ...}`: el manager no enviaba `initialize`. Además, el fallo real
    del gate live (`CodexRequestError: Not initialized`, `/tmp/opencode/codex_live.log`) queda
    documentado como RED del binario real.
  - GREEN: mismo comando tras el fix → `26 passed, 1 warning in 7.22s`.
  - Regresión T02: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py -q`
    → `26 passed, 1 warning in 7.22s` (25 previos + 1 nuevo).
  - Suite backend completa (criterio 2): `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
    → `578 passed, 3 skipped, 10 warnings in 37.51s` (577 esperados + el test nuevo; 0 fallos;
    T03/T04/T05+ usan el fake y pasan con el handshake de por medio).
  - `py_compile` de los 3 ficheros → `COMPILE_OK`.
  - Smoke standalone del fake (Linux): `initialize` → `{"id": 1, "result": {}}` inmediato incluso
    con `FAKE_CODEX_SCENARIO=slow_turn`; `initialized` sin respuesta; `echo` posterior OK; traza
    en orden `initialize` → `initialized` → `echo`.
  - Probe contra el binario real: `HANDSHAKE_OK` (payload exacto del fix validado antes de
    implementar).
- Concerns: la verificación completa del flujo de login real (device code) queda para la
  re-ejecución del gate live por el orquestador (requiere acción humana). El result de
  `initialize` del binario real no se valida (el manager solo espera el response); un cambio de
  protocolo futuro en el binario (p. ej. exigir `protocolVersion`) fallaría el spawn de forma
  limpia y tipada, sin requests intermedios. `_run_codex_live.py` y `tests/test_codex_live_login.py`
  no se tocaron (fuera de scope).
