# Task T10: Verificación integrada end-to-end y evidencia final (ENMENDADO — FR-01)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Ejecutar la verificación integrada completa sobre el árbol con todas las piezas cableadas
(incluida la re-implementación STREAMING de T02/T03 del amendo FR-01), añadir el test live de
vinculación (skip por defecto), y producir `final-review.md` con la evidencia y los pendientes
explícitos, incluyendo el cierre de FR-01.

## Acceptance Criteria
- `python scripts/run_pytest.py` completo en verde (backend, incluye los tests de T01-T07 con el
  fake app-server vía `CODEX_BIN_PATH` y los tests de streaming de T02/T03).
- `npx vitest run` en verde (frontend, incluye T09).
- `npm run test:all` en verde (conjunto orquestado backend+frontend+playwright smoke existente).
- `tests/test_codex_live_login.py` (marker `integration`, skip por defecto): start real →
  instrucciones para completar el device code manualmente → poll status linked (esperando la
  notificación `account/login/completed`) → un turno real `gpt-5.6-luna` ejecutado vía
  `call_codex_chat` — lo que ejercita contra el binario real el **ciclo de turno streaming**
  reconciliado en FR-01 (`turn/start` responde solo el turno; el texto llega por
  `item/completed` agentMessage, el usage por `thread/tokenUsage/updated` y la terminación por
  `turn/completed`; sin `turn/end`/`turn/poll`) → logout. Documenta en docstring que requiere
  acción humana y credenciales reales de ChatGPT. Si el turno real revela una divergencia de
  wire-format (p. ej. en los parámetros del request), se registra como hallazgo, NO se corrige
  en silencio.
- `final-review.md` en `plans/chatgpt-codex-auth/` con: resumen del scope real (diff por área
  backend/frontend/deploy/supabase, confirmando `android/` intacto), resultados de las suites
  ejecutadas (comando + salida real), **cierre de FR-01** (contrato reconciliado con source
  `08e482e2`/`rust-v0.147.0-alpha.9`; briefs T02/T03 re-implementados al streaming; suites
  verdes; live gate ejecutado o PENDING), estado del live gate (ejecutado con evidencia o
  **PENDING — requiere cuenta ChatGPT del usuario**), riesgos residuales del plan revisados
  (R-PROTO, R-MEM, R-AUTHJSON, R-USAGE, R-MODEL, R-CONC, R-COLD, R-RESOURCES, R-TARBALL) con su
  estado tras la implementación, y checklist de seguridad (sin credenciales en logs/diffs, RLS,
  0700, cifrado Fernet, sin Node en la imagen).
- `progress.md` actualizado: estados por tarea (T02/T03 re-implementadas tras el amendo),
  decision ledger con cualquier relajación de contrato autorizada y la fila de final review.

## Scope
Touch:
- `tests/test_codex_live_login.py` (nuevo)
- `plans/chatgpt-codex-auth/final-review.md` (actualización post-amendo)
- `plans/chatgpt-codex-auth/progress.md` (actualización)

Do not touch:
- Código de producción salvo correcciones de defectos encontrados por las suites; toda
  corrección se documenta en final-review.md con el test que la cubre.

## Constraints
- Reportar solo lo observado: distinguir "ejecutado, salida X" de "not verified" en cada
  bloque de evidencia (política de reporting del repo).
- No afirmar compatibilidad con el binario real si el live gate no se ejecutó.
- El cierre de FR-01 exige: suites verdes con el cliente streaming + (live gate ejecutado con
  éxito O PENDING explícito con el contrato reconciliado por source como evidencia).

## Interfaces
Consumes:
- Todo el bundle: contratos T01-T09 verificables desde las suites; fake streaming de T02
  (`scripted_turn`/`usage_limit`/`stalled_turn`) y cliente streaming de T03.
- `plans/chatgpt-codex-auth/integration-codex-appserver.md` §Turn lifecycle verification como
  evidencia autoritativa del contrato reconciliado.
- `plans/chatgpt-codex-auth/global-constraints.md` como checklist de seguridad.

Produces:
- `final-review.md` + `progress.md` finales.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `pytest.ini`, `scripts/run_pytest.py` | runner y markers | completo | Ejecución correcta |
| `tests/backend/conftest.py` | fixtures `client`/`auth_client` | completo | Base de los tests integrados |
| `package.json` | `test:all` | scripts | Comando orquestado |
| `plans/chatgpt-codex-auth/plan.md` | riesgos R-* | Named risks | Revisión de residuales |
| `plans/chatgpt-codex-auth/global-constraints.md` | Security invariants; Codex client and errors | secciones | Checklist final + contrato streaming |
| `plans/chatgpt-codex-auth/integration-codex-appserver.md` | Turn lifecycle verification | sección | Evidencia de reconciliación FR-01 |

## Existing Patterns To Reuse
- `plans/android-app/final-review.md` como formato de referencia (claims, evidencia ejecutada,
  items pendientes explícitos).

## Tests
- Los comandos de las Acceptance Criteria son la verificación; registrar salida real de cada uno.

## Implementer
task-implementer-bdd

## Task Review
Required: no
Why: la propia tarea produce la final review, que el orquestador/usuario aprueba.

## Named Risks
- Si una suite revela un defecto transversal, corregirlo solo con el consentimiento del
  contrato afectado; nunca editar contratos congelados sin registrarlo en el decision ledger.
- El live gate puede revelar la divergencia de request-params señalada en T03 (out-of-scope de
  FR-01); en ese caso se registra como hallazgo/finding nuevo, no se corrige sin decisión.

## Report Path
`plans/chatgpt-codex-auth/task-T10-report.md`
