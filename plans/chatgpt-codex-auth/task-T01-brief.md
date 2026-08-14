# Task T01: Migración y almacenamiento cifrado del vínculo ChatGPT (user_provider_connections)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Crear la tabla `user_provider_connections` con RLS y las funciones de almacenamiento en
`backend/supabase_data.py` (incluida la extensión de `get_user_api_key_status` con los campos
codex), que serán el contrato de datos de todas las tareas posteriores.

## Acceptance Criteria
- Existe `supabase/migrations/20260814120000_user_provider_connections.sql` con el DDL exacto de
  `global-constraints.md` (PK `user_id` FK a `auth.users` con `on delete cascade`, `provider`
  default `'codex'` con CHECK, `status` CHECK en `('none','pending','linked','failed')`, columnas
  `encrypted_credentials`, `login_id`, `plan_type`, `last_error`, timestamps) y RLS habilitada con
  políticas select/insert/update sobre filas propias (`auth.uid() = user_id`), patrón de
  `20260222120000_user_api_keys.sql`. La migración es re-aplicable sin error.
- `backend/supabase_data.py` define `PROVIDER_CODEX = "codex"` junto a las constantes existentes
  (líneas 891-895) y las funciones congeladas:
  `get_user_provider_connection(user_id) -> dict | None`,
  `upsert_user_provider_connection(user_id, *, status, encrypted_credentials=None, login_id=None,
  plan_type=None, last_error=None) -> None`,
  `delete_user_provider_connection(user_id) -> bool`.
- El upsert usa el patrón de `set_user_api_key` (upsert sobre `user_id`, `updated_at` al día) y
  nunca escribe credenciales sin cifrar: el caller cifra; la función de escritura acepta el blob
  tal cual (contrato documentado).
- `get_user_api_key_status(user_id)` devuelve además `has_codex_link` (bool),
  `codex_status` (`none|pending|linked|failed`), `codex_plan_type` (str|null) y
  `codex_updated_at` (str|null) leyendo `user_provider_connections`; ningún campo existente
  cambia de nombre ni de forma.
- Errores de Supabase se tratan como en `has_user_api_key` (log + retorno seguro, sin excepción
  al caller salvo casos críticos documentados).
- Tests nuevos en `tests/backend/` (fixture `client`/`auth_client` y mocks del cliente Supabase
  como en `test_supabase_data.py`): CRUD completo, round-trip de cifrado con
  `encrypt_user_api_key`/`decrypt_user_api_key`, status combinado con claves existentes, ausencia
  de fila → campos default seguros.

## Scope
Touch:
- `supabase/migrations/20260814120000_user_provider_connections.sql` (nuevo)
- `backend/supabase_data.py` (constante + 3 funciones + extensión de `get_user_api_key_status`)
- `tests/backend/test_user_provider_connections.py` (nuevo) y/o ampliación de
  `tests/backend/test_supabase_data.py` sin tocar sus casos existentes

Do not touch:
- `main.py`, agentes, `backend/crypto.py`, frontend, Dockerfile, koyeb.yaml, DEPLOY.md
- Cualquier otra migración existente

## Constraints
- Solo los invariantes de `global-constraints.md` → sección "Persistence". El esquema es fijo;
  cualquier desviación es un bloqueo a reportar, no un ajuste silencioso.
- Los accesos usan el cliente Supabase existente (`_client()`, service_role); la identidad
  `user_id` siempre viene del caller (ya validada por JWT aguas arriba).
- Sin logs de `encrypted_credentials` ni de `last_error` con contenido sensible.

## Interfaces
Consumes:
- `backend/crypto.py`: `encrypt_user_api_key`/`decrypt_user_api_key` (read-only).
- Patrón de `set_user_api_key`/`get_user_api_key`/`delete_user_api_key`
  (`supabase_data.py:889-996`) y de `get_user_api_key_status` (`998-1055`).
- Convención de migraciones: `supabase/migrations/20260222120000_user_api_keys.sql` y
  `20260406120000_multi_provider_api_keys.sql` (RLS/políticas).

Produces (contrato congelado para T02/T04/T07):
- `PROVIDER_CODEX = "codex"`
- `get_user_provider_connection(user_id: str) -> dict | None`
- `upsert_user_provider_connection(user_id, *, status, encrypted_credentials=None, login_id=None,
  plan_type=None, last_error=None) -> None`
- `delete_user_provider_connection(user_id: str) -> bool`
- `get_user_api_key_status` extendido con `has_codex_link`, `codex_status`, `codex_plan_type`,
  `codex_updated_at`.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/chatgpt-codex-auth/global-constraints.md` | Persistence; Security invariants | secciones correspondientes | DDL y firmas fijas |
| `backend/supabase_data.py` | `set_user_api_key`, `get_user_api_key`, `delete_user_api_key`, `get_user_api_key_status` | 889-1055 | Patrón de upsert/lectura/borrado y forma del status |
| `supabase/migrations/20260406120000_multi_provider_api_keys.sql` | PK compuesta + comentarios | completo | Estilo de migración del repo |
| `supabase/migrations/20260222120000_user_api_keys.sql` | RLS policies | completo | Patrón exacto de políticas por fila |
| `backend/crypto.py` | `encrypt_user_api_key`/`decrypt_user_api_key` | 115-159 | Reutilización directa, sin código nuevo de cifrado |

## Existing Patterns To Reuse
- `set_user_api_key` (upsert atómico + cifrado antes de persistir) y `delete_user_api_key`
  (select previo + delete) como plantilla exacta.
- Forma del dict de `get_user_api_key_status` para añadir campos nuevos sin romper consumidores
  (frontend `auth.js` lee los campos existentes por nombre).

## Tests
- `python scripts/run_pytest.py tests/backend/test_user_provider_connections.py`
- Criterios: upsert crea/actualiza y refresca `updated_at`; `get` devuelve fila o `None`;
  `delete` idempotente; `get_user_api_key_status` combina claves + vínculo sin campos rotos;
  mock del cliente Supabase sin red (patrón de `test_supabase_data.py`).

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: el esquema RLS y las firmas de almacenamiento son el contrato de datos de todas las olas;
un error aquí se propaga a vínculo, pipeline y UI.

## Named Risks
- La migración se aplica con la convención de timestamps del repo; confirmar que el nombre
  `20260814120000_` no colisiona con migraciones existentes (listado de `supabase/migrations/`).
- `auth.uid() = user_id` exige que la columna sea `uuid`; no inventar castings.

## Report Path
`plans/chatgpt-codex-auth/task-T01-report.md`
