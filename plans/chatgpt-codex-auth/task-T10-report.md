# Task T10 Report

## Status
DONE_WITH_CONCERNS

## Outcome
Verificación integrada final ejecutada sobre el árbol T01–T09 (baseline `4a1f794`):
backend completo `564 passed, 3 skipped` y frontend `339 passed` verificados con
salida real. Creado `tests/test_codex_live_login.py` (marker `integration`, skip por
defecto vía `CODEX_LIVE=1`, fuera de `testpaths`) con el flujo live completo
(device code manual → linked → turno real `gpt-5.6-luna` → logout → evict) y
docstring con instrucciones y credenciales reales. Producidos
`plans/chatgpt-codex-auth/final-review.md` (alcance por área, suites con salida
real, riesgos R-* post-implementación, checklist de seguridad) y
`progress.md` actualizado (T10 done, decision ledger ampliado, fila de final
review). Live gate **PENDING** (requiere cuenta ChatGPT del usuario). Concerns:
`npm run test:all` no es verde en este entorno (sin `python` en PATH de npm y
sin `@playwright/test` instalado — smoke E2E preexistente nunca ejecutable
aquí) y `docker build` no verificable (sin daemon Docker/WSL); ambos quedan
registrados como not-verified, no como defectos.

## Acceptance Criteria
- `python scripts/run_pytest.py` en verde → pass: ejecutado dos veces;
  `564 passed, 3 skipped, 10 warnings in 29.59s` (corrida final) y `30.35s`
  (primera). Los 3 skipped son preexistentes (fuera del alcance del bundle).
- `npx vitest run` en verde → pass: `Test Files 19 passed (19)`, `Tests 339
  passed (339)`, Duration 19.24s.
- `npm run test:all` en verde → fail por entorno: dentro del orquestador pasan
  vitest (339) y pytest (564); el paso E2E no arranca (`sh: 1: playwright: not
  found`; `@playwright/test` ausente → `Cannot find package '@playwright/test'`
  en los specs). No es defecto del bundle; se documenta como not-verified.
- `tests/test_codex_live_login.py` → pass: creado; `1 skipped` en la corrida
  con `-m integration` (skip por diseño); marker integration + docstring con
  instrucciones de device code manual y credenciales reales.
- `final-review.md` → pass: creado con alcance real por área, suites con salida
  real, live gate PENDING, riesgos R-PROTO/R-MEM/R-AUTHJSON/R-USAGE/R-MODEL/
  R-CONC/R-COLD/R-RESOURCES/R-TARBALL con estado, checklist de seguridad y
  limitaciones.
- `progress.md` actualizado → pass: T10 done, decision ledger con las 3
  entradas nuevas (koyeb documental, limitación de entorno test:all, live gate
  PENDING), fila de final review done; eliminadas las filas duplicadas de
  T09/T10 que quedaron de la plantilla inicial.

## Files Changed
- `tests/test_codex_live_login.py` - created; live gate del proveedor Codex:
  device-code real → linked → turno gpt-5.6-luna → logout; marker
  `integration`, skip por defecto (`CODEX_LIVE=1`), nunca en la suite por
  defecto (`pytest.ini` limita a `tests/backend`).
- `plans/chatgpt-codex-auth/final-review.md` - created; review final con
  evidencia real (formato de referencia: `plans/android-app/final-review.md`).
- `plans/chatgpt-codex-auth/progress.md` - modified; estados finales, decision
  ledger, fila de final review, corrección de filas duplicadas.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `tests/test_codex_live_login.py` | `test_live_device_code_link_turn_and_logout` | new; test async con `pytestmark` = [integration, asyncio(loop_scope=session), skipif(!CODEX_LIVE)] |
| `tests/test_codex_live_login.py` | `_codex_manager` / `_verify_binary_present` | new; helpers internos (import diferido del singleton; guard del binario real) |
| `plans/chatgpt-codex-auth/final-review.md` | — | new; documento de review (no código) |
| `plans/chatgpt-codex-auth/progress.md` | Decision ledger / tabla de tareas / Final review | modified; T10 done + 3 entradas de ledger + fila final review |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py`
  Result: pass — `564 passed, 3 skipped, 10 warnings in 29.59s` (exit 0);
  primera corrida idéntica en 30.35s.
- Command: `npx vitest run`
  Result: pass — `Test Files 19 passed (19)`, `Tests 339 passed (339)` (exit 0).
- Command: `PATH="/tmp/opencode/t10-bin:$PATH" npm run test:all` (bridge
  symlink `python` → `.venv-win/Scripts/python.exe`)
  Result: fail parcial por entorno — vitest 339 pass y pytest 564 pass dentro
  del orquestador; paso 3 `playwright test` → `sh: 1: playwright: not found`;
  `node node_modules/playwright/cli.js test --list` → `Error: Cannot find
  package '@playwright/test' imported from tests/e2e/app.spec.js` (y
  shared.spec.js). Exit 1.
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/test_codex_live_login.py -m integration -v`
  Result: pass — `1 skipped` (razón del skipif: requiere CODEX_LIVE=1, binario
  real y cuenta ChatGPT), exit 0.
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py --collect-only -q`
  Result: `567 tests collected` (solo `tests/backend`; el test live queda fuera
  de la suite por defecto, como diseño).
- Command: `docker version --format '{{.ServerVersion}}'` / `docker info`
  Result: not-verified — "The command 'docker' could not be found in this WSL 2
  distro" (integración WSL 2 de Docker Desktop desactivada).
- Command: `git status --short android/` y `git diff HEAD --stat -- android/`
  Result: 0 entradas / diff vacío — android/ intacto.

## TDD Evidence
- RED: no aplica defecto de producción: la tarea es verificación integrada y
  artefactos de evidencia. El único código nuevo es el test live, cuyo criterio
  es "skip por defecto": corrida inicial (antes del arreglo del escape `\c` en
  el docstring) mostró `DeprecationWarning: invalid escape sequence '\c'`;
  tras corregir el docstring, la corrida quedó limpia (`1 skipped`, sin
  warnings).
- GREEN: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/test_codex_live_login.py -m integration -v`
  → `1 skipped in 0.02s` sin warnings; suite por defecto intacta (564 passed).
  Las suites integradas (564/339) pasaron en el árbol con el test nuevo
  presente.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T10-brief.md` (autoridad de la tarea)
- `plans/chatgpt-codex-auth/global-constraints.md` (§Security invariants como
  checklist)
- `plans/android-app/final-review.md` (formato de referencia)
- `pytest.ini`, `scripts/run_pytest.py` (runner/markers)
- `tests/backend/conftest.py` (fixtures client/auth_client)
- `package.json` (scripts test:all)
- `plans/chatgpt-codex-auth/plan.md` (riesgos R-*, live gate, verification
  strategy)
- `plans/chatgpt-codex-auth/progress.md` (estados T01–T09)

Extra reads:
- `tests/backend/test_gemini_pdf_live_investiture.py` y
  `tests/backend/test_formatter_live.py` — patrón existente de tests live con
  marker integration y skipif por credenciales (para el nuevo test).
- `backend/codex_app_server.py` (completo) — API del manager/singleton y
  resolución lazy de env para escribir el test live correctamente.
- `backend/codex_client.py` — firma de `call_codex_chat` y `response_format`
  para el turno real del test live.
- `main.py` (secciones codex-link y helpers `_codex_runtime`/`_codex_home_dir`)
  — flujo de los endpoints que el test live ejercita y validación UUID.
- `tests/backend/fake_codex_app_server.py` — escenarios y contrato del fake
  (para distinguir del binario real en el test live).
- `tests/backend/test_codex_link_endpoints.py` — patrón de fixtures
  asyncio/loop_scope y `_uid()` para el estilo del test live.
- `scripts/run-all-tests.js`, `playwright.config.js`, `tests/e2e/app.spec.js`,
  `tests/e2e/shared.spec.js`, `node_modules/playwright/package.json` — causa
  raíz del fallo de E2E (`@playwright/test` ausente, shims solo Windows).
- `supabase/migrations/20260814120000_user_provider_connections.sql`,
  `Dockerfile`, `backend/crypto.py`, `koyeb.yaml` — checklist de seguridad
  (RLS, 0700, Fernet, sin Node) con evidencia de inspección.
- `git diff HEAD` (completo) — escaneo de credenciales y alcance por área.

Pack gaps:
- None.

## Decisions
- `tests/test_codex_live_login.py` se coloca en `tests/` (raíz) y NO en
  `tests/backend/`: `pytest.ini` limita `testpaths` a `tests/backend`, con lo
  que el test live queda fuera de la suite por defecto además del skipif por
  env — doble protección, según el brief ("skip por defecto").
- El turno real del live test usa `response_format="text"` con el prompt
  mínimo "Responde solo con la palabra ok": valida el wire-format real
  (`turn/start` + parseo) consumiendo la mínima cuota del plan; el JSON del
  explainer ya está cubierto por el fake.
- La espera del vínculo usa la notificación `account/login/completed` (vía
  `add_notification_handler`, el contrato real del manager) + verificación de
  `auth.json` en CODEX_HOME; el login_id se compara para no aceptar
  notificaciones de otro tenant.
- `npm run test:all` se ejecutó con un bridge temporal en `/tmp/opencode`
  (symlink `python` → python.exe del venv) para aislar el fallo real del paso
  E2E; no se modificó node_modules ni el venv. El fallo E2E se verificó además
  con `node node_modules/playwright/cli.js test --list` (raíz: paquete
  `@playwright/test` ausente), por lo que no es atribuible al entorno de
  ejecución de pytest sino al estado de instalación npm.
- `progress.md`: se eliminaron las filas duplicadas T09/T10 (artefacto de la
  plantilla inicial) al reescribir la tabla; T10 marcada done; decision ledger
  ampliado con la excepción documental de koyeb.yaml (T08), la limitación de
  entorno de test:all y el live gate PENDING.

## Concerns / Follow-ups
- Live gate `tests/test_codex_live_login.py` **PENDING**: requiere cuenta
  ChatGPT real del usuario (device code manual + cuota). Hasta que se ejecute,
  R-PROTO/R-AUTHJSON/R-MODEL no están cerrados contra el binario real; la
  compatibilidad no se afirma (constraint del brief).
- `npm run test:all` y el smoke E2E preexistente no son verificables en este
  entorno (`@playwright/test` no instalado; binario unix de playwright ausente
  — solo shims `.cmd`). Recomendado: `npm install`/reparar node_modules en un
  entorno Windows nativo o WSL con Node antes de certificar el paso 3.
- `docker build` not-verified (sin daemon Docker en WSL): el pin sha256 del
  tarball está en el Dockerfile (T08 lo verificó en host), pero la construcción
  de la imagen y `codex --version` en contenedor quedan pendientes.
- Migración no ejercitada contra Postgres real (F01 de T01 sigue abierto como
  hallazgo non-blocking; su verificación natural es el despliegue/live).
- Los 3 tests skipped de la suite backend son preexistentes y ajenos al
  bundle; no se investigó su causa (fuera del alcance de T10).

## Remediation History
None for the initial implementation.
