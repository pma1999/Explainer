# Task T01 Report

## Status
DONE

## Outcome
La tabla `user_provider_connections` (PK `user_id` → `auth.users` con `on delete cascade`,
`provider='codex'` con CHECK, `status` CHECK `('none','pending','linked','failed')`,
`encrypted_credentials`/`login_id`/`plan_type`/`last_error`, timestamps) queda creada con RLS
por fila propia (`auth.uid() = user_id`) en
`supabase/migrations/20260814120000_user_provider_connections.sql`, con DDL idéntico (diff
verificado) al contrato fijo de `global-constraints.md` §Persistence y re-aplicable
(`create table if not exists` + `drop policy if exists` antes de cada `create policy`; sin
colisiones de timestamp: no existe ninguna migración `20260814*` en `supabase/migrations/`).

`backend/supabase_data.py` expone el contrato congelado para T02/T04/T07: `PROVIDER_CODEX = "codex"`
junto a las constantes existentes, `get_user_provider_connection(user_id) -> dict | None` (fila
completa con el blob cifrado tal cual, sin descifrar), `upsert_user_provider_connection(user_id, *,
status, encrypted_credentials=None, login_id=None, plan_type=None, last_error=None) -> None`
(upsert sobre `on_conflict="user_id"` refrescando `updated_at` vía `_now_iso()`; acepta el blob
opaco sin cifrar ni escribir texto plano — contrato documentado en el docstring) y
`delete_user_provider_connection(user_id) -> bool` (select previo + delete, idempotente, patrón
exacto de `delete_user_api_key`). `get_user_api_key_status` añade `has_codex_link` (bool),
`codex_status` (`none|pending|linked|failed`), `codex_plan_type` (str|null) y `codex_updated_at`
(str|null) leyendo `user_provider_connections`; ningún campo existente cambió de nombre ni forma
(el endpoint `GET /api/settings/api-key/status` de `main.py` devuelve el dict tal cual, sin tocar).

Error handling según el patrón del módulo: lecturas/delete loguean (solo `user_id[:8]` y tipo de
error, nunca credenciales ni `last_error`) y retornan valor seguro (`None`/`False`); el upsert
propaga excepciones de Supabase como caso crítico documentado (patrón de `set_user_api_key`, que
tampoco traga excepciones — un vínculo marcado persistido sin estarlo rompería el flujo OAuth de
T04).

Tests: 17 nuevos en `tests/backend/test_user_provider_connections.py` con cliente Supabase mockeado
sin red (patrón de `test_supabase_pdf_ocr_cache.py`/`test_supabase_data.py`): CRUD completo
(crear/actualizar/leer/borrar idempotente), `updated_at` refrescado, round-trip de cifrado
`encrypt_user_api_key`/`decrypt_user_api_key` (el blob almacenado nunca es texto plano y se
descifra idéntico), status combinado con claves existentes (campos viejos intactos), ausencia de
fila → defaults seguros, y errores de Supabase → retorno seguro. Suite backend completa en verde.

## Acceptance Criteria
- Migración `20260814120000_user_provider_connections.sql` con DDL exacto + RLS
  select/insert/update por fila propia, patrón de `user_api_keys`, re-aplicable -> pass
  (diff del bloque `create table` contra `global-constraints.md` líneas 65-75: idéntico; políticas
  `drop policy if exists` + `create policy` con `auth.uid() = user_id`; sin colisión de nombre).
- `PROVIDER_CODEX = "codex"` junto a constantes existentes (línea 896) + 3 funciones con firmas
  congeladas -> pass (firmas verificadas por los tests de import y por el diff).
- Upsert con patrón de `set_user_api_key` (upsert `on_conflict="user_id"`, `updated_at` al día) y
  blob cifrado aceptado tal cual -> pass (`test_upsert_passes_encrypted_blob_through_and_targets_user_id`,
  `test_upsert_refreshes_updated_at`, `test_encrypt_store_read_decrypt_round_trip`).
- `get_user_api_key_status` extendido sin renombrar nada -> pass
  (`test_status_combines_existing_keys_and_codex_link` + `test_status_safe_defaults_without_connection_row`;
  los 11 campos existentes siguen presentes en el dict incluso con error de Supabase).
- Errores de Supabase como en `has_user_api_key` (log + retorno seguro), salvo upsert (caso
  crítico documentado) -> pass (`test_get_returns_none_on_supabase_error`,
  `test_delete_returns_false_on_supabase_error`, `test_status_safe_defaults_on_supabase_error`,
  `test_upsert_propagates_supabase_errors`).
- Tests nuevos en `tests/backend/` con mock sin red -> pass (17/17; ver Tests).
- No tocar lo prohibido (main.py, crypto.py, agentes, frontend, Dockerfile, koyeb.yaml, DEPLOY.md,
  otras migraciones) -> pass (git diff: solo `backend/supabase_data.py` + 2 archivos nuevos).

## Files Changed
- `supabase/migrations/20260814120000_user_provider_connections.sql` - created; tabla + RLS
  select/insert/update + comentarios, re-aplicable.
- `backend/supabase_data.py` - modified; `PROVIDER_CODEX` + 3 funciones de almacenamiento +
  extensión de `get_user_api_key_status` (129 líneas añadidas).
- `tests/backend/test_user_provider_connections.py` - created; 17 tests unitarios con mock del
  cliente Supabase.
- `.venv-win/` - created (local, untracked); venv Python 3.11.8 (Windows, vía interop WSL) con
  `requirements-dev.txt` instalado — el entorno no tenía ningún intérprete con dependencias.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/supabase_data.py` | `PROVIDER_CODEX = "codex"` | Añadida constante |
| `backend/supabase_data.py` | `get_user_provider_connection(user_id: str) -> Optional[dict]` | Nueva: fila completa o `None`; error → log + `None` |
| `backend/supabase_data.py` | `upsert_user_provider_connection(user_id, *, status, encrypted_credentials=None, login_id=None, plan_type=None, last_error=None) -> None` | Nueva: upsert `on_conflict="user_id"` con `updated_at` al día; blob opaco; propaga errores (caso crítico documentado) |
| `backend/supabase_data.py` | `delete_user_provider_connection(user_id: str) -> bool` | Nueva: select previo + delete; idempotente; error → log + `False` |
| `backend/supabase_data.py` | `get_user_api_key_status(user_id) -> dict[str, Any]` | Extendida: +`has_codex_link`, `codex_status`, `codex_plan_type`, `codex_updated_at`; sin cambios en campos existentes |
| `supabase/migrations/20260814120000_user_provider_connections.sql` | tabla `public.user_provider_connections` + políticas RLS | Nueva migración (esquema fijo) |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_user_provider_connections.py -q`
  Result: pass — `17 passed, 1 warning` (warning: `APP_ENCRYPTION_KEY` no configurada, fallback
  temporal del módulo crypto; esperado en tests).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_supabase_data.py tests/backend/test_api.py -q`
  Result: pass — `94 passed, 1 warning`.
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q -m "not integration"`
  Result: pass — `465 passed, 3 deselected` (3 deselected = marcador `integration`, requieren
  credenciales/APIs reales; no ejecutadas).

## TDD Evidence
- RED: `python scripts/run_pytest.py tests/backend/test_user_provider_connections.py -q` →
  `ImportError: cannot import name 'PROVIDER_CODEX' from 'backend.supabase_data'` (1 error en
  colección) — fallo por el motivo esperado: símbolos del contrato aún inexistentes.
- GREEN: mismo comando tras implementar → `17 passed`. Un fallo intermedio
  (`test_get_returns_full_row_when_present`) por forma de `data` de `maybe_single` (list vs dict)
  corregido con normalización defensiva `r.data[0] if isinstance(r.data, list) else r.data`, y un
  bug del propio test (`side_effect` sin retorno) corregido en el test; ambos antes del verde final.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T01-brief.md` (completo)
- `plans/chatgpt-codex-auth/global-constraints.md` §Persistence y §Security invariants (líneas 60-89, 228-236)
- `plans/chatgpt-codex-auth/context-map.md` (orientación)
- `backend/supabase_data.py` 870-1055 (constantes, `has/get/set/delete_user_api_key`, `get_user_api_key_status`) y 1-80 (imports, `_client`, `_now_iso`)
- `supabase/migrations/20260406120000_multi_provider_api_keys.sql` (completo)
- `supabase/migrations/20260222120000_user_api_keys.sql` (completo — patrón RLS)
- `backend/crypto.py` 85-159 (`encrypt_user_api_key`/`decrypt_user_api_key`)

Extra reads:
- `tests/backend/test_supabase_pdf_ocr_cache.py` - patrón de mock del cliente (`MagicMock` + `patch("..._client")`), usado en los tests nuevos.
- `tests/backend/test_api.py` 440-570 + `main.py` 508-517 - confirmar que el endpoint de status devuelve el dict tal cual y que ningún test existente asume forma exacta del dict (no hay asserts de keys exactas).
- `tests/backend/conftest.py` - fixtures `client`/`auth_client` (no requeridas por los tests unitarios de almacenamiento).
- `pytest.ini`, `scripts/run_pytest.py`, `requirements-dev.txt` - runner y dependencias del repo.

Pack gaps:
- None (todo el Context Pack del brief existía y coincidía con las líneas indicadas).

## Decisions
- **`updated_at` refrescado en la función, no vía trigger**: el esquema fijo de
  `global-constraints.md` no incluye trigger; la migración no añade ninguno (desviación mínima
  respecto al patrón `user_api_keys` evitada para no salir del DDL fijo). El upsert pasa
  `updated_at: _now_iso()` explícito, satisfaciendo "updated_at al día" tanto en DB real como en
  los tests con mock.
- **Políticas RLS**: solo select/insert/update (literal del contrato fijo, que no lista delete).
  El borrado del backend va con service_role (bypass RLS), y la UI no borra filas directamente.
  Documentado en el comentario de la migración.
- **Re-aplicabilidad**: `drop policy if exists` antes de cada `create policy` (las migraciones
  previas no lo hacían, pero el criterio de aceptación lo exige).
- **Upsert propaga errores** (caso crítico documentado en el docstring): tragar el fallo de una
  escritura de credenciales haría que T04 marcara un vínculo que no existe en DB. Lecturas y
  delete siguen el patrón seguro de `has_user_api_key` (log + retorno seguro).
- **Normalización `maybe_single`**: `data` puede llegar como dict (cliente real) o lista de 1
  elemento (versiones del cliente/`Accept` header); `r.data[0] if isinstance(r.data, list) else
  r.data` en `get_user_provider_connection` y en la lectura de `codex_conn` del status.
- **Logs**: nunca se loguean `encrypted_credentials` ni `last_error`; solo `user_id[:8]` y
  tipo/mensaje de la excepción (el mensaje de excepción de supabase-py no contiene el blob).
- **Entorno de test**: el WSL no tenía intérprete con dependencias (`python` roto — shim pyenv-win
  con CRLF; `/usr/bin/python3` sin pip/venv). Se creó `.venv-win/` (Python 3.11.8 Windows vía
  interop, misma versión que el Dockerfile) con `requirements-dev.txt`; queda en el worktree como
  untracked para re-ejecutar tests; se puede borrar sin afectar al repo.

## Concerns / Follow-ups
- La migración NO se ha ejecutado contra un Postgres real (sin credenciales Supabase ni servidor
  local en este entorno); la sintaxis se validó por construcción contra el DDL fijo y el patrón de
  `user_api_keys` (diff exacto verificado), pero la aplicación real (`supabase db push`/CLI) queda
  fuera de T01. La re-aplicabilidad se garantiza por construcción (`if not exists` +
  `drop policy if exists`), no por ejecución.
- `get_user_api_key_status` ahora hace 2 queries por llamada (una a `user_api_keys`, otra a
  `user_provider_connections`); mismo try/except único: si falla la segunda, los campos codex
  quedan en defaults seguros sin romper el status.
- Contrato respetado sin relajaciones: firmas, DDL y campos del status son los del brief.

## Remediation History
None for the initial implementation.
