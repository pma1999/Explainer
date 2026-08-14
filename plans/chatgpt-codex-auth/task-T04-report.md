# Task T04 Report

## Status
DONE

## Outcome
`main.py` implementa la región de endpoints de vínculo ChatGPT (device-code OAuth) según
`global-constraints.md` §Link endpoints, consumiendo T01 (`supabase_data.py`) y T02
(`codex_app_server.py`) sin tocarlos:

- **`POST /api/settings/codex-link/start`** (`@api_key_rate_limit` + `get_current_user_id`):
  `linked` → 400 "Tu cuenta ChatGPT ya está vinculada."; `pending` → 409; si no, `acquire` +
  `account/login/start` con `{"type": "chatgptDeviceCode"}` y responde 200
  `{"ok":true,"verification_url":...,"user_code":...,"login_id":...,"expires_in":...}` (casing
  de la receta `verificationUrl/userCode/loginId` → snake_case; `expires_in` con default seguro
  `CODEX_LINK_TIMEOUT_SECONDS` si el server no lo reporta). Persiste fila `pending` con
  `login_id`. `CodexSpawnError` (y cualquier error del app-server) → 503 con mensaje honesto,
  sin reintento silencioso y sin tocar la fila.
- **`GET /api/settings/codex-link/status`**: `{"ok":true,"codex_status":...,"codex_plan_type":...,"last_error":...}`
  desde la fila. Si `pending` sin login en vuelo en este proceso (cold start: proceso del tenant
  recreado tras reinicio) y el grace de 60 s se agotó → marca `failed` con "El vínculo caducó
  por un reinicio del servidor. Vuelve a iniciarlo." (mensaje exacto del constraint). Dentro del
  grace sigue `pending`.
- **`POST /api/settings/codex-link/cancel`**: `account/login/cancel` con el `loginId` pendiente
  (best-effort con timeout propio), fila → `none`. Idempotente sin pendiente; un vínculo
  `linked` no se toca.
- **`DELETE /api/settings/codex-link`**: si `linked`, `account/logout` best-effort (un fallo NO
  bloquea el borrado local); borra la fila (antes de evacuar, para que el snapshot de evicción
  no re-persista credenciales), `codex_manager.evict(user_id)`, borra `CODEX_HOME`. Idempotente,
  devuelve `{"ok":true}`.
- **Notificación `account/login/completed`** (registrada vía `add_notification_handler` con
  registro idempotente): lee `<CODEX_HOME>/auth.json` (reintento acotado) →
  `encrypt_user_api_key(json.dumps(...))` → `upsert_user_provider_connection(status="linked",
  encrypted_credentials=..., plan_type=...)` con `account/read.planType` best-effort (fallback
  al `planType` de la propia notificación; valor crudo, sin allowlist). Timeout global
  `CODEX_LINK_TIMEOUT_SECONDS=600` (tarea propia por usuario) → `failed` + `account/login/cancel`
  en el server. El handler corre como tarea con timeout propio de 30 s: nunca bloquea la
  reader-task.
- **Lifespan** (main.py 288-315): en el `finally` existente se ejecuta
  `_cancel_codex_link_timeout_tasks()` y `await codex_manager.shutdown()`; el resto del lifespan
  intacto. Los dos cierres nunca lanzan excepción.
- **Seguridad**: `_codex_home_dir` valida `user_id` con UUID estricto (anti path traversal);
  nunca se loguea `auth.json`, `encrypted_credentials`, `user_code` ni `login_id` completo (solo
  `user_id[:8]` y `type(exc).__name__` en warnings; `login_id` nunca en logs).

Verificado con el fake de T02 (read-only, escenarios `login_completes`/`login_pending`/
`logout_ok`/`account_read_plan`), sin red ni binario real: 13 tests nuevos en
`tests/backend/test_codex_link_endpoints.py`.

## Acceptance Criteria
- start: linked→400 / pending→409 / 200 con los 4 campos y fila `pending`+`login_id` /
  spawn fallido→503 honesto -> pass (tests `test_start_400_when_linked`,
  `test_start_409_when_pending`, `test_start_503_when_spawn_fails`,
  `test_happy_path_links_and_persists_encrypted_auth`; assert de mensaje exacto 400 y de
  `verification_url`/`user_code`/`login_id`/`expires_in`==600)
- status: campos desde la fila; `none` sin vínculo; cold start pendiente→failed tras grace 60 s
  con el mensaje exacto; dentro del grace sigue pending -> pass (`test_status_none_without_link`,
  `test_cold_start_pending_stays_pending_within_grace`,
  `test_cold_start_pending_becomes_failed_after_grace`)
- cancel: `account/login/cancel` best-effort, fila→none, idempotente, sin tocar `linked` ->
  pass (`test_cancel_pending_goes_to_none`, `test_cancel_idempotent_without_pending`)
- delete: logout best-effort (fallo no bloquea), fila borrada, evict + CODEX_HOME borrado,
  idempotente, `{"ok":true}` -> pass (`test_delete_removes_link_and_is_idempotent`,
  `test_delete_logout_failure_does_not_block_local_delete`)
- notificación login/completed: auth.json cifrado persistido + planType best-effort (vía
  account/read y fallback a la notificación) -> pass (`test_happy_path_...` verifica decrypt del
  blob == contenido de auth.json y plan_type "plus"; `test_plan_type_from_account_read_best_effort`
  verifica que `account/read.planType` gana)
- timeout `CODEX_LINK_TIMEOUT_SECONDS` → failed + cancel en el server -> pass
  (`test_link_timeout_marks_failed_and_cancels`, con timeout acortado por monkeypatch)
- lifespan: shutdown hook en el `finally` -> pass (hook en el código; se ejecuta sin error en el
  teardown de sesión del fixture `_lifespan_app`, que entra/sale del lifespan real en el loop de
  sesión)
- sin credenciales en logs -> pass (auditoría manual: todos los log points usan `user_id[:8]` +
  `type(exc).__name__`; nada de auth.json/user_code/login_id)
- tests del flujo con el fake -> 13 passed

## Files Changed
- `main.py` - modified; imports (`shutil`, `pathlib.Path`, `from backend import supabase_data`,
  `from backend.crypto import encrypt_user_api_key`), shutdown hook en el `finally` del lifespan,
  y nueva sección "Codex / ChatGPT link (device-code OAuth)" (constantes, estado en memoria,
  helpers, handler de notificación, 4 endpoints) insertada en la región settings (~523-1002,
  antes de "# ---- Status (all providers) ----"). El runtime de T02 se importa **perezosamente**
  (`_codex_runtime()`), ver Decisions.
- `tests/backend/test_codex_link_endpoints.py` - created; 13 tests del flujo completo contra el
  fake de T02, sobre el loop de sesión de pytest-asyncio con httpx ASGITransport + lifespan real
  (una vez por sesión).

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `main.py` | `CODEX_LINK_TIMEOUT_SECONDS` | nuevo; `float(os.environ.get(..., "600"))` (env del constraint) |
| `main.py` | `_CODEX_COLD_START_GRACE_SECONDS`, `_CODEX_LINK_SERVER_TIMEOUT_SECONDS`, `_CODEX_LINK_HANDLER_TIMEOUT_SECONDS` | nuevos (grace 60 s, timeouts internos 15/30 s) |
| `main.py` | `CODEX_LINK_COLD_START_ERROR_MESSAGE` / `CODEX_LINK_TIMEOUT_ERROR_MESSAGE` / `CODEX_LINK_INCOMPLETE_ERROR_MESSAGE` | nuevos; mensajes UX exactos del constraint (cold start) y propios |
| `main.py` | `_codex_runtime()` | nuevo; import perezoso de `codex_manager`/`CodexAppServerError`/`CodexSpawnError` + registro idempotente del handler (ver Decisions) |
| `main.py` | `_codex_home_dir(user_id)` | nuevo; `CODEX_HOME` con validación UUID estricta |
| `main.py` | `_codex_pending_logins` / `_codex_cold_start_seen` / `_codex_link_timeout_tasks` | nuevos; estado en memoria del vínculo (login en vuelo, observación de cold start, tareas de timeout) |
| `main.py` | `_codex_schedule_timeout` / `_codex_clear_link_state` / `_cancel_codex_link_timeout_tasks` | nuevos; ciclo de vida del timeout y limpieza |
| `main.py` | `_codex_cancel_pending_login` | nuevo; `account/login/cancel` best-effort con timeout propio |
| `main.py` | `_codex_link_timeout_task` | nuevo; timeout global → `failed` + cancel en el server |
| `main.py` | `_codex_read_auth_json` | nuevo; lectura de auth.json con reintento acotado |
| `main.py` | `_codex_persist_login_completed` / `_codex_handle_login_completed` | nuevos; handler de la notificación (cifra y persiste, planType best-effort, timeout propio) |
| `main.py` | `_register_codex_login_completed_handler(manager)` | nuevo; registro idempotente (identidad en `_notification_handlers`, robusto a reload del módulo) |
| `main.py` | `_resolve_pending_codex_link` | nuevo; estado honesto de `pending` (login en vuelo / plazo vencido / cold start + grace) |
| `main.py` | `api_codex_link_start` / `api_codex_link_status` / `api_codex_link_cancel` / `api_codex_link_delete` | nuevos; endpoints con `@api_key_rate_limit` + `get_current_user_id` |
| `main.py` | `lifespan` | modified; `finally` gana `_cancel_codex_link_timeout_tasks()` + `await codex_manager.shutdown()` |
| `tests/backend/test_codex_link_endpoints.py` | (nuevo) | 13 tests: flujo feliz, 400/409/503, status none/pending/failed, cold start con/sin grace, timeout, cancel idempotente, delete idempotente + logout fallido, planType vía account/read |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_link_endpoints.py`
  Result: pass — 13 passed (8.4 s), solo warnings de deprecación de supabase/crypto preexistentes.
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_app_server.py tests/backend/test_codex_link_endpoints.py`
  Result: pass — 33 passed (ambos órdenes de archivo verificados).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py` (suite completa de `tests/backend`)
  Result: pass — 511 passed, 3 skipped (baseline previo: 498 passed, 3 skipped; +13 de T04, sin
  regresiones).

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_link_endpoints.py`
  contra `main.py` del baseline (HEAD 4a1f794, `git stash`): error de colección — los símbolos
  del contrato (`CODEX_LINK_COLD_START_ERROR_MESSAGE`, endpoints, etc.) no existen en el
  baseline. El test de aceptación solo puede ejecutarse con la implementación presente.
- GREEN: mismo comando con la implementación: 13 passed.
- Suites de regresión: T02 (20 tests) + test_api (35) + helpers/supabase/SSE (121) + suite
  completa (511) verdes tras la implementación final.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T04-brief.md` — autoridad de la tarea.
- `plans/chatgpt-codex-auth/global-constraints.md` — §Link endpoints y §Security invariants
  (formas de respuesta, estados, mensajes).
- `plans/chatgpt-codex-auth/context-map.md` — orientación general.
- `plans/chatgpt-codex-auth/integration-codex-appserver.md` — §Verified Contract (casing del
  device-code, cancel, logout, planType).
- `main.py` 288-315 (lifespan), 372-530 (región settings y patrón de endpoints), imports.
- `backend/codex_app_server.py` (T02, completo) — contrato del manager, singleton, request,
  add_notification_handler, evict/shutdown, snapshot/restore.
- `backend/supabase_data.py` 885-1184 — funciones T01 (get/upsert/delete_user_provider_connection).
- `backend/crypto.py` 100-159 — encrypt/decrypt_user_api_key.
- `tests/backend/test_codex_app_server.py` (T02) — patrón de loop de sesión y aislamiento.
- `tests/backend/fake_codex_app_server.py` — escenarios y wire-format del fixture (read-only).
- `tests/backend/conftest.py`, `pytest.ini`, `scripts/run_pytest.py` — infraestructura de tests.
- `backend/rate_limit.py` — decorador `@api_key_rate_limit` (requiere `request: Request`).
- `backend/auth.py` 130-160 — `get_current_user_id` para el override de tests.

Extra reads:
- `backend/crypto.py` 1-60 — confirmar fallback de MASTER_KEY en dev (los tests cifran sin env).
- `requirements.txt` / `requirements-dev.txt` — versiones (fastapi 0.115.5, pytest-asyncio ≥1.0
  con loop_scope, httpx ≥0.27 con ASGITransport).
- `main.py` 120-184 — definición de `logger` y constantes (ubicación de imports).
- scratch `test_output/lazy_test.py` — verificar el comportamiento de LOAD_GLOBAL vs `__getattr__`
  de módulo (PEP 562): **LOAD_GLOBAL no consulta el `__getattr__` de módulo** → se descartó esa
  vía (ver Decisions).

Pack gaps:
- None.

## Decisions
- **Import perezoso del runtime de T02 (`_codex_runtime()`)** en vez de import top-level:
  `backend/codex_app_server.py` lee su configuración de env en el import y congela el singleton
  `codex_manager` con esos valores. Un import top-level en `main.py` (cargado por `test_api.py`
  antes que el módulo de tests de T02) congelaba el singleton con el env del shell y rompía 17
  tests de T02 en la suite completa (regresión verificada: baseline 498 passed → 17 failed).
  `_codex_runtime()` importa en el primer uso real (endpoint o shutdown del lifespan), momento en
  el que el módulo de T02 ya fijó su env (si corre en la misma sesión) o el env es el del proceso
  (correcto en prod). Verificado verde en: suite completa, archivo solo, y ambos órdenes de
  archivo con T02. Se intentó primero PEP 562 (`__getattr__` de módulo): no funciona para
  referencias internas (LOAD_GLOBAL no lo consulta), descartado por evidencia.
- **Fixtures de test sobre el loop de sesión** (patrón de T02): `httpx.AsyncClient` +
  `ASGITransport` + lifespan real ejecutado **una vez por sesión** (`scope="session"` +
  `loop_scope="session"`). El `finally` del lifespan cierra el default executor del loop;
  ejecutarlo por test rompía los `asyncio.to_thread` de T02 en corridas conjuntas (RuntimeError
  "cannot schedule new futures after shutdown"). TestClient/portal no se usó: abriría otro loop y
  rompería las primitivas asyncio del singleton.
- **Estado "login en vuelo" en memoria de main** (`_codex_pending_logins`): es lo único que
  distingue un `pending` sano de un cold start (tras reinicio el registro se vacía). El grace de
  60 s se cuenta desde la primera observación del cold start (no desde `updated_at` de la fila),
  lo que evita depender del reloj de la DB y es directamente testeable.
- **Timeout activo por usuario** (`_codex_link_timeout_task`) + **check perezoso** en status como
  red de seguridad: el task garantiza `failed` + cancel en el server a los 600 s aunque el
  frontend deje de hacer polling; el check perezoso cubre el caso de reinicio (tasks muertos con
  el loop). Las tareas se cancelan en cancel/delete/completed y en el shutdown del lifespan (sin
  warnings de tasks pendientes).
- **planType**: primario `account/read.planType` (best-effort, valor crudo sin allowlist, como
  exige el constraint); fallback al `planType` de la propia notificación si el server no lo
  reporta (el fake de `login_completes` no implementa `account/read` con plan). Aditivo, no
  relaja el contrato: se documenta aquí por si el gate live (T10) revela otra forma.
- **Mensajes 409/503**: el constraint fija el 400 ("Tu cuenta ChatGPT ya está vinculada.") y el
  mensaje de cold start; el resto (409, 503, timeout) usan mensajes UX propios en español, sin
  detalles internos (invariante de seguridad).
- **Registro del handler idempotente por identidad** (`manager._notification_handlers`, lectura
  read-only de un atributo interno de T02): robusto a `importlib.reload` del módulo; no hay API
  pública para listar handlers en T02 y `codex_app_server.py` es do-not-touch.
- **Delete borra la fila ANTES de evict** para que el snapshot de evicción (T02) no re-persista
  credenciales de un vínculo ya eliminado; el rmtree explícito cubre el caso sin proceso
  registrado (reinicio).

## Concerns / Follow-ups
- **Fragilidad de orden de import en T02 (preexistente, fuera de alcance)**: si un módulo
  importa `backend.codex_app_server` antes que `tests/backend/test_codex_app_server.py` (que
  fija su env en el import), el singleton queda congelado con otro env y 3 tests de T02 que
  asertan rutas de su `_TEST_HOME_ROOT` fallan. Con esta implementación no ocurre en ningún
  orden natural (suite completa, solo T04, T02+T04 en ambos órdenes — todo verificado verde),
  porque nadie más importa el módulo antes que T02 en colección; pero la fragilidad es de diseño
  de T02 (env en import + singleton congelado) y no se tocó su archivo (do-not-touch).
- `_codex_handle_login_completed` usa `wait_for(..., 30)`; si el timeout corta el handler a mitad
  de un `asyncio.to_thread`, el hilo termina en background (acotado, sin fuga de loop). Caso
  degradado documentado.
- El fallback de planType a la notificación es una adición no especificada explícitamente (la
  vía primaria `account/read` se conserva y se testea). Si T10 confirma que `account/read` nunca
  devuelve plan en `login_completes`, el fallback es lo que hace funcionar el flujo feliz con
  planType.
- `expires_in` se devuelve como int (`int(result.get("expiresIn") or CODEX_LINK_TIMEOUT_SECONDS)`)
  para estabilizar el contrato de respuesta de T09.

## Remediation History
None for the initial implementation.

### Round 1 - plans/chatgpt-codex-auth/task-T04-review.md (RC-01)
- Finding IDs: `RC-01`
- Status: addressed
- Delta: `main.py` `_register_codex_login_completed_handler` (región codex-link,
  ~753-771): se eliminó el booleano global `_codex_login_handler_registered` y la
  comprobación por identidad (`handler is _codex_handle_login_completed`), que no
  sobreviven a `importlib.reload(main)` (el booleano vuelve a False y la función
  del módulo anterior es otro objeto). Ahora el registro usa una marca estable
  como atributo sobre la propia función handler
  (`_codex_handle_login_completed._codex_login_completed_handler_registered`):
  el scan de `manager._notification_handlers["account/login/completed"]`
  comprueba `getattr(handler, marca, False)`; tras un reload el manager conserva
  el handler del módulo anterior (que ya lleva la marca) y el registro retorna
  sin añadir un segundo handler. Sin cambios fuera de la región codex-link.
  `tests/backend/test_codex_link_endpoints.py`: nuevo test
  `TestHandler.test_login_completed_handler_registered_once_after_reload`, que
  siembra el estado post-reload (guard global reseteado + handler del módulo
  anterior como objeto distinto con su marca estable) y verifica que queda
  EXACTAMENTE UN handler registrado para `account/login/completed`.
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_link_endpoints.py -q`
    → `1 failed, 13 passed`; el test nuevo falla con `assert 2 == 1` (la
    implementación previa registró un segundo handler
    `_codex_handle_login_completed` junto al stale).
  - GREEN: mismo comando → `14 passed` (13 previos + 1 nuevo).
  - Regresión: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
    → `512 passed, 3 skipped` (baseline de la review: 511 passed, 3 skipped;
    +1 del test nuevo, sin regresiones).
- Concerns: tras un reload real, el handler del módulo anterior queda registrado
  (T02 no expone API de remove y su archivo es do-not-touch); el requisito de
  RC-01 (un único handler, sin doble procesamiento) se cumple. La re-asociación
  de logins en vuelo pre-reload al estado del módulo nuevo queda fuera del
  alcance del finding.
