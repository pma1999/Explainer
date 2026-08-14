# Progress: Proveedor Codex — vinculación OAuth ChatGPT y app-server

Planning: engine=opencode | model=opencode-go/deepseek-v4-pro | effort=max
Baseline: 4a1f794 (git rev-parse HEAD, 2026-08-14) — Pre-existing: untracked .opencode/, .playwright-mcp/, plans/android-app/
Bundle owner: implementation-planner
Bundle status: APROBADO por el usuario (2026-08-14) — implementación en curso
Orchestrated scope: backend + frontend web + despliegue; 10 tareas en 6 olas; `android/` intacto

Waves:

| Wave | Tasks | Mode |
|---|---|---|
| 0 | T01 | sequential (tabla/almacenamiento = contrato de datos común) |
| 1 | T02, T08 | parallel (gestor de procesos vs despliegue; archivos disjuntos) |
| 2 | T03, T04 | parallel (cliente+routing vs endpoints; consumen API congelada de T02) |
| 3 | T05, T06 | parallel (agentes núcleo vs familia; archivos disjuntos) |
| 4 | T07, T09 | parallel (wiring main.py vs frontend; contratos congelados) |
| 5 | T10 | sequential (integración + final review) |

Decision ledger:

| Date | Decision | Evidence | Implementation owner |
|---|---|---|---|
| 2026-08-14 | Plan aprobado por el usuario (web-only, device-code, gpt-5.6-luna, 1 proceso app-server por tenant, tabla cifrada user_provider_connections) | question tool | orquestador |
| 2026-08-14 | T08: koyeb.yaml cambia SOLO en comentario documental (nano/512MB/scale-to-zero/healthz/max 1 intactos); excepción reportada, no aplicada en silencio | diff koyeb.yaml vs 4a1f794 + final-review.md §Alcance | implementer-T08 |
| 2026-08-14 | T10: `npm run test:all` no certificable verde en este entorno: `python` fuera del PATH de npm (venv .venv-win/ solo tiene python.exe) y `@playwright/test` no instalado (smoke E2E preexistente nunca ejecutable aquí). No es relajación de contrato; se registra como limitación de entorno en final-review.md | salida real de test:all + `node playwright/cli.js test --list` | implementer-T10 |
| 2026-08-14 | T10: live gate (`tests/test_codex_live_login.py`) queda PENDING: requiere cuenta ChatGPT real del usuario; skip por defecto (CODEX_LIVE=1, marker integration) | final-review.md §Live gate | implementer-T10 |
| 2026-08-14 | FR-01 changed-contract: flujo de turno streaming por notificaciones (turn/completed + item/completed + thread/tokenUsage/updated), validado en source (commit 08e482e2 / rust-v0.147.0-alpha.9); briefs T02/T03 enmendados (y T10/global-constraints/plan.md con la reconciliación; sin API nueva en el manager: correlación por turnId con futures en el cliente). Escenario `usage_limit` del fake = notificación error + turn/completed failed; `scripted_error` = error de aceptación en response. Los parámetros del request (message/system/threadID vs input/threadId v2) quedan FUERA de FR-01, pendientes del live gate (named risk T03). T02/T03 pendientes de re-implementación y re-verificación | integration-codex-appserver.md §Turn lifecycle verification + final-review.md FR-01 | implementation-planner |

| Task | Status | Implementer | Owner | Brief | Report | Review | Notes |
|---|---|---|---|---|---|---|---|
| T01 | done | task-implementer-bdd | implementer-T01 (sesión cerrada) | task-T01-brief.md | task-T01-report.md | APPROVE_WITH_FINDINGS (F01 non-blocking: re-aplicación de migración no ejercitada vs Postgres real → se cubre en T10/live) | Migración + almacenamiento del vínculo (17 tests nuevos, 465 suite verde) |
| T02 | done | task-implementer-bdd | implementer-T02 (R1 cerrada) | task-T02-brief.md | task-T02-report.md | APPROVE (F01 resuelto; 20 tests T02, 485 backend) | CodexAppServerManager + fake app-server. **BRIEF ENMENDADO (FR-01): fake streaming — re-implementación pendiente** |
| T03 | done | task-implementer-bdd | implementer-T03 (sesión cerrada) | task-T03-brief.md | task-T03-report.md | APPROVE (sin findings; 13 tests, suites codex 33) | Cliente tipado + routing de modelos. **BRIEF ENMENDADO (FR-01): cliente por notificaciones turnId — re-implementación pendiente** |
| T04 | done | task-implementer-bdd | implementer-T04 (R1 cerrada) | task-T04-brief.md | task-T04-report.md | APPROVE (RC-01 resuelto; 14 tests T04, 512 backend) | Endpoints device-code + lifespan shutdown |
| T05 | done | task-implementer-bdd | implementer-T05 (R1 cerrada) | task-T05-brief.md | task-T05-report.md | APPROVE (RC-01 resuelto; 11 tests T05, 564 backend) | Agentes codex núcleo |
| T06 | done | task-implementer-bdd | implementer-T06 (sesión cerrada) | task-T06-brief.md | task-T06-report.md | skipped-not-needed | Agentes codex familia (12 tests; resumen formatter ampliado en R1 de T07) |
| T07 | done | task-implementer-bdd | implementer-T07 (R1 cerrada) | task-T07-brief.md | task-T07-report.md | APPROVE (RC-01 resuelto; 25 tests pipeline, 564 backend) | Wiring del pipeline + review/reformat + usage |
| T08 | done | task-implementer-bdd | implementer-T08 (sesión cerrada) | task-T08-brief.md | task-T08-report.md | skipped-not-needed | Dockerfile pineado sin Node + koyeb + DEPLOY.md (docker build not-verified: sin daemon en entorno; secuencia RUN verificada en host, codex 0.147.0 OK) |
| T09 | done | task-implementer-bdd | implementer-T09 (sesión cerrada) | task-T09-brief.md | task-T09-report.md | skipped-not-needed | Frontend: card, panel, vínculo, validación, uso (339 tests vitest, 38+ nuevos; e2e not-runnable en entorno) |
| T10 | done | task-implementer-bdd | implementer-T10 (sesión cerrada) | task-T10-brief.md | task-T10-report.md | skipped-not-needed (produce final-review.md) | Verificación integrada: 564 backend + 339 frontend; test live (skip por defecto); final-review.md; live gate PENDING (cuenta ChatGPT del usuario); test:all y docker build not-verified por entorno. **BRIEF ENMENDADO (FR-01): re-verificación post-streaming pendiente** |

Final review: done - plans/chatgpt-codex-auth/final-review.md — PASS WITH REQUIRED CHANGES (2026-08-14, tras re-review FR-01/FR-01b): FR-01 y FR-01b RESUELTOS (cliente streaming v2 source-pinned, 577 backend + 339 frontend verdes, verificados por el orquestador). FR-02 (live gate): **RESUELTO 2026-08-14** — ejecutado contra codex.exe real 0.145.0 (1 passed; device-code completado por el usuario; turno gpt-5.6-luna OK; R-PROTO/R-AUTHJSON/R-MODEL cerrados). FR-04 (migración vs Supabase real): **RESUELTO 2026-08-14** — aplicada vía MCP (proyecto Explainer jlvgirgvbwxkcixiksls; tabla + 3 políticas RLS verificadas por SQL). FR-03 (docker build + e2e playwright: requiere entorno): abierto non-blocking.

Input ledger:

| Artifact | Owner | Status | Scope |
|---|---|---|---|
| context-map.md | codebase-explorer (sesión previa) | done | repo/auth/selector/pipeline/BYOK/deploy/tests |
| integration-codex-appserver.md | integration-researcher (sesión previa) | done | contrato app-server: pin 0.147.0, stdio, device-code, gpt-5.6-luna |
| plan bundle | implementation-planner | done | plan.md + global-constraints.md + 10 briefs; pendiente de aprobación |
