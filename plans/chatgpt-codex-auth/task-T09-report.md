# Task T09 Report

## Status
DONE

## Outcome
El proveedor "ChatGPT (Codex)" está integrado en la web completa: card `.provider-card`
`#provider-card-codex` (sub "GPT-5.6 Luna — incluida en tu plan ChatGPT" y punto de estado
`#provider-card-codex-status`), sub-panel informativo `#codex-model-panel` (modelo fijo
`gpt-5.6-luna` sin radios, estado del vínculo inline con botones "Vincular cuenta ChatGPT" →
abre Ajustes y "Desvincular" → confirmado → DELETE), flujo device-code completo en Ajustes
(iniciar → panel con `verification_url` como enlace `target="_blank" rel="noopener noreferrer"`,
`user_code` copiable con confirmación, cancelar; polling de `GET /api/settings/codex-link/status`
cada 3 s con deadline de 10 min; estados rendered `none|pending|linked|failed` con copia honesta
incluyendo `last_error` del servidor y mensaje de caducidad; desvincular con `confirm()` →
`DELETE`), estado en `state.js` (`hasCodexLink`, `codexLinkStatus`, `codexPlanType`) + caché
`explainer.codexLinkStatus.v1.` en `storage.js`, parseo de los campos nuevos del status endpoint
en `refreshApiKeyStatus`, y display de uso "Cuota ChatGPT: N peticiones" en `projectView.js`
solo cuando `usage.codex_quota_requests > 0` (coste mostrado como "Incluido", sin inventar
dólares). Los proveedores gemini/openrouter/deepseek quedan intactos (los tests existentes
pasan sin cambios de comportamiento).

## Acceptance Criteria
- `index.html`: card codex en `#explainer-provider-group` con radio `value="codex"`, sub
  "GPT-5.6 Luna — incluida en tu plan ChatGPT" y punto `#provider-card-codex-status` -> pass
  (diff; patrón de las cards existentes).
- Sub-panel `#codex-model-panel` informativo (patrón `#deepseek-model-panel`): modelo fijo
  `gpt-5.6-luna` sin radios + estado del vínculo inline (no vinculada → botón "Vincular cuenta
  ChatGPT" que abre Ajustes; vinculada → "Vinculada · <planType>" + "Desvincular") -> pass
  (HTML + `updateApiKeyUI` renderiza texto y visibilidad de ambos botones; tests
  `auth.test.js` "renders the linked state ... in the selector sub-panel" y
  `landingFlow.test.js` "opens Ajustes from the sub-panel..." / "unlinks ... from the sub-panel").
- Ajustes: sección Codex con device-code (iniciar → panel con URL + código copiable + cancelar),
  polling 3 s máx. 10 min, estados `none|pending|linked|failed` con `last_error` y caducidad,
  desvincular confirmado → `DELETE` -> pass (tests `auth.test.js` device-code flow: start/poll
  3 s→linked, last_error del servidor, caducidad a los 10 min, cancel, unlink con/sin
  confirmación, copy, `hideSettings` detiene el polling).
- `landing.js`: `validProviders` incluye `'codex'`; `isExplainerProviderSupportedForSource`
  false para codex+youtube; `restoreModelSelector` exige `state.hasCodexLink` (fallback gemini);
  `persistModelSelector` sin campos nuevos (test con la lista exacta de claves); 
  `validateExplainerProviderSelection` con `hasCodexLink` y los 2 mensajes congelados
  ("Vincula tu cuenta ChatGPT en Ajustes para usar Codex." /
  "Necesitas configurar tu API key de Mistral para usar OCR en PDFs con Codex."); hint codex;
  `getReviewProviderConfig` pasa `explainer_provider:'codex'` sin campos extra (sin cambios de
  código necesarios: codex no entra en las ramas openrouter/deepseek); `processPayload` sin
  cambios de forma -> pass (tests `landing.test.js` y `landingFlow.test.js`).
- `state.js`: `hasCodexLink` (bool), `codexLinkStatus`, `codexPlanType` junto a los flags de
  keys; `auth.js` `refreshApiKeyStatus` parsea `has_codex_link`/`codex_status`/`codex_plan_type`
  y `updateApiKeyUI` renderiza la sección Codex + punto de estado de la card (patrón por
  proveedor); caché `explainer.codexLinkStatus.v1` en `storage.js` con el patrón existente ->
  pass (tests `state.test.js`, `storage.test.js`, `auth.test.js`).
- `projectView.js`: "Cuota ChatGPT: N peticiones" solo si `usage.codex_quota_requests > 0`;
  coste 0/incluido sin inventar dólares -> pass (tests `projectViewProgress.test.js`
  updateUsageUI: fila visible + "Incluido"; oculta + `$1.25` sin cuota).
- Listener del grupo de radios muestra/oculta `#codex-model-panel` y actualiza hints; idempotente
  (mismo guard `_landingListenersAttached`) -> pass (test de idempotencia existente sigue
  pasando; "disables the codex radio on YouTube..." y "selecting codex shows..." cubren el panel).
- Vitest: `landing.test.js`, `landingFlow.test.js`, `auth.test.js` ampliados con la factory
  `renderLandingDom` para UI -> pass (339 tests frontend en verde, 19 archivos).

## Files Changed
- `frontend/index.html` - modified; card `#provider-card-codex` + radio `value="codex"`,
  sub-panel `#codex-model-panel` (modelo fijo + estado inline con botones), sección de Ajustes
  "Cuenta ChatGPT (Codex)" con el flujo device-code completo (estados, panel, botones), fila de
  uso `#usage-codex-quota-row` en `#project-usage-card`.
- `frontend/js/landing.js` - modified; `validProviders` + codex, `isExplainerProviderSupportedForSource`
  (codex+youtube=false), fallback de `restoreModelSelector` por `hasCodexLink`, reglas congeladas
  en `validateExplainerProviderSelection` (+`hasCodexLink`), hint codex en
  `buildExplainerProviderHint`, soporte de codex en `syncExplainerProviderUI` (radio/panel/selected/
  disabled), listener del radio y de los botones del sub-panel (vincular → `showSettings`,
  desvincular → `unlinkCodexAccount`), `hasCodexLink` en la llamada de validación de
  `handleUpload`.
- `frontend/js/auth.js` - modified; `refreshApiKeyStatus` siembra desde caché y parsea los campos
  codex del status endpoint; `updateApiKeyUI` renderiza la sección Codex de Ajustes, el punto de
  estado de la card y el estado inline del sub-panel (idempotente, sin listeners); flujo
  device-code: `startCodexLink`, `cancelCodexLink`, `unlinkCodexAccount`, `copyCodexUserCode`,
  polling `_pollCodexLinkStatus` (3 s, deadline 10 min o `expires_in` si es menor); `initSettings`
  cablea los botones de la sección; `showSettings` reanuda el polling si hay `pending`;
  `hideSettings` detiene el polling y limpia el error.
- `frontend/js/state.js` - modified; `hasCodexLink`, `codexLinkStatus`, `codexPlanType` +
  constante `CODEX_LINK_CACHE_KEY_PREFIX = 'explainer.codexLinkStatus.v1.'`.
- `frontend/js/storage.js` - modified; `getCachedCodexLinkStatus`/`setCachedCodexLinkStatus`
  (patrón de caches por proveedor, TTL `API_KEY_CACHE_TTL_MS`, validación de estados).
- `frontend/js/projectView.js` - modified; solo bloque de uso: fila "Cuota ChatGPT: N peticiones"
  y coste "Incluido" cuando `codex_quota_requests > 0`.
- `frontend/style.css` - modified; solo clases nuevas mínimas: `.codex-panel-link-status` y
  `.codex-verification-link` (enlace del device-code).
- `tests/frontend/landing.test.js` - modified; codex en `isExplainerProviderSupportedForSource`,
  reglas congeladas de `validateExplainerProviderSelection`, round-trip/fallback de
  `restoreModelSelector`, persistencia sin campos nuevos (lista exacta de claves).
- `tests/frontend/landingFlow.test.js` - modified; factory `renderLandingDom` + estado mock
  ampliados con codex; describe "codex provider (ChatGPT)" (selección/panel, YouTube deshabilitado,
  bloqueo de submit con los 2 mensajes, payload `explainer_provider:'codex'` sin campos extra,
  restore con/sin vínculo, botones del sub-panel).
- `tests/frontend/auth.test.js` - modified; describe "codex link (ChatGPT)": hydratación del
  status endpoint, render de `updateApiKeyUI` (linked/pending/failed/none en Ajustes, card y
  sub-panel), flujo device-code completo con fake timers (start, poll→linked, last_error,
  caducidad 10 min, cancel, unlink con/sin confirmación, copy, `hideSettings` detiene polling).
- `tests/frontend/storage.test.js` - modified; round-trip/TTL/prefix/corrupt de la caché codex.
- `tests/frontend/state.test.js` - modified; assert de los campos de estado y del prefijo de caché.
- `tests/frontend/projectViewProgress.test.js` - modified; DOM de usage en `resetDom` + tests de
  `updateUsageUI` con/sin cuota codex.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/index.html` | `#provider-card-codex`, `#explainer-provider-codex`, `#codex-model-panel`, `#provider-card-codex-status` | Nuevos (card + sub-panel + punto de estado) |
| `frontend/index.html` | `#codex-link-not-set/pending/set/failed`, `#btn-start-codex-link`, `#codex-device-panel`, `#codex-verification-url`, `#codex-user-code`, `#btn-copy-codex-code`, `#btn-cancel-codex-link`, `#btn-unlink-codex`, `#codex-link-error` | Nueva sección de Ajustes (device-code) |
| `frontend/index.html` | `#usage-codex-quota-row`, `#usage-codex-quota` | Nueva fila de uso |
| `frontend/js/landing.js` | `validProviders`, `isExplainerProviderSupportedForSource`, `restoreModelSelector`, `validateExplainerProviderSelection`, `buildExplainerProviderHint` | Extendidos con `'codex'` / `hasCodexLink` / reglas congeladas / hint |
| `frontend/js/landing.js` | `initLanding` (`syncExplainerProviderUI`, listener del radio, botones del sub-panel) | Extendido; guard `_landingListenersAttached` intacto (idempotente) |
| `frontend/js/auth.js` | `refreshApiKeyStatus` | Parsea `has_codex_link`/`codex_status`/`codex_plan_type`; siembra desde caché |
| `frontend/js/auth.js` | `updateApiKeyUI` | Render de la sección Codex + card + sub-panel (nuevo, al final, patrón existente) |
| `frontend/js/auth.js` | `startCodexLink`, `cancelCodexLink`, `unlinkCodexAccount` (export), `_pollCodexLinkStatus`, `_startCodexPolling`, `_stopCodexPolling`, `_cacheCodexLinkState`, `copyCodexUserCode` | Nuevos (flujo device-code + polling 3 s / 10 min) |
| `frontend/js/auth.js` | `initSettings`, `showSettings`, `hideSettings` | Cableado de botones; reanudar polling si pending; detener polling al cerrar |
| `frontend/js/state.js` | `state.hasCodexLink`, `state.codexLinkStatus`, `state.codexPlanType` | Nuevos |
| `frontend/js/state.js` | `CODEX_LINK_CACHE_KEY_PREFIX` | Nuevo: `'explainer.codexLinkStatus.v1.'` |
| `frontend/js/storage.js` | `getCachedCodexLinkStatus`, `setCachedCodexLinkStatus` | Nuevos (patrón de caches, TTL 24 h) |
| `frontend/js/projectView.js` | `updateUsageUI` | Fila cuota + coste "Incluido" (solo bloque de uso) |
| `frontend/style.css` | `.codex-panel-link-status`, `.codex-verification-link` | Clases nuevas mínimas |

## Tests
- `npx vitest run` (todos los tests frontend): **19 archivos / 339 tests pasan** (antes del
  cambio: 156 en los 6 archivos tocados; el resto del suite intacto). Incluye los tests nuevos
  de selector, vínculo y usage.
- `npm run test:all`: **frontend (vitest) pasa** (339/339); el paso backend **no pudo ejecutarse
  por el entorno**: `scripts/run-all-tests.js` invoca `python` que no existe en PATH aquí
  (solo `python3`), y `python3` no tiene `pytest` instalado
  (`ModuleNotFoundError: No module named 'pytest'`; el único venv presente, `.venv-win/`, es de
  Windows y no es usable en Linux). El backend no se tocó en T09.
- `npm run test:e2e`: **not-verified por el entorno**: `playwright` no está en
  `node_modules/.bin` como binario Unix (solo `playwright.cmd`/`.ps1` de instalación Windows) y el
  paquete `@playwright/test` no está instalado (`Error: Cannot find package '@playwright/test'
  imported from tests/e2e/app.spec.js`). Los browsers sí están descargados
  (`~/.cache/ms-playwright/chromium-1228`). Los specs e2e son smoke de carga; el cambio de HTML
  no rompe el parseo (los tests `modules.test.js` y `dom.test.js` cargan `main.js`/DOM en verde).

## TDD Evidence
- RED (antes de implementar): `npx vitest run` sobre los 6 archivos tocados → 38 tests nuevos
  fallando por las razones esperadas (funciones/exports ausentes: `setCachedCodexLinkStatus is
  not a function`, mensajes congelados no devueltos, `SELECTOR_KEY` no definido en el describe
  nuevo — corregido en la fase de tests, panel device-code no visible por falta de `show()` en
  `startCodexLink`, y acúmulo de historia del mock de `api` entre tests — corregido con
  `mockReset()` en `beforeEach`). Los 156 tests existentes seguían en verde durante el RED.
- GREEN: `npx vitest run tests/frontend/` → 19 archivos / 339 tests pasan (todo el suite
  frontend, incluidos los 38+ tests nuevos de selector/vínculo/usage y los existentes sin
  regresiones).

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T09-brief.md` - brief completo (acceptance criteria, scope,
  context pack, risks).
- `plans/chatgpt-codex-auth/global-constraints.md` - §Frontend invariants y §Link endpoints
  (textos congelados, formas JSON, polling).
- `plans/chatgpt-codex-auth/context-map.md` - localización de los puntos del selector/auth
  (read-hints de líneas).
- `frontend/index.html` - provider group + sub-panels + settings de keys + usage card.
- `frontend/js/landing.js` - selector/persist/validate/hint/payload/listeners (completo).
- `frontend/js/auth.js` - `refreshApiKeyStatus`, `initSettings`, `showSettings`, `hideSettings`,
  `updateApiKeyUI` (completo).
- `frontend/js/state.js` - flags de keys y prefijos de caché (completo).
- `frontend/js/storage.js` - patrón de caches por proveedor (completo).
- `frontend/js/projectView.js` - `updateUsageUI` (bloque de uso).
- `frontend/style.css` - `.provider-card*`, `.api-key-status`, `.settings-*`, `.share-link-row`,
  `.status-*`, `.btn-sm`.
- `tests/frontend/landing.test.js`, `landingFlow.test.js`, `auth.test.js`, `storage.test.js`,
  `state.test.js`, `projectViewProgress.test.js`, `setup.js` - patrones de test y factory
  `renderLandingDom`.
- `frontend/js/main.js` - orden de llamadas `initSettings`/`initLanding`/`refreshApiKeyStatus`.
- `tests/backend/test_codex_link_endpoints.py` - formas JSON congeladas de start/status/cancel
  (solo lectura para confirmar el contrato).
- `plans/chatgpt-codex-auth/task-T08-report.md` - formato del reporte del bundle.

Extra reads:
- `scripts/run-all-tests.js`, `playwright.config.js`, `tests/e2e/app.spec.js` - para saber qué
  ejecuta `test:all` y si el e2e es ejecutable aquí.
- `node_modules/` (playwright/`@playwright/test`) - diagnóstico de por qué `test:e2e` no arranca
  (bins Windows-only, paquete ausente).

Pack gaps:
- None (el contrato T01/T04/T07 llegó completo y congelado; no hizo falta relajar nada).

## Decisions
- **Dueño del punto de estado de la card codex: `updateApiKeyUI`** (invariante: "punto de estado
  `#provider-card-codex-status` actualizado por `updateApiKeyUI`"). `syncExplainerProviderUI` solo
  gestiona `selected`/`disabled` de la card y la visibilidad del sub-panel; así no hay dos
  escritores compitiendo por el mismo nodo (riesgo nombrado de `updateApiKeyUI` llamado desde
  varios sitios; se mantiene la idempotencia: es render puro sin listeners).
- **Polling**: intervalo de 3 s con deadline `min(expires_in del start, 10 min)`; en `failed`
  con `last_error` del servidor se detiene y se muestra; caducidad cliente = mensaje "El vínculo
  caducó. Vuelve a iniciarlo." con reintento (botón iniciar de nuevo). `hideSettings` detiene el
  intervalo (riesgo nombrado de fugas de timers); `showSettings` reanuda con ventana fresca si el
  estado sigue `pending`. `status == 'none'` durante el polling (p. ej. cancelado en otro lado)
  detiene y renderiza `none`.
- **`last_error` no se cachea**: la caché `explainer.codexLinkStatus.v1.` guarda solo
  `{hasCodexLink, codexStatus, codexPlanType}` (los campos del invariante). Si el estado `failed`
  se rehidrata desde el status endpoint (que no devuelve `last_error`), la copia honesta es el
  mensaje genérico "El vínculo falló. Vuelve a iniciarlo."; el `last_error` real se muestra
  durante el flujo de polling.
- **Coste "Incluido"**: cuando `usage.codex_quota_requests > 0` el pill de coste muestra
  "Incluido" (tanto en `#usage-total-cost` como en `#mini-total-cost`), y `$0.00`/dólares solo
  cuando no hay cuota codex — "0/incluido sin inventar dólares".
- **Sub-panel sin radios**: `createCombobox` no se usa; el modelo fijo `gpt-5.6-luna` es una card
  informativa sin input, y el estado del vínculo son dos botones estáticos cuya visibilidad/texto
  controla `updateApiKeyUI` (los listeners se cuelgan una sola vez bajo
  `_landingListenersAttached` en `initLanding`).
- **`getReviewProviderConfig` y `processPayload` sin cambios de código**: `'codex'` fluye por el
  campo existente `explainer_provider`; ninguna rama openrouter/deepseek aplica (verificado por
  lectura y por el test de payload que exige exactamente `{explainer_provider:'codex',
  target_language:'es-ES'}`).

## Concerns / Follow-ups
- **`npm run test:all` incompleto en este entorno**: el paso backend (pytest) y el e2e
  (Playwright) no son ejecutables aquí (`python` ausente, `pytest` no instalado para `python3`,
  `@playwright/test` no instalado y bins de playwright solo `.cmd` de instalación Windows). El
  backend no se tocó (T01-T08 lo cubren); conviene un `test:all` completo en un entorno con el
  toolchain Python + Playwright antes del merge.
- El `status == 'none'` durante el polling se trata como fin del flujo (rendered `none`); si el
  backend algún día devolviera `none` transitoriamente tras un `start`, el usuario vería el
  estado "No vinculada" y podría reintentar — comportamiento honesto, sin polling infinito.
- Los untracked `.opencode/`, `.playwright-mcp/`, `.venv-win/`, `plans/android-app/` y los
  cambios de T01-T06/T08 (backend) no se tocaron.

## Remediation History
None for the initial implementation.
