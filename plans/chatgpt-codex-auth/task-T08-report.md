# Task T08 Report

## Status
DONE_WITH_CONCERNS

## Outcome
El `Dockerfile` (base `python:3.11-slim` intacta, sin Node/npm/Rust) instala el binario
standalone `codex` pineado a `0.147.0-linux-x64` en `/usr/local/bin/codex` (build musl estático,
`file`: `ELF 64-bit LSB pie executable, x86-64, static-pie linked`), con verificación de **sha256
literal** del tarball (`c969740cf8297e4c31905cd551efeb2c99af5080c12c236bdf825598b250139a`,
escrito en el Dockerfile y en DEPLOY.md) y `codex --version` como `RUN` del build para fallar
temprano si el binario no ejecuta. `koyeb.yaml` queda **sin cambios funcionales** (solo bloque de
comentarios documental: presupuesto de memoria, env `CODEX_*`, supervivencia del vínculo en cold
starts vía Supabase — parseo YAML verificado: nano/512MB/min 0/max 1/healthcheck `/healthz`
intactos). `DEPLOY.md` gana la sección "Proveedor Codex / ChatGPT" (procedimiento de bump del
binario con re-descarga + sha256 + rebuild, tabla de env `CODEX_*` con defaults, tabla de
presupuesto de memoria, log del app-server en `/tmp/codex/<user_id>/app-server.stderr.log` y
comportamiento scale-to-zero).

**Desviación documentada (URL del tarball, ver Decisions):** la URL del brief
(`https://registry.npmjs.org/@openai/codex-linux-x64/-/codex-linux-x64-0.147.0.tgz`) devuelve
**404** porque `@openai/codex-linux-x64` **no es un paquete publicado**: es un alias npm
(`optionalDependencies` de `@openai/codex@0.147.0` → `npm:@openai/codex@0.147.0-linux-x64`,
verificado contra el metadata del registry). El tarball real del mismo pin exacto es
`https://registry.npmjs.org/@openai/codex/-/codex-0.147.0-linux-x64.tgz`, que sí contiene el
binario (layout `package/vendor/x86_64-unknown-linux-musl/bin/codex`, inspeccionado con
`tar tzvf`). No se activó R-TARBALL (fallback a GitHub Releases) porque el tarball npm **sí**
contiene el binario en el layout esperado (`package/...`); la corrección de URL queda registrada
en el comentario del Dockerfile, en DEPLOY.md y en este reporte.

## Acceptance Criteria
- Dockerfile base `python:3.11-slim` intacta; `curl ca-certificates` añadidos al `apt-get
  install` -> pass (diff; una sola capa apt, estilo previo).
- Descarga desde registry.npmjs.org con **sha256 pineado literal** (comentario + `echo ... |
  sha256sum -c -`) -> pass (hash real obtenido y escrito literalmente; la URL concreta difiere de
  la del brief por el alias npm, ver Decisions; `sha256sum -c` ejecutado en host: `OK`).
- Layout inspeccionado con `tar tzf` y binario extraído a `/usr/local/bin/codex` con
  `chmod +x` (`install -m 0755`) -> pass (layout real:
  `package/vendor/x86_64-unknown-linux-musl/bin/codex`; extracción + install ejecutados en host
  con los mismos comandos).
- NO instala Node, npm ni Rust -> pass (sin `nodejs`, sin `npm`, sin `rust` en el Dockerfile).
- La imagen construida verifica `codex --version` (RUN del build, fallo temprano) -> **parcial**
  (`RUN codex --version` añadido como paso del build; el build no pudo ejecutarse, ver Tests —
  Docker no disponible).
- `koyeb.yaml` sin cambios funcionales; solo bloque de comentarios con presupuesto de memoria
  (Python ~200 MB + hasta `CODEX_MAX_PROCESSES=3` × app-server), env `CODEX_*`, vínculo que
  sobrevive cold starts vía Supabase -> pass (`yaml.safe_load` OK; `name/type/scaling
  (min:0,max:1)/healthcheck /healthz/instance_types [nano]/env [3]` idénticos al baseline;
  ninguna clave funcional añadida, modificada ni borrada).
- `DEPLOY.md` sección nueva "Proveedor Codex / ChatGPT" con: procedimiento de actualización
  (bump → re-descarga → sha256 → rebuild + `codex --version`), lista de env `CODEX_*` con
  defaults, tabla de presupuesto de memoria, log del app-server
  (`/tmp/codex/<user_id>/app-server.stderr.log`) y comportamiento scale-to-zero (procesos
  efímeros, vínculo persistente en Supabase, evicción idle) -> pass.
- Evidencia en el report: si Docker disponible, `docker build` + `docker run ... codex --version`;
  si no, **not-verified** explícito -> **not-verified** (Docker no disponible; instrucciones
  exactas en Tests).
- No tocar lo prohibido (código Python, `frontend/`, `supabase/`, `android/`,
  `requirements.txt`) -> pass (`git status`: solo `Dockerfile`, `koyeb.yaml`, `DEPLOY.md` de mi
  sesión; `backend/supabase_data.py` ya estaba modificado antes del baseline de la tarea).

## Files Changed
- `Dockerfile` - modified; `curl ca-certificates` al apt-get + capa nueva de instalación del
  binario codex pineado (descarga con curl, sha256 literal verificado, extracción del miembro
  `package/vendor/x86_64-unknown-linux-musl/bin/codex`, `install -m 0755` a
  `/usr/local/bin/codex`, `codex --version` al final del RUN). 20 líneas añadidas.
- `koyeb.yaml` - modified; solo comentarios documentales (14 líneas) sobre el impacto del
  proveedor Codex: presupuesto de memoria, env `CODEX_*` de ajuste y supervivencia del vínculo
  en cold starts. Cero cambios funcionales.
- `DEPLOY.md` - modified; sección nueva "Proveedor Codex / ChatGPT" insertada entre el
  despliegue Koyeb y el de Vercel (96 líneas).

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `Dockerfile` | build stage de instalación de codex (RUN) | Nueva: curl + sha256 pinned + extracción + install + verificación `codex --version`; expone `/usr/local/bin/codex` (consumido vía env `CODEX_BIN_PATH` por T02) |
| `Dockerfile` | apt-get install | Extendido: `+curl ca-certificates` (misma capa) |
| `koyeb.yaml` | (sin símbolos funcionales) | Solo comentario documental; contrato nano/512MB/scale-to-zero/`/healthz`/max 1 intacto |
| `DEPLOY.md` | sección "Proveedor Codex / ChatGPT" | Nueva: bump del binario, env `CODEX_*`, presupuesto de memoria, log del app-server, scale-to-zero |

## Tests
- Docker **no disponible** en el entorno (WSL2 sin Docker Desktop integration: `docker --version`
  → "The command 'docker' could not be found"; `docker info` → daemon no accesible). Por tanto
  **not-verified** el build y el run reales. Instrucciones exactas para verificar (idénticas a
  las del brief):
  ```
  docker build -t explainer-codex-test .
  docker run --rm explainer-codex-test codex --version
  # esperado: codex-cli 0.147.0  (el RUN del build ya falla temprano si no)
  # smoke opcional: docker run --rm explainer-codex-test python -c "import main"
  ```
- Sustituto observado (host Linux x86_64, mismos comandos del RUN sin la capa apt): `curl`
  del tarball OK; `sha256sum -c` → `/tmp/opencode/codex.tgz: OK`; `tar -xzf` del miembro
  `package/vendor/x86_64-unknown-linux-musl/bin/codex` OK; `install -m 0755` OK; ejecución del
  binario: `codex-cli 0.147.0`, exit 0 (stderr: warning benigno de PATH aliases solo porque el
  HOME de prueba era `/tmp`; con `HOME=/root` en el contenedor no aplica).
- `yaml.safe_load(koyeb.yaml)` OK y valores funcionales idénticos al baseline (ver AC).
- `git diff` revisado: solo los 3 archivos del scope.

## TDD Evidence
- No aplica escenario BDD de aceptación: tarea de infraestructura sin harness de tests del repo;
  el "test" es el propio build de imagen (no ejecutable aquí) y la secuencia RUN que se
  reprodujo en host.
- RED: no procede (no existe fase roja previa; el cambio es aditivo y la verificación es el
  `RUN codex --version` del build, que fallaría el build si el binario no ejecutara).
- GREEN (host): la secuencia exacta del RUN (curl → sha256 `OK` → extraer → install → ejecutar)
  pasa y `codex --version` imprime `codex-cli 0.147.0` (exit 0). El `RUN` del Dockerfile incluye
  la misma verificación para fallar temprano en CI/Koyeb.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T08-brief.md` - brief completo.
- `plans/chatgpt-codex-auth/global-constraints.md` - §Container runtime and binary (y resto del
  documento para env `CODEX_*`, `CODEX_HOME`, log path).
- `Dockerfile` - punto de inserción (completo).
- `koyeb.yaml` - completo (impacto documental).
- `DEPLOY.md` - sección Koyeb y estilo (116-228 y colindantes).
- `plans/chatgpt-codex-auth/integration-codex-appserver.md` - §Chosen Approach, §Minimal Working
  Snippet, §Setup, §Verification Status (pin 0.147.0, dist-tags, builds musl).
- `plans/chatgpt-codex-auth/task-T01-report.md` - formato del reporte del bundle.

Extra reads:
- `https://registry.npmjs.org/@openai/codex` (metadata, vía curl) - la URL del brief dio 404;
  necesidad de resolver el tarball real y el hash (dist-tags y optionalDependencies muestran que
  `@openai/codex-linux-x64` es alias de `@openai/codex@0.147.0-linux-x64`).
- tarball descargado + `tar tzvf` - layout real y sha256 (R-TARBALL).
- `file` + ejecución del binario extraído en host - confirmar que es musl estático y que ejecuta
  (verificación de la premisa del RUN).

Pack gaps:
- None.

## Decisions
- **URL del tarball corregida (desviación del brief, registrada):** la URL del brief da 404;
  `@openai/codex-linux-x64` es un alias npm, no un paquete publicado. Se usa el tarball real del
  mismo pin exacto en el mismo registry:
  `https://registry.npmjs.org/@openai/codex/-/codex-0.147.0-linux-x64.tgz`. Sigue cumpliendo el
  invariante de global-constraints ("tarball de @openai/codex-linux-x64@0.147.0 desde
  registry.npmjs.org, sha256 pineado"): mismo contenido, mismo registry, misma versión. R-TARBALL
  **no** se activa porque el tarball npm contiene el binario (layout
  `package/vendor/x86_64-unknown-linux-musl/bin/codex`). Queda documentado en comentario del
  Dockerfile, DEPLOY.md y este reporte.
- **Extracción por miembro único** (`tar -xzf ... package/vendor/.../codex`) en lugar de extraer
  todo el tarball: evita copiar ~300 MB innecesarios (bwrap, rg, zsh, code-mode-host) a la capa
  final; la capa solo contiene el binario de 258 MB.
- **`RUN codex --version` al final de la misma capa**: fallo temprano del build si el binario no
  ejecuta (AC explícito); no añade capa extra y el binario musl estático no necesita runtime
  adicional (verificado en host con `file` y ejecución).
- **Presupuesto de memoria documentado como estimación, no medición**: los ~80-150 MB RSS por
  app-server son una estimación razonada (binario Rust de 258 MB, procesos stdio idle); la
  verificación real de pico en nano 512MB queda como follow-up de despliegue (T10/live), y el
  texto de koyeb.yaml/DEPLOY.md indica explícitamente bajar `CODEX_MAX_PROCESSES` si hay OOM.
- **Sin fallback a GitHub Releases**: descartado porque la premisa de R-TARBALL (tarball npm sin
  el binario) no se cumple; añadir el asset de GitHub habría duplicado fuentes de verdad sin
  necesidad.

## Concerns / Follow-ups
- **Docker no disponible**: `docker build` y `docker run ... codex --version` quedan
  **not-verified** (instrucciones exactas en Tests). La secuencia RUN se verificó en host al
  detalle, pero el build completo (apt + pip + capas) no se ejecutó; conviene un build real
  antes del despliegue (T10).
- Presupuesto de memoria sin medir en nano 512MB (ver Decisions); validar RSS real del
  app-server en live.
- Los untracked `.opencode/`, `.playwright-mcp/`, `.venv-win/`, `plans/android-app/` y la
  modificación previa de `backend/supabase_data.py` (T01) no se tocaron.

## Remediation History
None for the initial implementation.
