# Context Map: Model / Provider Selector UX

## Objective
Support a comprehensive UX redesign of the AI model + provider selector on the landing page (upload card). Covers all HTML surfaces, JS logic, CSS tokens, backend contracts, accessibility gaps, and risks.

---

## Codegraph Status
**Live** — 138 files indexed, 2774 nodes, 3750 edges. All structural lookups were resolved via codegraph. CSS/HTML queries fell back to grep (not AST-parsed).

---

## Relevant Areas

| Area | File | Symbol(s) | Contract / role | Read-hint | Why it matters |
|---|---|---|---|---|---|
| Landing init | `frontend/js/landing.js` | `initLanding()` | Top-level orchestrator: queries all DOM ids, attaches listeners idempotently via `_landingListenersAttached`, calls `syncExplainerProviderUI()` on load | lines 202–570 | Entry point for all selector logic |
| Provider UI sync | `frontend/js/landing.js` | `syncExplainerProviderUI()` | Writes `.selected`/`.disabled`/`.hidden` classes to all provider-card and model-card elements; renders provider hint text | lines 256–305 | Must be called after every state mutation |
| Provider selection | `frontend/js/landing.js` | `setExplainerProvider(provider)` | Sets `currentExplainerProvider` ∈ `{'gemini','openrouter','deepseek'}`, calls sync | line 307 | Drives which sub-panel is visible |
| OR model selection | `frontend/js/landing.js` | `setOpenRouterModel(model)` | `model === '__custom__'` triggers lazy combobox load + `loadOpenRouterModels()`; preset path resets combobox | lines 312–364 | Custom mode creates/destroys `_openrouterCombobox` on demand |
| DeepSeek model selection | `frontend/js/landing.js` | `setDeepSeekModel(model)` | Sets `currentDeepSeekModel` ∈ `{DEEPSEEK_MODEL_V4_PRO, DEEPSEEK_MODEL_V4_FLASH}` | line 366 | Simpler; no async fetch |
| Model combobox lazy init | `frontend/js/landing.js` | `loadOpenRouterModels()` | Fetches `GET /api/openrouter/models` → `{models:[{id,name,...}]}`, caches in `_orModelsCache`; on error shows `#openrouter-custom-fetch-error` | lines 372–386 | Only triggered when user picks "Personalizado" |
| Provider endpoint fetch | `frontend/js/landing.js` | `fetchEndpointsForModel(modelId)` | Fetches `GET /api/openrouter/models/endpoints?model=<id>` → `{providers:[str]}`, caches in `_orEndpointsCache[modelId]`; populates `_openrouterProviderCombobox` | lines 397–413 | Called after custom model combobox selection |
| Provider hint builder | `frontend/js/landing.js` | `buildExplainerProviderHint(sourceType, provider)` | Returns a descriptive string reading from `state.hasOpenRouterKey`, `state.hasMistralKey`, etc. | lines 156–200 | Long-form contextual hint under provider grid |
| Validation | `frontend/js/landing.js` | `validateExplainerProviderSelection({sourceType, provider, hasGeminiKey, ...})` | Returns error string or `null`; exported | lines 112–154 | Called on submit; also exported for tests |
| Submit handler | `frontend/js/landing.js` | `handleUpload()` | Builds `processPayload` from `currentExplainerProvider`, `currentOpenRouterMode`, `currentCustomOpenRouterModel`, `_openrouterProviderCombobox.getValue()`, `currentOpenRouterProviderOnly` | lines 609–729 | Final data flow: determines what reaches `/api/projects/{id}/process` |
| Target language setter | `frontend/js/landing.js` | `setTargetLanguage(language)` | Validates against `SUPPORTED_TARGET_LANGUAGES`, sets `currentTargetLanguage`, syncs `#target-language` value | lines 91–95 | Scoped to landing; resets to DEFAULT on submit |
| Combobox component | `frontend/js/components/openrouter-combobox.js` | `createCombobox(mountEl, options)` | Returns `{setItems, getValue, setValue, focus, destroy}`. Implements WAI-ARIA 1.2 combobox with keyboard nav (Arrow, Enter, Escape, Tab, Home, End). Filters up to 100 items. Attaches `document.click` for outside-close. | lines 24–337 | Reused for BOTH model combobox AND provider combobox |
| DOM helpers | `frontend/js/dom.js` | `$`, `show`, `hide`, `toast` | `$(id)` = `getElementById`; `show/hide` toggle `.hidden` class; `toast(msg, type)` appends to `#toast-container` | lines 5–7, 51 | Used throughout landing.js |
| App state | `frontend/js/state.js` | `state` object | Holds `hasApiKey`, `hasOpenRouterKey`, `hasMistralKey`, `hasDeepSeekKey`, `hasTavilyKey`, `user` | read from `state.js` | Provider hint and validation read these |
| HTML: Provider grid | `frontend/index.html` | `#explainer-provider-group` → `#provider-card-gemini/openrouter/deepseek` | 3 radio-backed `<label class="provider-card">` in `.provider-grid` (2-col). Radio inputs are `position:absolute;opacity:0` (visually hidden) | lines 238–260 | Top-level provider picker surface |
| HTML: OR model sub-panel | `frontend/index.html` | `#openrouter-model-panel` → `#openrouter-model-grid` | 4 provider-cards: pro / standard / deepseek / custom. Hidden until OR is selected. | lines 261–324 | Second-level model picker for OpenRouter |
| HTML: Custom panel | `frontend/index.html` | `#openrouter-custom-panel` | Contains `#openrouter-custom-model-combobox` (mount point), `#openrouter-provider-combobox` (mount point), `#openrouter-provider-only` checkbox, loading/error elements | lines 293–323 | Tertiary level; only shown in custom mode |
| HTML: DeepSeek sub-panel | `frontend/index.html` | `#deepseek-model-panel` → `#deepseek-model-group` | 2 cards: pro / flash | lines 325–343 | Second-level for DeepSeek provider |
| HTML: Hint + error bar | `frontend/index.html` | `#explainer-provider-hint`, `#explainer-provider-error` | Plain `<p>` tags below provider grid; hint is always visible, error is `.hidden` by default | lines 344–347 | UX feedback zone |
| CSS: Provider grid | `frontend/style.css` | `.provider-grid`, `.provider-card`, `.provider-card.selected`, `.provider-card.disabled` | 2-col grid; card min-height 90px; selected → amber border + `amber-dim` gradient bg; disabled → opacity 0.45 + grayscale + pointer-events:none | lines 651–730 | Visual state machine for card selection |
| CSS: Model sub-panel | `frontend/style.css` | `.openrouter-model-panel`, `.openrouter-model-grid .provider-card` | Inset panel with border + subtle bg; model cards min-height 82px | lines 716–730 | Nesting container for model cards |
| CSS: Combobox | `frontend/style.css` | `.combobox-wrapper`, `.combobox-input`, `.combobox-listbox`, `.combobox-option`, `.combobox-option-name`, `.combobox-option-id`, `.combobox-option-meta` | Listbox: absolute, max-height 320px, z-index 100, fade+slide animation (respects `prefers-reduced-motion`); option: 3-col flex (name/id/meta) | lines 5173–5327 | Combobox visual; transitions already match Scholarly Forge |
| CSS: Design tokens | `frontend/style.css` `:root` | `--bg-base:#0d1117`, `--bg-surface:#161b22`, `--bg-elevated:#1f2937`, `--amber:#f59e0b`, `--amber-dim:rgba(245,158,11,0.12)`, `--border:#2d3748`, `--font-ui:'Syne'`, `--font-display:'Playfair Display'`, `--font-body:'Crimson Pro'`, `--text-primary:#f0ece3`, `--text-secondary:#9ca3af`, `--text-muted:#6b7280` | lines 7–30 | Scholarly Forge token set — all redesign work must use these |
| Backend: process endpoint | `main.py` | `api_process_project` `POST /api/projects/{id}/process` | Accepts `ProcessProjectRequest` body: `{explainer_provider, openrouter_model?, deepseek_model?, target_language, openrouter_provider?, openrouter_provider_only?}` | line 3795 | Data contract for the submit path |
| Backend: ProcessProjectRequest | `main.py` | `ProcessProjectRequest` (Pydantic) | Fields: `explainer_provider: Literal["gemini","openrouter","deepseek"]`, `openrouter_model: str|None`, `deepseek_model: Literal["deepseek-v4-pro","deepseek-v4-flash"]|None`, `target_language: str = "es-ES"`, `openrouter_provider: str|None`, `openrouter_provider_only: bool = False` | lines 179–185 | Full shape the frontend must post |
| Backend: models endpoint | `main.py` | `get_openrouter_models` `GET /api/openrouter/models` | Returns `{models:[{id,name,context_length,prompt_price,completion_price}], stale:bool, fetched_at:str}` | lines 4188–4196 | Used by custom combobox; cached |
| Backend: endpoints API | `main.py` | `get_openrouter_endpoints` `GET /api/openrouter/models/endpoints?model=<id>` | Returns `{providers:[str], stale:bool}`; validates `author/slug` format | lines 4199–4210 | Used to auto-populate provider combobox |
| Backend: model validation | `main.py` | `_resolve_explainer_model(provider, openrouter_model, deepseek_model)` | Validates custom model format with `re.fullmatch(r"[\w.-]+/[\w.:-]+", model)`, max 128 chars | lines 188–213 | Server-side guard matching frontend's `isValidOpenRouterModel` |
| Backend: provider routing | `main.py` | `_build_openrouter_provider_routing(provider, only)` | Converts provider string + only-bool into OpenRouter routing dict | line 216 | Backend side of provider routing |

---

## Existing Patterns To Reuse

- **Idempotent listener guard**: `_landingListenersAttached` boolean flag in `landing.js` (line 33); `if (!_landingListenersAttached) { _landingListenersAttached = true; ... }` at line 455. Any new listeners must go inside this block.
- **`createCombobox` API** (`frontend/js/components/openrouter-combobox.js`): `{setItems(newItems), getValue(), setValue(val), focus(), destroy()}`. Already handles keyboard nav, ARIA, click-outside. Reuse for any new searchable pickers rather than building a new one.
- **`show(el)` / `hide(el)`** (`dom.js` lines 6–7): Toggle `.hidden` class. Never use `el.style.display` directly.
- **`toast(msg, type)`** (`dom.js` line 51): Appends to `#toast-container`. Types: `''`, `'success'`, `'error'`.
- **`$(id)`** shorthand: `document.getElementById`. Used throughout.
- **Design token set**: All colors, fonts, spacing at `:root` in `style.css` lines 7–30. New CSS must reference only these vars.
- **Provider-card pattern**: `<label class="provider-card" id="..." for="radio-id"><input type="radio" .../><span class="provider-card-main"><span class="provider-card-title">...</span><span class="provider-card-sub">...</span></span></label>`. The radio is hidden; the label is the clickable surface. JS adds `.selected`/`.disabled` classes.
- **`_orModelsCache` / `_orEndpointsCache`** in `landing.js`: In-memory caches for API calls; reset on module reload. Any new fetch-based picker should follow the same pattern.
- **`formatProviderLabel(slug)`** (line 388): `slug.charAt(0).toUpperCase() + slug.slice(1).replace(/-/g, ' ')`. Reuse for any provider display label.
- **`landingFlow.test.js`** DOM factory: `renderLandingDom()` (line 41) builds a complete mock DOM. Extend this for new elements; do not duplicate the factory.
- **`state` object** (`state.js`): Read-only from landing's perspective — holds all API key flags (`hasApiKey`, `hasOpenRouterKey`, `hasMistralKey`, `hasDeepSeekKey`, `hasTavilyKey`). Never mutate from landing.

---

## Tests And Verification Entry Points

- **`tests/frontend/landingFlow.test.js`**: Primary test file for the selector. 7 test cases covering: idempotent listener registration, target language reset, custom panel show/hide, submit blocked without model, payload shape for custom model + provider, payload for preset mode, fetch-error fallback. Run with `npx vitest run tests/frontend/landingFlow.test.js`.
- **`tests/frontend/landing.test.js`**: Simpler tests for exported pure functions (`isValidOpenRouterModel`, `isPresetOpenRouterModel`, `isExplainerProviderSupportedForSource`, `validateExplainerProviderSelection`).
- **`tests/e2e/app.spec.js`**: Playwright E2E tests covering the landing flow end-to-end.
- **Run all frontend unit tests**: `npx vitest run tests/frontend/`
- **`tests/backend/test_main_helpers_v2.py`**: Tests `_build_openrouter_provider_routing`, `_resolve_explainer_model`. Run with `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py`.

---

## Integration / Data Contracts

### POST `/api/projects/{id}/process` — Submit payload
```
{
  "explainer_provider": "gemini" | "openrouter" | "deepseek",
  "openrouter_model": "author/slug" | null,     // required when provider=openrouter
  "deepseek_model": "deepseek-v4-pro" | "deepseek-v4-flash" | null,
  "target_language": "es-ES" | "en" | "fr" | "de" | "it" | "pt-PT",
  "openrouter_provider": "<slug>" | null,        // only in custom mode
  "openrouter_provider_only": false              // only in custom mode
}
```

### GET `/api/openrouter/models`
Returns `{models: [{id: str, name: str, context_length: int, prompt_price: float, completion_price: float}], stale: bool}`. Used to populate the custom model combobox.

### GET `/api/openrouter/models/endpoints?model=<author/slug>`
Returns `{providers: [str], stale: bool}`. Used to populate the provider combobox after model selection.

### Backend model format validation
Custom model strings must match `re.fullmatch(r"[\w.-]+/[\w.:-]+", model)` and be ≤ 128 chars. The frontend enforces `isValidOpenRouterModel` only for preset IDs; arbitrary custom strings are sent as-is and validated server-side.

### Preset model constants (frontend ↔ backend must agree)
```
OPENROUTER_MODEL_MIMO_PRO  = "xiaomi/mimo-v2.5-pro"
OPENROUTER_MODEL_MIMO      = "xiaomi/mimo-v2.5"
OPENROUTER_MODEL_DEEPSEEK  = "deepseek/deepseek-v4-pro"
DEEPSEEK_MODEL_V4_PRO      = "deepseek-v4-pro"
DEEPSEEK_MODEL_V4_FLASH    = "deepseek-v4-flash"
```
Backend `OPENROUTER_EXPLAINER_MODELS` frozenset (`main.py` line 161) must stay in sync with frontend constants.

---

## Accessibility & State Gaps

1. **ARIA role duplication on combobox**: `openrouter-combobox.js` sets `role="combobox"` on BOTH the `<div>` wrapper AND the `<input>`. WAI-ARIA 1.2 requires `role="combobox"` only on the input; the container should use no role or `role="group"`. (line 42–43 vs 48 in combobox.js)
2. **Provider hint has no live region**: `#explainer-provider-hint` is a plain `<p>`; when it changes (e.g., switching from Gemini to OpenRouter), screen readers don't announce it. Needs `aria-live="polite"`.
3. **Provider error has no live region**: `#explainer-provider-error` similarly has no `aria-live="assertive"`.
4. **No selection state persisted**: `currentExplainerProvider`, `currentOpenRouterModel`, `currentDeepSeekModel` are all ephemeral module-level vars. If the user navigates away and returns (SPA route), state resets to default. No `localStorage` persistence.
5. **Inline styles on provider-only checkbox**: `#openrouter-provider-only` and its label are styled with `style=""` attributes (`index.html` line 310–315). Should use a CSS class matching existing `.checkbox-label` pattern.
6. **Inconsistent card inner structure**: Preset provider cards use `.provider-card-main > .provider-card-title + .provider-card-sub`; the "Personalizado" card uses `.provider-card-content > .provider-card-title + .provider-card-desc`. This inconsistency complicates CSS targeting.
7. **No keyboard shortcut to reach provider grid**: Users tabbing through the form reach the provider radio inputs but the visual card pattern (with hidden radios) doesn't give visual focus rings unless a `focus-visible` rule is added to `.provider-card`.
8. **Provider combobox initialized empty, relies on model combobox selection**: The provider combobox (`_openrouterProviderCombobox`) is always initialized with `items: []` and placeholder "Selecciona un modelo primero…". It gets populated only after `onSelect` fires in the model combobox. If the user manually types a provider slug before picking a model, that text is silently discarded on `commitOption` calls.
9. **No confirmation of API key presence inline**: Validation errors for missing keys only appear at submit time (via `validateExplainerProviderSelection`). No inline indicator on provider cards that a key is missing.
10. **Mobile breakpoint**: `.provider-grid` goes to 1-col at `max-width: 680px` (`style.css` line 2741), but the 4-model OpenRouter grid (`.openrouter-model-grid`) also collapses; the "Personalizado" card with its custom panel would stack deeply on mobile with no height control.
11. **No loading state on provider card click**: Switching to OpenRouter + Custom triggers an async model fetch, but there is no visible loading indicator on the card itself — only `#openrouter-custom-loading` inside the now-revealed custom panel.

---

## Named Risks

- **SSE pipeline coupling**: `handleUpload` calls `POST /api/projects` then immediately `POST /api/projects/{id}/process`. The process call starts the SSE pipeline. Any UI change that delays or re-orders these calls could leave a project stuck. Do not add async gaps between them.
- **`_openrouterCombobox` teardown**: `setOpenRouterModel` calls `_openrouterCombobox.destroy()` then sets it to `null` before creating a new one. If `loadOpenRouterModels` is still in-flight (slow network) when the user switches back to a preset, the `.then()` callback runs with a stale `mountEl` after `destroy()` has cleared it. Verify JSDOM behavior in tests.
- **`document.addEventListener('click', onDocumentClick)`**: Each `createCombobox` call attaches a document-level click listener. `destroy()` removes it. But `_openrouterCombobox` is destroyed and re-created each time custom mode is toggled (lines 319–321). Multiple rapid toggles could accumulate listeners if `destroy()` is not called before re-creation. Current code calls `destroy()` before new creation — verify this in test coverage.
- **Module-level state survives hot-reload in dev**: `_landingListenersAttached`, `_orModelsCache`, `_openrouterCombobox` are module globals. Vite HMR may or may not reset them. The idempotency guard works correctly in production but can mask stale state during development.
- **Backend preset model frozenset drift**: `OPENROUTER_EXPLAINER_MODELS` in `main.py` line 161 is separate from the frontend constants. If a new preset model is added on the frontend without updating the backend frozenset, the model will pass frontend validation but may fail server-side checks in `_resolve_explainer_model`. No automated cross-language test guards this.
- **Provider combobox `getValue()` reads raw input text**: `handleUpload` calls `_openrouterProviderCombobox.getValue().trim()` (line 693–695) which returns the input's text content, not necessarily a committed `selectedValue`. If the user types a partial string without selecting from the dropdown, it gets sent as `openrouter_provider`. Backend does lowercase+strip but no strict format validation on provider slugs (`_build_openrouter_provider_routing` line 219).

---

## Open Unknowns

- **No user-visible model metadata in preset cards**: The preset cards show only a human label and brief description. The models endpoint returns `context_length`, `prompt_price`, `completion_price` but none of these are displayed. It is unknown whether the redesign should surface pricing/context info inline (requires design decision).
- **Target language UI position**: The language selector (`#target-language`, a `<select>`) sits above the provider grid in the form, but the hint text it generates is not contextually linked. Whether to move it or keep it is a layout decision.
- **Whether `openrouter_provider_hint` text (line 305) should react to typing in the provider combobox**: Currently it is static. Whether it should update with validation feedback as the user types is unknown.
