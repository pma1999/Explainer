# Task T02: Effort Codex — frontend (sub-panel en la card, persistencia, payload)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Añadir al sub-panel de la card "ChatGPT (Codex)" un selector de nivel de razonamiento (thinking)
de Luna con EXACTAMENTE los niveles `low/medium/high/xhigh/max` (default `medium`), copia en
español por nivel (velocidad/calidad/consumo de cuota), marca de default recomendado y nota de
que afecta a todas las fases; persistirlo en `explainer.modelSelector.v1` (campo `codexEffort`)
con restore tolerante a ausencia/valores inválidos, e incluirlo en el payload de `/process`
(`codex_effort`) solo para el provider codex.

## Acceptance Criteria
- En `#codex-model-panel` (solo visible con provider codex) aparece el bloque "Nivel de
  razonamiento (thinking)" con 5 radios `name="codex-effort"` e ids
  `codex-effort-{low|medium|high|xhigh|max}`, en ese orden, con los títulos y descripciones
  congelados (ver Constraints), medium marcado "Recomendado" y `checked` por defecto, y la
  nota congelada "se aplica a todas las fases".
- Seleccionar un nivel lo persiste: `localStorage['explainer.modelSelector.v1'].codexEffort`
  refleja el valor elegido; el estado sobrevive a `restoreModelSelector()`.
- `restoreModelSelector()`: campo ausente → `medium`; valor válido de la allowlist → ese
  valor; valor inválido/no-string → `medium`. Nunca lanza.
- El payload de `POST /api/projects/{id}/process` incluye `codex_effort` solo cuando el
  provider es codex; los demás providers no lo incluyen.
- El grupo de radios queda oculto cuando el provider no es codex o codex no está soportado
  para la fuente (patrón existente del panel).
- `npx vitest run` completo verde, incluido el test existente de persistencia de la card
  codex actualizado para el nuevo campo.

## Scope
Touch:
- `frontend/index.html` — extensión de `#codex-model-panel` (361-377): bloque de effort tras
  `#codex-model-group`.
- `frontend/js/landing.js` — constantes `CODEX_EFFORT_LEVELS`/`CODEX_DEFAULT_EFFORT` (junto a
  `DEEPSEEK_MODEL_*`, ~16-20), estado `currentCodexEffort`, `persistModelSelector` (245),
  `restoreModelSelector` (268), `syncExplainerProviderUI` (~604-640), listener change del
  grupo bajo `_landingListenersAttached` (~875-885), payload en `handleUpload` (1184-1216).
- `tests/frontend/landing.test.js` — actualizar test "persistModelSelector never writes new
  codex fields" (640) y añadir casos de effort.
- `tests/frontend/landingFlow.test.js` — casos DOM con `renderLandingDom` (default checked,
  persist al click, payload).

Do not touch:
- `backend/**`, `tests/backend/**`, `android/**`, `frontend/js/getReviewProviderConfig`
  (`getReviewProviderConfig` no cambia), `frontend/js/auth.js`, `frontend/js/api.js`,
  `frontend/js/state.js`, `frontend/js/sse.js`, `frontend/js/projectView.js`.

## Constraints
Solo los invariantes de `plans/codex-effort-selector/global-constraints.md` que vinculan esta
tarea: "Allowlist y default" (espejo frontend), "API y persistencia" (payload y persistencia)
y "Frontend UX" completa (DOM, copia congelada, persist/restore, listener). Se mantienen los
invariantes frontend de `plans/chatgpt-codex-auth/global-constraints.md` (§Frontend
invariants: `validProviders`, fallback por vínculo, `isExplainerProviderSupportedForSource`).

## Interfaces
Consumes:
- Backend (congelado por T01): `POST /api/projects/{id}/process` acepta
  `codex_effort: "low"|"medium"|"high"|"xhigh"|"max"` (opcional); valores inválidos → 400 con
  mensaje fijo. No se requiere llamada nueva de API.
- `frontend/js/state.js`: `state.hasCodexLink` (fallback existente del provider).

Produces:
- `explainer.modelSelector.v1` gana `codexEffort` (string de la allowlist, siempre escrito por
  `persistModelSelector`).
- Payload de process con `codex_effort` para provider codex.
- DOM: `#codex-effort-group` con radios `codex-effort-{low|medium|high|xhigh|max}`
  (`name="codex-effort"`), copia congelada, nota de todas las fases.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/codex-effort-selector/global-constraints.md` | secciones "Allowlist y default" y "Frontend UX" | completo | Copia congelada, DOM ids, reglas de persist/restore |
| `frontend/index.html` | card `#provider-card-codex` (268-275), `#codex-model-panel` (361-377), `#openrouter-model-panel` (282-358) como patrón visual | 255-380 | Dónde insertar el bloque y qué clases reutilizar |
| `frontend/js/landing.js` | constantes/estado (12-38), `persistModelSelector` (245), `restoreModelSelector` (268), `syncExplainerProviderUI` (604-640), listeners (860-890), `handleUpload` payload (1184-1216) | 1-45, 240-470, 595-650, 860-890, 1175-1230 | Puntos de edición exactos |
| `tests/frontend/landing.test.js` | tests codex round-trip (606-623), test "no extra codex fields" (640-665) | 600-665 | Test existente a actualizar |
| `tests/frontend/landingFlow.test.js` | factory `renderLandingDom` y tests de panel | grep `codex-model-panel` | Patrón para tests DOM |
| `tests/frontend/setup.js` | mock de `state` y `localStorage` | completo (corto) | Cómo mockear `state.hasCodexLink` |

## Existing Patterns To Reuse
- Sub-paneles por proveedor: `openrouter-model-panel` / `deepseek-model-panel` / `codex-model-panel`
  con `classList.toggle('hidden', ...)` en `syncExplainerProviderUI` — el bloque de effort vive
  dentro del panel codex y hereda su visibilidad (no necesita toggle propio).
- Radios + `provider-grid`/`provider-card` (patrón `openrouter-model-group`): mismo markup que
  los modelos OpenRouter, con radios ocultos y labels tipo card.
- Persist/restore tolerante: patrón `isValidDeepSeekModel(saved.deepseekModel) ? ... :
  DEEPSEEK_MODEL_V4_PRO` en `restoreModelSelector` — aquí
  `CODEX_EFFORT_LEVELS.includes(saved.codexEffort) ? saved.codexEffort : CODEX_DEFAULT_EFFORT`.
- Payload condicional: patrón `if (currentExplainerProvider === 'deepseek')
  processPayload.deepseek_model = ...` en `handleUpload`.
- Listeners idempotentes bajo `if (!_landingListenersAttached)`.

## Tests
(`npx vitest run` al final; durante el desarrollo `npx vitest run landing.test.js
landingFlow.test.js`)
- `landing.test.js`:
  - Actualizar "persistModelSelector never writes new codex fields": la lista de claves
    esperadas ahora incluye `'codexEffort'` (el test sigue validando que NO hay más claves).
  - Nuevo: restore sin `codexEffort` → `persistModelSelector` escribe `codexEffort ===
    'medium'`; restore con `codexEffort: 'xhigh'` → round-trip `'xhigh'`; restore con
    `codexEffort: 'none'`/`123`/`null` → `'medium'`.
  - Nuevo: con `state.hasCodexLink = true` y provider codex, round-trip conserva
    `codexEffort`.
- `landingFlow.test.js` (con `renderLandingDom`):
  - Con provider codex seleccionado, el radio `codex-effort-medium` está `checked` y la nota
    de "todas las fases" es visible; el grupo se oculta al cambiar a gemini.
  - `click` en `codex-effort-xhigh` → `localStorage['explainer.modelSelector.v1']` contiene
    `codexEffort: 'xhigh'`.
  - Payload de upload (mock de `api`/`handleUpload` o assert del objeto construido): incluye
    `codex_effort: 'xhigh'` para codex; ausente para gemini.
  - Red/green: los tests nuevos fallan antes de implementar (no existe el DOM/campo) y pasan
    tras la implementación; el test de claves actualizado falla si se añaden claves extra o
    falta `codexEffort`.

## Implementer
task-implementer-bdd

## Task Review
Required: no
Why: final review is sufficient (extensión incremental de UI sobre lenguaje visual existente;
cubierta por vitest y el contrato congelado).

## Named Risks
- R-COPY: usar EXACTAMENTE los títulos/descripciones congelados; no reformular.
- No aplicar skill de frontend (decisión de producto): reutilizar clases existentes; cambios
  de CSS solo mínimos e imprescindibles.

## Report Path
`plans/codex-effort-selector/task-T02-report.md`
