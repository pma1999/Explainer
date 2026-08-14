# Task T04: Endpoints de vinculación device-code y ciclo de vida (lifespan)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Implementar en `main.py` los cuatro endpoints del vínculo ChatGPT (`start/status/cancel/delete`),
la captura de `account/login/completed`, el estado honesto de cold start y el shutdown hook del
`codex_manager` en el lifespan.

## Acceptance Criteria
- `POST /api/settings/codex-link/start` (`@api_key_rate_limit`, `get_current_user_id`): si la
  fila T01 está `linked` → 400 "Tu cuenta ChatGPT ya está vinculada."; si `pending` → 409. Llama
  `account/login/start` con `type="chatgptDeviceCode"` en el app-server del tenant y guarda fila
  `pending` con `login_id`; responde 200
  `{"ok":true,"verification_url":...,"user_code":...,"login_id":...,"expires_in":...}` con el
  casing de la receta (`verificationUrl`/`userCode`/`loginId` mapeados a snake_case en la
  respuesta). `CodexSpawnError` → 503 con mensaje honesto.
- `GET /api/settings/codex-link/status`: devuelve
  `{"ok":true,"codex_status":...,"codex_plan_type":...,"last_error":...}` desde la fila; si
  `pending` y el proceso del tenant fue recreado sin login en vuelo (cold start), tras grace de
  60 s marca `failed` con "El vínculo caducó por un reinicio del servidor. Vuelve a iniciarlo.".
- `POST /api/settings/codex-link/cancel`: `account/login/cancel` con el `loginId` pendiente
  (best-effort), fila → `none`; idempotente sin pendiente.
- `DELETE /api/settings/codex-link`: si `linked` → `account/logout` best-effort; borra la fila,
  `codex_manager.evict(user_id)`, borra `CODEX_HOME`. Idempotente; un logout fallido no bloquea
  el borrado local. Devuelve `{"ok":true}`.
- La notificación `account/login/completed` (registrada vía
  `codex_manager.add_notification_handler("account/login/completed", handler)`) persiste:
  leer `<CODEX_HOME>/auth.json` → `encrypt_user_api_key(json.dumps(...))` →
  `upsert_user_provider_connection(status="linked", encrypted_credentials=..., plan_type=...)`
  con `account/read.planType` best-effort. Timeout `CODEX_LINK_TIMEOUT_SECONDS=600` → `failed` +
  cancel en el server.
- En `lifespan` (main.py 288-306), dentro del `finally` se ejecuta
  `await codex_manager.shutdown()`; el resto del lifespan intacto.
- Sin credenciales en logs (nunca `auth.json`, `user_code` completo se loguea truncado o no se
  loguea; `login_id` solo en logs debug).
- Tests `tests/backend/test_codex_link_endpoints.py` (fixture `auth_client` + fake de T02, que
  ya incluye los escenarios `login_completes`/`login_pending`/`logout_ok`/`account_read_plan`;
  se consume read-only): flujo feliz start→completed→status linked con planType, cancel, delete
  idempotente, timeout de vínculo, cold-start pendiente→failed, 400/409/503 y campos de status
  sin vínculo (none).

## Scope
Touch:
- `main.py` (solo: nuevos endpoints en la región settings ~372-530, imports de
  `backend/codex_app_server.py` y `backend/supabase_data.py`, lifespan shutdown)
- `tests/backend/test_codex_link_endpoints.py` (nuevo)

Do not touch:
- Pipeline (`_process_project` y pre-checks), agentes, `backend/codex_client.py`,
  `codex_app_server.py`, frontend, `supabase_data.py`, migraciones

## Constraints
- Solo los invariantes de `global-constraints.md` → "Link endpoints" y "Security invariants".
  Las formas de respuesta son contrato para T09.
- El handler de notificación no debe bloquear la reader-task: operaciones de red/DB async con
  timeout propio.
- Registro del handler idempotente (proteger contra doble registro si el módulo se recarga).

## Interfaces
Consumes:
- T01: `get_user_provider_connection`, `upsert_user_provider_connection`,
  `delete_user_provider_connection`, `encrypt_user_api_key` (`backend/crypto.py:115-135`).
- T02: `codex_manager`, `CodexAppServer.request`, `add_notification_handler`, `evict`,
  `shutdown`, `CodexSpawnError`.
- `@api_key_rate_limit` y `get_current_user_id` existentes en `main.py` (patrón de
  `api_set_deepseek_key`, main.py ~470-517).

Produces (contrato para T09/T07):
- Endpoints `POST/GET /api/settings/codex-link/{start,status,cancel}` y
  `DELETE /api/settings/codex-link` con las formas JSON de `global-constraints.md`.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/chatgpt-codex-auth/integration-codex-appserver.md` | device-code, login/completed, cancel, logout | §Verified Contract | Casing y semántica del flujo |
| `plans/chatgpt-codex-auth/global-constraints.md` | Link endpoints | sección | Formas y estados fijos |
| `main.py` | `lifespan`, endpoints settings | 288-306, 372-530 | Dónde insertar; patrón de endpoints |
| `main.py` | `get_user_id_from_token` / SSE (solo referencia) | 4472-4509 | No tocar |
| `backend/supabase_data.py` | funciones T01 | (nuevas en T01) | Contrato de almacenamiento |

## Existing Patterns To Reuse
- Endpoints `api_set_*_key`/`api_delete_*_key` (form, rate limit, logs con máscara) para estilo y
  manejo de errores HTTP.
- `lifespan` actual para colgar el shutdown sin reescribir el resto.

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_link_endpoints.py`
- Señal verde: todos los estados del flujo con el fake; sin red real ni binario real.

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: frontera OAuth/device-code y manejo de credenciales; estado erróneo aquí expone vínculos
rotos o datos de otros tenants.

## Named Risks
- El nombre exacto del método `account/login/start` y el parámetro `type` son per-docs/VERIFIED
  en fuente (receta §Verified Contract); si el fake y el binario real difieren, el gate live
  (T10) lo detecta.
- `expires_in` puede no venir en la respuesta real: usar default seguro (600 s) sin romper el
  contrato de respuesta.

## Report Path
`plans/chatgpt-codex-auth/task-T04-report.md`
