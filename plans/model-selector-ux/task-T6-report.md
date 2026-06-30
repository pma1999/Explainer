# Task T6 Report

## Status
DONE

## Outcome
`localStorage` persistence of the model selector is implemented under key `explainer.modelSelector.v1`. Selections persist across SPA re-entries and page reloads. Validation prevents restoring corrupt data, unavailable providers, or invalid model IDs. The async custom-mode restore path chains off the `setOpenRouterModel('__custom__')` promise and mirrors the T5 teardown-race guard.

## Acceptance Criteria
- One key `explainer.modelSelector.v1` only → pass (single constant `SELECTOR_KEY`)
- `persistModelSelector()` exported, writes on every selection mutation → pass
- `restoreModelSelector()` exported, validates every field before applying → pass
- Never throws on corrupt/missing JSON → pass (try/catch, returns null on error)
- Provider availability fallback (openrouter/deepseek key missing → gemini) → pass
- `openrouterModel` validated via `isPresetOpenRouterModel`; invalid → `OPENROUTER_MODEL_MIMO_PRO` → pass
- `deepseekModel` validated via `isValidDeepSeekModel`; invalid → `DEEPSEEK_MODEL_V4_PRO` → pass
- `openrouterProviderOnly` coerced to boolean → pass
- Custom-mode restore drives `setOpenRouterModel('__custom__')`, chains `.then()`, sets combobox value + `currentCustomOpenRouterModel`, calls `fetchEndpointsForModel`, restores provider combobox + checkbox → pass
- Teardown-race guard on custom async restore → pass (verified by dedicated test)
- `restoreModelSelector()` call placed inside `initLanding` after setters, before final `syncExplainerProviderUI()` → pass
- No `persistModelSelector()` call inside `handleUpload`'s post-submit reset → pass (verified by code review)
- No new listeners outside `_landingListenersAttached` guard → pass (persist calls added to existing setter/handler bodies only)
- `npx vitest run tests/frontend/` green → pass (252/252)

## Files Changed
- `frontend/js/landing.js` — modified; added `SELECTOR_KEY` constant, exported `persistModelSelector()` and `restoreModelSelector()`, added persist calls to `setExplainerProvider`/`setOpenRouterModel` (preset + custom onSelect)/`setDeepSeekModel`/provider-only listener, updated provider combobox `onSelect` to track `currentOpenRouterProvider` + persist, changed `setOpenRouterModel` custom path to `return loadOpenRouterModels().then(...)` (removes stray `return;`), added restore block in `initLanding` before final `syncExplainerProviderUI()`
- `tests/frontend/landing.test.js` — modified; added `vi.hoisted` for `mockState`, added `vi.mock` stubs for `state.js`/`dom.js`/`api.js`/`storage.js`/`auth.js`, added `persistModelSelector / restoreModelSelector` describe block (13 unit tests: corrupt JSON, missing key, invalid provider, key-unavailable fallback, model validation, round-trips, custom pending return, boolean coercion)
- `tests/frontend/landingFlow.test.js` — modified; added `localStorage.clear()` to `beforeEach`, added `localStorage persistence (T6)` describe block (9 integration tests: save on selection, save on model/deepseek change, restore gemini/preset/deepseek, key-unavailable fallback, custom-mode restore, teardown-race guard)

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/js/landing.js` | `SELECTOR_KEY` | Added — `const SELECTOR_KEY = 'explainer.modelSelector.v1'` |
| `frontend/js/landing.js` | `persistModelSelector` | Added — exported function, writes current module vars to localStorage |
| `frontend/js/landing.js` | `restoreModelSelector` | Added — exported function, validates + restores from localStorage; returns `{pendingCustomModel, pendingProvider}` or null |
| `frontend/js/landing.js` | `setExplainerProvider` | Modified — adds `persistModelSelector()` at end |
| `frontend/js/landing.js` | `setOpenRouterModel` | Modified — custom path now `return loadOpenRouterModels().then(...)` (returns promise); `onSelect` adds `persistModelSelector()`; preset path adds `persistModelSelector()` |
| `frontend/js/landing.js` | `setDeepSeekModel` | Modified — adds `persistModelSelector()` at end |
| `frontend/js/landing.js` | provider combobox `onSelect` | Modified — adds `currentOpenRouterProvider = value` + `persistModelSelector()` |
| `frontend/js/landing.js` | provider-only `change` listener | Modified — adds `persistModelSelector()` |
| `frontend/js/landing.js` | `initLanding` | Modified — restore block + custom async continuation inserted before final `syncExplainerProviderUI()` |

## Tests
- Command: `npx vitest run tests/frontend/`
  Result: pass — 252/252 tests (17 suites)

## TDD Evidence
- RED: `npx vitest run tests/frontend/landing.test.js` → 1 failed suite (ReferenceError on `mockState` before `vi.hoisted` fix)
- GREEN: after `vi.hoisted()` fix → 252/252 pass

## Read Ledger
Planned reads:
- `plans/model-selector-ux/task-T6-brief.md` — full brief
- `plans/model-selector-ux/global-constraints.md` — constraints
- `frontend/js/landing.js` lines 1–33 (module vars), 307–370 (setters), 455–569 (listener guard + end), 312–348 (custom path)
- `tests/frontend/landing.test.js` — existing tests
- `tests/frontend/landingFlow.test.js` — existing tests + factory

Extra reads:
- `frontend/js/components/openrouter-combobox.js` — needed to understand `setValue` API (does not call `onSelect`, only sets input.value + re-renders). Risk: custom-mode restore display label.
- `frontend/js/landing.js` lines 524–580 — confirm exact whitespace around `return;` for edit tool
- `tests/frontend/setup.js` — confirm jsdom environment and stub pattern
- `vitest.config.js` — confirm `environment: 'jsdom'` and `globals: true`
- `frontend/js/landing.js` (full body) — several targeted reads to identify exact edit locations after prior edits shifted lines

Pack gaps:
- None

## Decisions
- `setOpenRouterModel('__custom__')` changed to `return loadOpenRouterModels().then(...)` (was `loadOpenRouterModels().then(...); return;`). The existing radio listeners ignore the return value; only the restore path uses it. This avoids a second `loadOpenRouterModels()` call that would race with the first.
- `currentOpenRouterProvider` now tracks the provider combobox value on `onSelect`. The `handleUpload` still reads `_openrouterProviderCombobox.getValue()` for the submit payload (unchanged). The tracked `currentOpenRouterProvider` is used only for persistence. Typed-but-not-selected provider values are not persisted (only selected values are); noted as minor limitation.
- Custom-mode display label: when restoring, we resolve the label via `_orModelsCache` (set by the time `.then()` runs) to show the model name instead of the raw ID in the combobox input.
- `vi.hoisted()` used in `landing.test.js` for `mockState` to avoid the TDZ error that occurs when `vi.mock` factory runs before `const` initialization (static import in the same file triggers this; `landingFlow.test.js` avoids it via dynamic imports).
- `localStorage.clear()` added to `landingFlow.test.js` `beforeEach` to prevent state leakage from persistence tests into provider-key-indicator tests.

## Concerns / Follow-ups
- Typed-but-not-selected provider values (user types in the provider combobox without picking from the dropdown) are not persisted because only `onSelect` triggers `persistModelSelector()`. This is acceptable for the current scope — the restore only applies to dropdown-confirmed selections.
