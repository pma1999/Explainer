# Task T09: Frontend web — card del proveedor, panel, flujo de vínculo y validación

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Añadir el proveedor "ChatGPT (Codex)" a la web: card y sub-panel en el selector, flujo de
vínculo device-code completo en Ajustes, estado en `state.js`/`auth.js`, validación y
persistencia en `landing.js`, y display de uso de cuota en `projectView.js`. Sin tocar los
proveedores actuales.

## Acceptance Criteria
- `index.html`: nueva `.provider-card` (`id="provider-card-codex"`, radio `value="codex"`) en
  `#explainer-provider-group` (junto a gemini/openrouter/deepseek, ~241-268), sub "GPT-5.6 Luna —
  incluida en tu plan ChatGPT" y punto de estado `#provider-card-codex-status`. Sub-panel
  `#codex-model-panel` (patrón `#deepseek-model-panel`, ~334-352) informativo: modelo fijo
  `gpt-5.6-luna` (sin radios) + estado del vínculo inline (no vinculada → botón "Vincular cuenta
  ChatGPT" que abre Ajustes; vinculada → "Vinculada · <planType>" + "Desvincular").
- Ajustes: sección Codex con el flujo device-code: botón iniciar → panel con `verification_url`
  (enlace `target="_blank" rel="noopener noreferrer"`), `user_code` copiable (botón copiar con
  confirmación), botón cancelar; polling de `GET /api/settings/codex-link/status` cada 3 s con
  máximo 10 min; estados rendered `none|pending|linked|failed` con copia honesta (incluye
  `last_error` y mensaje de caducidad); botón "Desvincular" confirmado → `DELETE`.
- `landing.js`: `validProviders` (286) incluye `'codex'`; `isExplainerProviderSupportedForSource`
  (77-81) devuelve false para codex+youtube; `restoreModelSelector` (274-331) exige
  `state.hasCodexLink` para codex (fallback gemini, patrón de fallback por key); `persistModelSelector`
  (248-262) sigue guardando solo `explainerProvider` (sin campos nuevos); `validateExplainerProviderSelection`
  (338-380) añade el parámetro `hasCodexLink` y las dos reglas congeladas (sin vínculo → mensaje;
  codex+pdf sin Mistral → mensaje); `buildExplainerProviderHint` (382+) gana hint codex
  ("Usa GPT-5.6 Luna con la cuota de tu plan ChatGPT…"); `getReviewProviderConfig` (115-130)
  pasa `explainer_provider:'codex'` sin campos extra; `processPayload` (1140-1175) sin cambios
  de forma (solo el valor `'codex'` fluye por el campo existente).
- `state.js`: `hasCodexLink` (bool), `codexLinkStatus` (`none|pending|linked|failed|loading`),
  `codexPlanType` (str|null), junto a `hasDeepSeekKey` (145-159); `auth.js`
  `refreshApiKeyStatus` parsea los campos nuevos del status endpoint y `updateApiKeyUI`
  (612-703) renderiza la sección Codex y el punto de estado de la card (patrón existente por
  proveedor); caché `explainer.codexLinkStatus.v1` en `storage.js` con el patrón de caches
  existentes.
- `projectView.js`: si `usage.codex_quota_requests > 0`, mostrar "Cuota ChatGPT: N peticiones";
  coste 0/incluido sin inventar dólares.
- El listener del grupo de radios (patrón `_landingListenersAttached`, ~955) muestra/oculta el
  sub-panel codex y actualiza hints; idempotente como los existentes.
- Vitest (`tests/frontend/`): `landing.test.js` (validProviders, restore con/sin vínculo,
  validación por fuente/keys, hint, persistencia sin campos nuevos), `landingFlow.test.js` /
  `auth.test.js` (estados de la sección de vínculo con `renderLandingDom`/mocks de `api`).

## Scope
Touch:
- `frontend/index.html`, `frontend/js/landing.js`, `frontend/js/auth.js`,
  `frontend/js/state.js`, `frontend/js/storage.js`, `frontend/js/projectView.js`
  (solo bloque de uso), hoja de estilos existente de provider/settings (solo clases nuevas
  mínimas), `tests/frontend/landing.test.js` + `landingFlow.test.js`/`auth.test.js` (ampliación)

Do not touch:
- Backend, `supabase/`, `android/`, `frontend/js/sse.js`, `frontend/js/api.js`, `backupStorage.js`

## Constraints
- Solo los invariantes de `global-constraints.md` → "Frontend invariants". Mensajes de
  validación y textos de estados congelados.
- Sin framework nuevo ni reescritura del lenguaje visual: reutilizar `.provider-card`,
  `.provider-grid`, `.api-key-status`, `toast`/`copy` existentes.

## Interfaces
Consumes:
- T01 (vía status endpoint): `has_codex_link`, `codex_status`, `codex_plan_type`,
  `codex_updated_at` en `GET /api/settings/api-key/status`.
- T04: `POST/GET /api/settings/codex-link/{start,status,cancel}`, `DELETE
  /api/settings/codex-link` con las formas JSON congeladas.
- T07 (contrato, no archivos): `explainer_provider: "codex"` en `/process`.

Produces:
- Selector con provider `codex` + flujo de vínculo completo + display de uso.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/index.html` | provider group + sub-panels + settings de keys | 241-357, ~1030-1060 | Estructura a extender |
| `frontend/js/landing.js` | selector/persist/validate/hint/payload | 77-81, 115-130, 240-331, 338-405, 1140-1175 | Todos los puntos a tocar |
| `frontend/js/auth.js` | `refreshApiKeyStatus`, `updateApiKeyUI` | 28-106, 612-703 | Estado de keys → vínculo |
| `frontend/js/state.js` | flags de keys | 140-175 | Dónde viven los flags |
| `frontend/js/projectView.js` | render de usage | grep `total_cost` | Bloque de uso |
| `plans/chatgpt-codex-auth/global-constraints.md` | Frontend invariants | sección | Textos y reglas congelados |

## Existing Patterns To Reuse
- DeepSeek como plantilla end-to-end (card, panel, validación, persistencia, caches, hints).
- `createCombobox` NO se usa (modelo fijo); el flujo de vínculo reutiliza el patrón de
  `refreshApiKeyStatus` + caches por proveedor.

## Tests
- `npx vitest run` (módulos tocados) y `npm run test:all` al final.
- Señal verde: los tests nuevos de selector/vínculo pasan; los tests existentes de
  landing/auth/state/storage sin regresiones.

## Implementer
task-implementer-bdd

## Task Review
Required: no
Why: extensión de UI con tests de comportamiento puros; final review es suficiente.

## Named Risks
- `updateApiKeyUI` se llama desde varios sitios: mantener la idempotencia del patrón existente.
- Polling máximo 10 min y limpieza de intervalos al cerrar Ajustes (evitar fugas de timers).

## Report Path
`plans/chatgpt-codex-auth/task-T09-report.md`
