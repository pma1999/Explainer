# Task T02 Report

## Status
DONE

## Outcome
La card "ChatGPT (Codex)" tiene ahora el sub-panel "Nivel de razonamiento (thinking)" con 5
radios `name="codex-effort"` (ids `codex-effort-{low|medium|high|xhigh|max}`, en orden
canónico), medium `checked` por defecto con la marca "Recomendado" en el título y la nota
congelada "se aplica a todas las fases". El estado `currentCodexEffort` se persiste en
`explainer.modelSelector.v1` (clave `codexEffort`) con restore tolerante (ausente/inválido/no
string → `medium`, nunca lanza) y se incluye `codex_effort` en el payload de
`POST /api/projects/{id}/process` solo cuando el provider es codex. El grupo de effort hereda
la visibilidad del panel (`#codex-model-panel` oculto cuando el provider no es codex o codex
no está soportado para la fuente). Copia UX española EXACTA del constraint (R-COPY
verificado).

## Acceptance Criteria
- Bloque "Nivel de razonamiento (thinking)" dentro de `#codex-model-panel` con 5 radios
  `name="codex-effort"` e ids `codex-effort-{low|medium|high|xhigh|max}` en ese orden, medium
  checked por defecto y título "Equilibrado (Recomendado)", nota congelada de todas las fases
  -> pass (index.html 371-409; verificado por grep y por test DOM `landingFlow`).
- Click en un nivel lo persiste en `localStorage['explainer.modelSelector.v1'].codexEffort`;
  sobrevive a `restoreModelSelector()` -> pass (test "persists codexEffort when an effort
  radio is clicked" + unit round-trips).
- `restoreModelSelector()`: ausente → `medium`; allowlist → ese valor; inválido/no-string →
  `medium`; nunca lanza -> pass (tests unitarios con `'none'`, `123`, `null`, ausente).
- Payload de `/api/projects/{id}/process` con `codex_effort` solo cuando provider codex;
  demás providers sin él -> pass (tests payload codex xhigh/medium y test gemini ausente).
- Grupo oculto cuando el provider no es codex o codex no soportado (patrón existente del
  panel) -> pass (test "renders the effort group…" cambia a gemini y verifica panel hidden;
  test existente de YouTube sigue verde).
- `npx vitest run` completo verde, incluido el test existente de persistencia de la card
  codex actualizado -> pass (19 files, 347 tests).

## Files Changed
- `frontend/index.html` - modified; bloque de effort (label + `#codex-effort-group` con 5
  labels `.provider-card` + nota `#codex-effort-note`) insertado dentro de
  `#codex-model-panel`, tras `#codex-model-group`. Sin clases nuevas (reutiliza
  `provider-grid`, `openrouter-model-grid`, `provider-card`, `provider-card-main/title/sub`,
  `form-label`, `input-hint`); únicamente ids nuevos (patrón existente `*-card-*`).
- `frontend/js/landing.js` - modified; constantes `CODEX_EFFORT_LEVELS`/`CODEX_DEFAULT_EFFORT`
  (espejo del backend, junto a `DEEPSEEK_MODEL_*`), estado `currentCodexEffort`,
  `codexEffort` en `persistModelSelector`, restore con fallback en `restoreModelSelector`,
  sync de radios + `selected` de cards en `syncExplainerProviderUI`, refs DOM en
  `initLanding`, listener `change` sobre `#codex-effort-group` bajo `_landingListenersAttached`
  y `codex_effort` en el payload de `handleUpload`.
- `tests/frontend/landing.test.js` - modified; test "never writes new codex fields"
  actualizado (claves esperadas ahora incluyen `codexEffort`, sigue validando que NO hay
  claves extra) + 4 tests nuevos de persist/restore.
- `tests/frontend/landingFlow.test.js` - modified; `renderLandingDom` extendido con el grupo
  de effort dentro de `#codex-model-panel`, test de payload codex existente actualizado
  (body ahora incluye `codex_effort: 'medium'`), 4 tests nuevos DOM/persist/payload.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| frontend/js/landing.js | `CODEX_EFFORT_LEVELS` (export) | added `['low','medium','high','xhigh','max']` |
| frontend/js/landing.js | `CODEX_DEFAULT_EFFORT` (export) | added `'medium'` |
| frontend/js/landing.js | `currentCodexEffort` (module state) | added, init `CODEX_DEFAULT_EFFORT` |
| frontend/js/landing.js | `persistModelSelector` | writes `codexEffort: currentCodexEffort` siempre |
| frontend/js/landing.js | `restoreModelSelector` | `CODEX_EFFORT_LEVELS.includes(saved.codexEffort) ? saved.codexEffort : CODEX_DEFAULT_EFFORT` |
| frontend/js/landing.js | `syncExplainerProviderUI` | refleja `currentCodexEffort` en los 5 radios y en `selected` de las 5 cards |
| frontend/js/landing.js | `initLanding` | refs `codexEffortGroup` + 5 radios; listener `change` del grupo bajo `_landingListenersAttached`: `currentCodexEffort = e.target.value` (solo si `CODEX_EFFORT_LEVELS.includes`) + sync + persist |
| frontend/js/landing.js | `handleUpload` | `processPayload.codex_effort = currentCodexEffort` en rama `else if (currentExplainerProvider === 'codex')` |
| frontend/index.html | `#codex-model-panel` DOM | bloque effort tras `#codex-model-group` |

## Tests
- Command: `npx vitest run tests/frontend/landing.test.js tests/frontend/landingFlow.test.js`
  Result: pass — 2 files, 128 tests (antes de implementar: 8 fallos RED esperados).
- Command: `npx vitest run`
  Result: pass — 19 files, 347 tests, 0 fallos.

## TDD Evidence
- RED: tras añadir los tests y antes de tocar el código, `npx vitest run
  tests/frontend/landing.test.js tests/frontend/landingFlow.test.js` -> 8 failed:
  - 5 en landing.test.js: `codexEffort` ausente en claves persistidas (`expected undefined to
    be 'medium'/'xhigh'/'high'`) y test de claves (faltaba `'codexEffort'` en la lista).
  - 3 en landingFlow.test.js: payload codex sin `codex_effort`, listener de persistencia
    inexistente (`expected undefined to be 'xhigh'`).
- GREEN: tras implementar, mismo comando -> 128 passed; `npx vitest run` completo -> 347
  passed. El test de claves actualizado falla si falta `codexEffort` o aparece cualquier
  clave extra (lista exacta con `toEqual`).

## Read Ledger
Planned reads:
- `plans/codex-effort-selector/task-T02-brief.md` — brief completo.
- `plans/codex-effort-selector/global-constraints.md` — §§Allowlist y default, API y
  persistencia, Frontend UX (copia congelada).
- `plans/codex-effort-selector/plan.md` — §Chosen approach 6 y task graph.
- `frontend/index.html` (255-384) — card codex y paneles modelo como patrón visual.
- `frontend/js/landing.js` (1-59, 235-364, 415-524, 595-674, 674-793, 840-959, 960-1079,
  1160-1229) — puntos de edición exactos.
- `tests/frontend/landing.test.js` (1-120, 514-684) — tests persist/restore existentes.
- `tests/frontend/landingFlow.test.js` (1-199, 1280-1471) — factory `renderLandingDom` y
  tests del panel codex.
- `tests/frontend/setup.js` — stub de `getElementById` y globals.

Extra reads:
- `frontend/js/landing.js` 415-524 (`buildExplainerProviderHint` + inicio de `initLanding`) —
  confirmar estructura de `initLanding` y refs DOM existentes antes de editar.
- `tests/frontend/landingFlow.test.js` 192-266 — patrón del test de payload gemini existente
  (reutilizado para el test de ausencia de `codex_effort`).
- `frontend/js/landing.js` 754-793 (`setDeepSeekModel`, `loadOpenRouterModels`) — patrón
  setter+sync+persist para mimetizar el listener de effort.

Pack gaps:
- None.

## Decisions
- El listener de `#codex-effort-group` llama también a `syncExplainerProviderUI()` además de
  `persistModelSelector()`: necesario para mover la clase visual `selected` entre cards,
  mimetizando los grupos openrouter/deepseek (el contrato congelado fija el mínimo
  `currentCodexEffort = value; persistModelSelector()`; sync no lo viola).
- El bloque de effort va entre `#codex-model-group` y el párrafo `#codex-panel-link-status`
  ("tras `#codex-model-group`" sin ambigüedad); la nota usa `class="input-hint"` (clase
  existente de notas) con id `codex-effort-note` (los hints existentes llevan id, p.ej.
  `explainer-provider-hint`). Ninguna clase nueva.
- Cards de effort con ids `codex-effort-card-{level}` siguiendo el patrón
  `deepseek-model-card-*` para poder reflejar `selected` desde sync (ids nuevos, no clases).
- `restoreModelSelector` restaura `codexEffort` independientemente del provider final
  (fallback por vínculo incluido): el campo es global del selector, igual que `deepseekModel`.
- El test de flujo existente "submits codex with no extra payload fields" se actualizó a
  "submits codex with the default codex_effort..." (body `{explainer_provider, target_language,
  codex_effort}`): el campo nuevo forma parte del contrato de payload para codex; la
  aserción `toEqual` de la lista de claves de localStorage en landing.test.js sigue
  garantizando que no hay claves extra.
- No se tocó `frontend/js/getReviewProviderConfig` ni ningún archivo de `backend/**` (T01
  corre en paralelo; archivos disjuntos verificados con `git status`).

## Concerns / Follow-ups
- Ninguno. Contrato cross-task (`codex_effort` en payload, allowlist, default) se validó solo
  contra el espejo local de global-constraints.md; la integración real con el backend de T01
  la cruza el revisor final (según plan.md §Parallel-safety reasoning). Ninguna relajación de
  contrato.

## Remediation History
None for the initial implementation.
