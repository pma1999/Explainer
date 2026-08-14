# Review: task T01

## Veredicto
APPROVE_WITH_FINDINGS

## Findings

- `F01` | non-blocking | Los tests nuevos no cubren la re-aplicabilidad de la migración, aunque el SQL usa `create table if not exists` y recrea las tres policies con `drop policy if exists`; falta evidencia ejecutable para ese criterio de aceptación.

## Verificación funcional

- Revisados el brief, el report del implementer y `global-constraints.md` (§Persistence y §Security invariants).
- Revisado el diff aislado y los tres archivos de T01. La migración coincide con el esquema fijado: PK/FK UUID con cascade, provider/status checks, timestamps y RLS select/insert/update propias.
- Confirmado `PROVIDER_CODEX`, las tres firmas congeladas, upsert por `user_id` con `updated_at`, lectura del blob sin descifrar y los cuatro campos Codex del status sin alterar los existentes.
- Confirmado que el cifrado usa el contrato caller-side con `encrypt_user_api_key`/`decrypt_user_api_key`; no se observan logs de `encrypted_credentials` ni `last_error`.
- Confirmado que `none/pending/linked/failed` se reflejan correctamente en `codex_status` y `has_codex_link`.

## Comandos ejecutados

- `python scripts/run_pytest.py tests/backend/test_user_provider_connections.py tests/backend/test_supabase_data.py` — no ejecutable: el shim pyenv-win del intérprete por defecto falló (`cannot execute: required file not found`).
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_user_provider_connections.py tests/backend/test_supabase_data.py` — **76 passed**, 1 warning esperado por `APP_ENCRYPTION_KEY` no configurada.
- `find supabase/migrations ...` — confirmado que `20260814120000_user_provider_connections.sql` es el único `20260814*` y no colisiona por nombre.

## Required changes

- `F01` | non-blocking | Owner hint: `tests/backend/test_user_provider_connections.py` | La suite no prueba la re-aplicación de `20260814120000_user_provider_connections.sql`. | Añadir una verificación que aplique/parsee el SQL dos veces contra un Postgres/Supabase de prueba, o documentar explícitamente esa limitación si el entorno no dispone de base real. | Status: open

## Evidence

- `supabase/migrations/20260814120000_user_provider_connections.sql:12-49`: DDL y policies RLS propias, idempotentes por construcción.
- `backend/supabase_data.py:896-1183`: constante, CRUD, cifrado opaco y status extendido.
- `tests/backend/test_user_provider_connections.py:43-287`: CRUD, round-trip Fernet, estados y defaults; no contiene prueba de migración.

## Limitaciones

- No se ejecutó la migración contra PostgreSQL/Supabase real; la re-aplicabilidad fue inspeccionada estáticamente, no observada en ejecución.
