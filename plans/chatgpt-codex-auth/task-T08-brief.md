# Task T08: Despliegue — binario codex pineado sin Node + impacto Koyeb + DEPLOY.md

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Instalar el binario standalone de Codex pineado en el Dockerfile (sin Node), documentar el
impacto en `koyeb.yaml` (nano 512MB, scale-to-zero) y dejar `DEPLOY.md` con el procedimiento de
actualización y diagnóstico.

## Acceptance Criteria
- `Dockerfile` (base `python:3.11-slim` intacta): añade `curl ca-certificates` al
  `apt-get install`; descarga el tarball de `@openai/codex-linux-x64@0.147.0` desde
  `https://registry.npmjs.org/@openai/codex-linux-x64/-/codex-linux-x64-0.147.0.tgz` con
  verificación de **sha256 pineado** (registrar el hash real obtenido en un comentario del
  Dockerfile y en DEPLOY.md); extrae el binario (inspeccionar layout con `tar tzf`; ruta típica
  `package/...`) a `/usr/local/bin/codex` con `chmod +x`; NO instala Node, npm ni Rust.
- La imagen construida verifica `codex --version` (puede ser un `RUN` del build para fallar
  temprano si el binario no ejecuta en musl).
- `koyeb.yaml`: **sin cambios funcionales** (nano, 512MB, scale-to-zero, healthcheck `/healthz`,
  max 1). Se añade únicamente un bloque de comentarios documentando: presupuesto de memoria
  (Python ~200 MB + hasta `CODEX_MAX_PROCESSES=3` × app-server), los env de ajuste
  `CODEX_*`, y que el vínculo sobrevive a cold starts porque vive en Supabase. Cualquier cambio
  funcional necesario se reporta como excepción en el report, no se aplica en silencio.
- `DEPLOY.md`: sección nueva "Proveedor Codex / ChatGPT" con: procedimiento de actualización del
  binario (bump de versión → re-descargar tarball → actualizar sha256 → rebuild + `codex
  --version`), lista de env `CODEX_*` con defaults, tabla de presupuesto de memoria, ubicación
  del log del app-server (`/tmp/codex/<user_id>/app-server.stderr.log`) y comportamiento
  esperado en scale-to-zero (procesos efímeros, vínculo persistente en Supabase, evicción idle).
- Evidencia en el report: si Docker está disponible en el entorno, ejecutar
  `docker build -t explainer-codex-test .` y
  `docker run --rm explainer-codex-test codex --version` y reportar salida real; si no está
  disponible, registrarlo explícitamente como **not-verified** con las instrucciones exactas
  (sin afirmar que funciona).

## Scope
Touch:
- `Dockerfile`
- `koyeb.yaml` (solo comentarios documentales)
- `DEPLOY.md` (sección nueva)

Do not touch:
- Código Python, `frontend/`, `supabase/`, `android/`, `requirements.txt`

## Constraints
- Solo los invariantes de `global-constraints.md` → "Container runtime and binary".
- Pin exacto `@openai/codex-linux-x64@0.147.0`; no usar `install.sh`, `latest` ni npm/npx en
  runtime. El hash sha256 debe quedar escrito literalmente en el Dockerfile (verificable en diff).

## Interfaces
Consumes:
- Receta: `plans/chatgpt-codex-auth/integration-codex-appserver.md` (§Chosen Approach, §Minimal
  Working Snippet, §Verification Status: dist-tags VERIFIED).

Produces:
- Imagen con `/usr/local/bin/codex` (env `CODEX_BIN_PATH` por defecto, usado por T02).

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `Dockerfile` | base + apt + CMD | completo | Punto de inserción |
| `koyeb.yaml` | scaling/health/instance | completo | Documentar impacto sin romper |
| `DEPLOY.md` | sección Koyeb | 116-228 | Estilo y dónde añadir |
| `plans/chatgpt-codex-auth/integration-codex-appserver.md` | install/pinning | §Chosen, §Snippet, §Verification | Fuente del pin |

## Existing Patterns To Reuse
- Estilo minimalista del Dockerfile actual (una capa apt, sin imágenes extra).

## Tests
- `docker build -t explainer-codex-test . && docker run --rm explainer-codex-test codex --version`
  (si Docker disponible). Además `docker run --rm explainer-codex-test python -c "import main"`
  opcional como smoke de imagen. Reportar exactamente qué se ejecutó y su salida.

## Implementer
task-implementer-bdd

## Task Review
Required: no
Why: cambio de infraestructura verificable por build; la evidencia queda en el report y se
revisa en final review.

## Named Risks
- R-TARBALL: si el tarball npm no contiene el binario en el layout esperado, caer al asset
  standalone de GitHub Releases (builds musl de la receta) y registrar la decisión con su URL y
  sha256; no desviarse sin documentarlo.
- Red necesaria en el build para descargar/verificar el hash la primera vez.

## Report Path
`plans/chatgpt-codex-auth/task-T08-report.md`
