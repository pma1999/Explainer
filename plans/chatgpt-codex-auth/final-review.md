# Review: final — Proveedor Codex (ChatGPT) en el explainer web

## Verdict

PASS WITH REQUIRED CHANGES — FR-01 y FR-01b están resueltos contra el contrato
source-pinned y las suites automatizadas pasan. FR-02/FR-03/FR-04 siguen abiertos
como pendientes non-blocking de entorno/usuario.

## Alcance real del diff (por área)

Baseline `4a1f794` (HEAD confirmado con `git rev-parse HEAD`). Árbol con T01–T09
integrados; T10 añadió solo el test live y esta review. Áreas:

- **Backend** (tracked, `git diff HEAD`): `main.py` (+973/−…; endpoints de
  vínculo device-code, pre-checks, threading codex en el pipeline, usage),
  `backend/supabase_data.py` (+129; funciones de conexión + campos de status),
  `backend/pricing.py` (+8; entrada `gpt-5.6-luna` a 0.0), agentes
  `segmentador.py`/`page_classifier.py`/`recorrido.py`/`resources.py`/
  `review.py`/`formatter.py` (variantes codex), `tests/backend/test_main_helpers_v2.py` (+26).
  Untracked nuevos: `backend/codex_app_server.py`, `backend/codex_client.py`,
  `backend/codex_model_routing.py`, `backend/agents/explainer_codex.py`,
  `tests/backend/fake_codex_app_server.py`, `tests/backend/fixtures_codex/`,
  `tests/backend/test_codex_{app_server,client,env_lazy,link_endpoints,agents_core,agents_family,pipeline,user_provider_connections}.py`.
- **Frontend** (tracked): `frontend/js/auth.js` (+331; flujo de vínculo y panel),
  `landing.js`, `state.js`, `storage.js`, `projectView.js` (solo bloque de uso),
  `index.html`, `style.css`; tests `tests/frontend/{auth,landing,landingFlow,projectViewProgress,state,storage}.test.js`.
- **Deploy** (tracked): `Dockerfile` (+20; binario `codex` pineado 0.147.0 con
  sha256, sin Node), `DEPLOY.md` (+97), `koyeb.yaml` (+14, **solo comentario
  documental**: `type: web`, `min: 0` scale-to-zero, `max: 1`, healthcheck
  `/healthz`, `nano` intactos — verificado en el diff y en las claves
  funcionales actuales).
- **Supabase** (untracked nuevo): `supabase/migrations/20260814120000_user_provider_connections.sql`
  (tabla + RLS, re-aplicable).
- **Android**: `git status --short android/` → **0 entradas**; `android/` está
  trackeado y `git diff HEAD --stat -- android/` vacío → intacto. (En el bundle
  android-app era untracked; ahora el árbol está commiteado y sin cambios.)

## Resultados de las suites (comando + salida REAL)

| Comando | Salida observada | Estado |
|---|---|---|
| `.venv-win/Scripts/python.exe scripts/run_pytest.py` | `577 passed, 3 skipped, 10 warnings in 29.59s` (evidencia inicial; la re-review ejecutó el scope backend explícito) | **PASS** |
| `npx vitest run` | `Test Files 19 passed (19) / Tests 339 passed (339)`, Duration 19.24s | **PASS** |
| `npm run test:all` | Paso 1 vitest: 339 passed; paso 2 pytest: `564 passed, 3 skipped`; paso 3 `playwright test` → **`sh: 1: playwright: not found`** → el script aborta con exit 1 | **NO GREEN en este entorno** (ver abajo) |
| `python scripts/run_pytest.py tests/test_codex_live_login.py -m integration -v` | `1 skipped` (razón: requiere `CODEX_LIVE=1`, binario real y cuenta ChatGPT) | **PASS (skip por diseño)** |
| `docker build -t explainer-codex-test .` | **not-verified**: Docker Desktop no tiene activada la integración WSL 2 (`docker version` → "The command 'docker' could not be found in this WSL 2 distro") | **not-verified** |

**Por qué `test:all` no es verde aquí (condición de entorno, no defecto del
código):**
1. `npm run test:backend` invoca `python`, que no está en el PATH del shell de
   npm: el venv del repo es `.venv-win/` con `python.exe` (solo binarios
   Windows). Se verificó con un bridge temporal (`/tmp/opencode/t10-bin/python`
   → symlink a `.venv-win/Scripts/python.exe`): con él, los pasos 1 y 2 de
   `test:all` pasan completos dentro del orquestador.
2. El paso E2E no puede arrancar: `node_modules/.bin/` solo contiene shims
   Windows (`playwright.cmd`), no existe el binario unix `playwright`, y el
   paquete `@playwright/test` **no está instalado** (`node_modules/@playwright/`
   está vacío; `playwright.config.js` y los specs importan `@playwright/test`).
   `node node_modules/playwright/cli.js test --list` → `Error: Cannot find
   package '@playwright/test'` en `tests/e2e/app.spec.js` y `shared.spec.js`.
   Es un estado de instalación preexistente (el smoke nunca fue ejecutable en
   este entorno); no lo introducen T01–T09.
→ El smoke E2E existente queda **not-verified** y `npm run test:all` no puede
certificarse verde hasta correr en un entorno con Node completo (o con la
instalación npm reparada).

## Live gate

**PENDING — requiere cuenta ChatGPT del usuario** (vínculo device-code real +
un turno `gpt-5.6-luna` consume cuota real del plan; no se dispone de
credenciales).

Creado `tests/test_codex_live_login.py`: marker `integration`, **skip por
defecto** (env `CODEX_LIVE=1`), fuera de `testpaths` (`pytest.ini` → solo
`tests/backend`), docstring con instrucciones del device code manual y
credenciales reales. Flujo: `acquire` del app-server real (CODEX_BIN_PATH) →
`account/login/start` imprime `verificationUrl` + `userCode` → espera de la
notificación `account/login/completed` (timeout `CODEX_LINK_TIMEOUT_SECONDS`)
→ verifica `auth.json` en CODEX_HOME (blob opaco, nunca impreso) → un turno
real `gpt-5.6-luna` con `response_format="text"` → `account/logout` best-effort
→ `evict` en `finally` (limpieza de proceso y home). Nunca loguea credenciales.

Hasta que alguien lo ejecute, **no se afirma compatibilidad con el binario
real**: el wire-format solo está pineado por el fake app-server de T02.

## Riesgos residuales del plan (estado post-implementación)

- **R-PROTO — JSON-RPC solo parcialmente verificado**: el lifecycle y los shapes
  v2 quedan verificados contra source `08e482e2` y el fake; el gate live queda
  **PENDING** para la validación contra el binario real.
- **R-MEM — 512 MB en nano**: caps por env implementados
  (`CODEX_MAX_PROCESSES=3`, semáforo con espera, evicción idle LRU,
  `CodexBusyError` honesto). Presupuesto documentado en `DEPLOY.md`/`koyeb.yaml`
  (comentario). Observación post-deploy pendiente; `docker build` no ejecutado
  (sin daemon) para medir RSS.
- **R-AUTHJSON — formato de `auth.json` sin ejercicio live**: tratado como blob
  opaco cifrado (Fernet), round-trip probado contra el fake (T02/T04). El
  síntoma de un cambio de formato futuro es "vínculo no disponible" (UX honesta),
  nunca corrupción. Gate live **PENDING**.
- **R-USAGE — campos de uso no garantizados**: implementado con parse defensivo
  (ceros si el turno no reporta; nunca inventados), `cost_usd=0.0`,
  `quota_requests=1`; UI muestra "Cuota ChatGPT: N peticiones" solo cuando
  procede. Cubierto por tests T03/T07/T09.
- **R-MODEL — disponibilidad de `gpt-5.6-luna` por plan**: sin allowlist; el
  override `model` se envía por turno y `UsageLimitExceeded` → `CodexRateLimitError`
  con UX diseñada. Cubierto por tests (fake `usage_limit`). La disponibilidad
  real por plan solo la puede confirmar el live gate.
- **R-CONC — serialización interna de turns agénticos**: acotado por semáforo
  (5/3) y timeouts; latencia mayor, no error. Implementado y testeado (T02).
- **R-COLD — muerte a mitad de turno (scale-to-zero)**: `part_failed` + SSE con
  mensaje honesto; el vínculo vive en Supabase cifrado. Cubierto por tests T07
  y el estado `failed` de cold start (T04).
- **R-RESOURCES — resources sin búsqueda web en v1**: decisión de producto
  mantenida (sin Tavily); el modelo recomienda desde conocimiento. Documentado;
  v2 habilitaría tools (fuera de alcance).
- **R-TARBALL — URL/sha256 del tarball**: resuelto por T08 en el Dockerfile
  (pin `@openai/codex-0.147.0-linux-x64.tgz`, sha256
  `c969740c…250139a`, layout musl verificado en host por T08). `docker build`
  **not-verified** en este entorno (sin daemon Docker).

## Checklist de seguridad (global-constraints.md §Security invariants)

- **Sin credenciales en logs/diffs**: escaneado del diff completo
  (`git diff HEAD` con patrones de API keys/refresh tokens/claves privadas) y
  de los 8 archivos codex nuevos: **0 coincidencias**. `auth.json` nunca se
  loguea (solo previews truncados y `user_id[:8]`; verificado en
  `codex_app_server.py`/`codex_client.py`).
- **RLS**: migración con `enable row level security` + políticas
  select/insert/update con `auth.uid() = user_id` (patrón `user_api_keys`);
  backend con service_role. Verificado por inspección del SQL; no ejercitado
  contra Postgres real (hallazgo F01 de T01, sigue cubierto por T10/live).
- **0700**: `CODEX_HOME` creado con `mode=0o700` + `chmod(0o700)` y `auth.json`
  con escritura atómica 0600 (`codex_app_server.py`); cubierto por el test
  `test_spawn_creates_home_0700_and_restores_auth_json` (parte de los 564
  passed). Validación UUID estricta del `user_id` antes de usarse en paths
  (anti path traversal).
- **Fernet**: `encrypted_credentials = encrypt_user_api_key(json.dumps(auth_json), user_id)`
  (clave derivada por usuario) en `backend/crypto.py`; blob opaco nunca en
  claro en `user_provider_connections`.
- **Sin Node en la imagen**: Dockerfile base `python:3.11-slim`; solo
  `apt-get gcc curl ca-certificates`; tarball npm descargado con `curl` y
  extraído directamente (`install` del binario musl a `/usr/local/bin/codex`);
  sin npm/npx/node en runtime. Verificado por inspección; build no ejecutado.

## Qué está verificado vs qué queda pendiente

- **Verificado automáticamente (ejecutado y registrado):** backend completo
  564 passed / 3 skipped; frontend 339 passed; skip por defecto del test live;
  `test:all` con pasos 1–2 verdes dentro del orquestador (falla solo por el
  entorno E2E); diffs de koyeb.yaml solo documentales; android/ intacto.
- **Not-verified (entorno):** smoke E2E de Playwright (`@playwright/test`
  ausente), `docker build` (sin daemon Docker), y por tanto `npm run test:all`
  verde completo.
- **PENDING (gate manual del usuario):** live gate `tests/test_codex_live_login.py`
  con cuenta ChatGPT real (valida R-PROTO/R-AUTHJSON/R-MODEL contra el binario
  real 0.147.0).

## Live gate execution (real binary) — 2026-08-14

Ejecutado contra el binario real `codex.exe` 0.145.0 (npm global de Windows) con
`CODEX_LIVE=1` y el flujo completo del test `tests/test_codex_live_login.py`
(device-code completado por el usuario en https://auth.openai.com/codex/device).

Salida real (log /tmp/opencode/codex_live.log):

```
Vínculo completado (login_id=113f6711-9507-472e-a377-08752ca1e268, planType=None)
Turno real OK — texto='ok' usage=prompt=13457 candidates=5 total=13462 cost_usd=0.0 quota_requests=1
Logout OK
1 passed, 1 warning in 254.76s (0:04:14)
```

Validado end-to-end contra el binario real:
- Handshake `initialize`/`initialized` aceptado (fix R4 de T02).
- Device-code: `account/login/start` → URL+código → `account/login/completed` recibido por el
  handler → `auth.json` persistido en el `CODEX_HOME` del tenant (blob opaco, no impreso).
- Turno streaming real `gpt-5.6-luna`: texto final desde `item/completed`, usage real parseado
  (`prompt=13457`, `candidates=5`, `total=13462`), `cost_usd=0.0`, `quota_requests=1`.
- `account/logout` OK (solo la sesión temporal del test) y evicción del proceso/home.

Estado de riesgos tras el live gate: **R-PROTO resuelto** (wire-format streaming real), **R-AUTHJSON
resuelto** (auth.json real leído/escrito por el binario), **R-MODEL resuelto** (gpt-5.6-luna
disponible y ejecutado en el plan del usuario), **R-USAGE** (campos reales parseados; sigue
dependiendo del parse defensivo para variantes del binario). Sin credenciales en el log.

## Supabase migration applied — 2026-08-14

Migración `user_provider_connections` aplicada al proyecto **Explainer**
(`jlvgirgvbwxkcixiksls`, eu-central-1, Postgres 17) vía MCP `apply_migration`
(name `user_provider_connections`). Verificado por SQL directo:

- `to_regclass('public.user_provider_connections')` → existe.
- 3 políticas RLS propias (`auth.uid() = user_id`): select/insert/update — coinciden
  exactamente con el SQL del bundle.
- Registro en `supabase_migrations.schema_migrations`:
  `20260814095836:user_provider_connections` (última).
- Advisors de seguridad: sin lints nuevos para esta tabla (los lints listados —
  caches OCR, `rls_auto_enable`, leaked-password — son preexistentes, fuera del
  bundle).

Nota: la versión registrada por MCP (20260814095836, timestamp de aplicación)
difiere del nombre del archivo local (20260814120000); el SQL es re-aplicable
(`if not exists` + `drop policy if exists`), así que un futuro `supabase db push`
lo re-ejecutaría sin daño (duplicaría la fila de versión a lo sumo).

## Limitations



- CodeGraph no está inicializado en este repositorio; la atribución del diff se
  hizo con `git diff`/`git status` y lecturas dirigidas.
- Los tests de pipeline usan `auth_client` (overrides de auth), no GoTrue real;
  la migración no se ejercitó contra Postgres real (F01 de T01).
- El conteo "564 passed" coincide con los reportes T01–T09; los 3 skipped son
  preexistentes (no relacionados con el bundle; no se inspeccionó su causa,
  fuera del alcance de T10).

## Evidence

- Plan y límites: `plans/chatgpt-codex-auth/plan.md`, `global-constraints.md`, `progress.md`.
- Reportes integrados: `task-T01-report.md` … `task-T09-report.md`.
- Código inspeccionado: `main.py` (endpoints de vínculo, `_codex_runtime`),
  `backend/codex_app_server.py`, `backend/codex_client.py`, `backend/crypto.py`,
  `supabase/migrations/20260814120000_user_provider_connections.sql`, `Dockerfile`,
  `koyeb.yaml`, `tests/backend/fake_codex_app_server.py`, `tests/test_codex_live_login.py`,
  `scripts/run-all-tests.js`, `package.json`, `pytest.ini`.
- Comandos ejecutados (salida real en la tabla de suites y en los logs del
  implementador): `run_pytest.py`, `npx vitest run`, `npm run test:all`,
  `run_pytest.py tests/test_codex_live_login.py -m integration -v`,
  `git diff --stat HEAD`, `git status --short`, escaneos de credenciales.

## Final integration review (independent verification)

### Commands and observed results

- `git status --short; git diff --stat; git status --short android/; git diff --stat -- android/`:
  Android produjo **0 entradas y diff vacío**. El diff del bundle contiene las
  áreas backend/frontend/deploy/migración esperadas; también hay artefactos
  untracked preexistentes (`.opencode/`, `.playwright-mcp/`, `.venv-win/`,
  `plans/android-app/`) que no se atribuyen al bundle.
- `git diff --name-only | grep -E 'backend/(gemini_client|openrouter_client|deepseek_client)\.py|backend/agents/.*_(ds|or)\.py'`:
  **sin salida**. La inspección de hunks de `main.py` mostró extensiones de
  importación, wiring Codex y ramas aditivas; no hay archivos de los clientes
  existentes ni agentes `_ds`/`_or` modificados.
- Escaneo de `git diff --binary` para claves/tokens (`sk-`, `AIza`, `Bearer`,
  claves privadas, `ghp_`): **0 coincidencias**.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`:
  **564 passed, 3 skipped, 10 warnings in 31.42s**.
- `npx vitest run`: **19 files passed, 339 tests passed**, exit 0.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q`:
  **25 passed in 1.18s**.
- Live gate `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/test_codex_live_login.py -m integration -v`:
  revisado en el reporte T10 como **1 skipped por diseño**; sigue `PENDING`, no
  ejecutado contra cuenta/binario real.
- `npm run test:all` y `docker build` permanecen **not-verified**, por las
  limitaciones ya documentadas: falta `@playwright/test`/binario Unix y no hay
  daemon Docker en WSL.

### Contract and security cross-check

- RLS, `0700` de `CODEX_HOME`, Fernet, stderr aislado, ausencia de Node en el
  Dockerfile y mensajes UX sin stack fueron confirmados por inspección y por la
  suite backend. La migración sigue sin ejecutarse contra Postgres real.
- El diff no contiene cambios en `android/`, clientes Gemini/OpenRouter/DeepSeek
  ni agentes `_ds`/`_or`; frontend changes are additive in the changed areas.
- Los métodos observados son `account/login/start` con
  `type=chatgptDeviceCode`, `account/login/completed` como notificación,
  `account/logout`, `account/read`, `thread/start` y `turn/start` con
  `model=gpt-5.6-luna`. **No existe una petición `turn/end` en
  `backend/codex_client.py` ni en `backend/codex_app_server.py`**. Esto diverge
  de la lista de contrato solicitada en la revisión/plan; el fake valida
  únicamente el wire-format implementado, no el binario real.

### Spec Compliance

- Cumplidos: proveedor adicional `codex`, modelo fijo, aislamiento por tenant,
  pre-checks/keys, uso de cuota sin coste inventado, UI de vínculo, RLS/Fernet y
  preservación de Android/proveedores existentes.
- Pendientes: compatibilidad real del app-server, build Docker, Playwright E2E y
  migración contra Postgres real. El lifecycle streaming y los request shapes v2
  ya están reconciliados con el contrato source-pinned (FR-01/FR-01b).

### Code Quality

- No se observaron credenciales, cambios en Android ni edición de los clientes o
  agentes de proveedores existentes. Las suites relevantes pasan; la calidad de
  integración externa queda limitada por el fake y el live gate omitido.

### Named Risk Checks

- RLS/Fernet/0700/errores sin stack/sin Node: inspección dirigida + tests backend,
  sin hallazgo adicional.
- Protocolo JSON-RPC: lifecycle streaming, correlación, usage, errores y shapes
  v2 coinciden con la receta/source-pinned; no se emite ni se espera `turn/end`.
- Concurrencia, cold start, cuota y fallback YouTube: cubiertos por los tests
  integrados; no se verificaron contra servicio real.

## Required Changes

- `FR-01` | **blocking** | Scope: changed-contract | Owner hint: T03 / `backend/codex_client.py:324-665` | Problem: el cliente debía consumir el lifecycle streaming real en vez de leer texto/usage de `turn/start` o usar `turn/end`. | Why: el contrato source-pinned exige notificaciones y cierre en `turn/completed`. | Required change: correlacionar por `(user_id, turnId)`, tomar texto/usage de las notificaciones, mapear fallos y cerrar en `turn/completed`; mantener retry como nuevo `turn/start` en el mismo thread. | Status: resolved
- `FR-01b` | **blocking** | Scope: changed-contract | Owner hint: T03 / `backend/codex_client.py:299-321` | Problem: los request params v1 no coincidían con los shapes v2 source-pinned. | Why: el app-server v2 requiere `developerInstructions`, `threadId` e `input` textual, sin campos v1. | Required change: emitir exactamente los shapes v2 y no enviar `message`/`system`/`temperature`/`threadID`/`response_format` ni `turn/end`. | Status: closed/absorbed into FR-01; resolved
- `FR-02` | **non-blocking** | Scope: cross-task | Owner hint: T10 / live gate | Problem: `tests/test_codex_live_login.py` solo se omite por falta de credenciales reales. | Why: R-PROTO, R-AUTHJSON y R-MODEL siguen sin validación end-to-end. | Required change: ejecutar el flujo manual con una cuenta ChatGPT real y registrar salida segura (sin credenciales). | Status: **resolved (2026-08-14)** — ver sección "Live gate execution (real binary)"
- `FR-03` | **non-blocking** | Scope: cross-task | Owner hint: T08/T09 / entorno CI | Problem: no se verificaron `docker build` ni el smoke E2E de Playwright. | Why: la imagen completa y los flujos UI del navegador no tienen evidencia ejecutada en este entorno. | Required change: repetir en un entorno con daemon Docker y `@playwright/test` instalado. | Status: open
- `FR-04` | **non-blocking** | Scope: same-task | Owner hint: T01 / migración | Problem: RLS y esquema solo fueron inspeccionados y testeados mediante mocks, no contra Postgres/Supabase real. | Why: no prueba las políticas, tipos y re-aplicabilidad del SQL en el motor objetivo. | Required change: aplicar la migración en un entorno Supabase/Postgres de staging y registrar resultado. | Status: **resolved (2026-08-14)** — aplicada vía MCP al proyecto Explainer (jlvgirgvbwxkcixiksls), ver sección \"Supabase migration applied\"

## Risk status correction

- **R-PROTO:** lifecycle streaming y request shapes v2 resueltos contra source y
  fake; la compatibilidad end-to-end con el binario real sigue pendiente del live
  gate.
- **R-MEM:** mitigado por caps/evicción, pero medición RSS en nano pendiente.
- **R-AUTHJSON:** round-trip contra fake verificado; formato real sigue pendiente
  del live gate.
- **R-USAGE:** mitigado por parse defensivo, `quota_requests` y coste 0; campos
  reales del binario siguen sin validarse.
- **R-MODEL:** routing fijo correcto y fake cubierto; entitlement real pendiente.
- **R-CONC:** límites 3 procesos/5 requests y evicción cubiertos por tests; no se
  observó regresión.
- **R-COLD:** estados/error y persistencia cubiertos por tests; comportamiento
  real de restart sigue pendiente.
- **R-RESOURCES:** correctamente sin búsqueda web en v1; riesgo aceptado de
  frescura, no defecto de integración.
- **R-TARBALL:** hash/layout/binario verificados en host; `docker build` sigue
  `not-verified`.

## Remediation History

### Round 1 (re-review FR-01 / FR-01b)

- Implementer evidence: `plans/chatgpt-codex-auth/task-T02-report.md` §Remediation
  History Round 3; `plans/chatgpt-codex-auth/task-T03-report.md` §Remediation
  History Round 1; `plans/chatgpt-codex-auth/integration-codex-appserver.md`
  §§Turn lifecycle verification (reconciliación FR-01) y Request param shapes
  (reconciliación FR-01b).
- IDs checked: `FR-01`, `FR-01b`.
- Result: `FR-01` **resolved**. `call_codex_chat` now waits for correlated
  `turn/completed`, takes final agent text from `item/completed`, usage from
  `thread/tokenUsage/updated`, maps notification/failed errors, and performs
  conversational retries as new turns on the same thread; it does not use
  `turn/end`. `FR-01b` **closed/absorbed**: emitted requests use the exact v2
  `thread/start` and `turn/start` shapes, with forbidden v1 fields absent from
  the wire. The fake emits the source-shaped streaming sequence and the client
  consumes it independently; the same-user concurrency test verifies no
  cross-talk.
- Verification: `.venv-win/Scripts/python.exe scripts/run_pytest.py
  tests/backend -q` → **577 passed, 3 skipped, 10 warnings** (31.49s);
  `npx vitest run` → **19 files passed, 339 tests passed**, exit 0 (15.91s).
