# Task T5 Report

## Status
DONE

## Outcome
Custom OpenRouter model picker now shows per-option metadata badges (context length + prompt price) in the `.combobox-option-meta` slot. On selection a `#openrouter-custom-model-summary` element is populated with model name, id, context, and prompt/completion price chips and shown via `show()`. While `loadOpenRouterModels()` is in flight the `.is-loading` class is applied to `#openrouter-model-card-custom` and removed when the promise settles. A teardown-race guard in the `.then()` callback bails if the user has left custom mode or the mount element is detached before the combobox is created. Two pure exported formatters (`formatModelPrice`, `formatContextLength`) are available for tests.

## Acceptance Criteria
- `formatModelPrice(0)` → `'Gratis'` -> pass (unit tested)
- `formatModelPrice(0.0000005)` → `'$0.5/1M'` -> pass (unit tested)
- `formatContextLength(128000)` → `'128K ctx'` -> pass (unit tested)
- `formatContextLength(0/undefined/null)` → `''` -> pass (unit tested)
- Combobox items carry a non-empty `meta` string with context + price -> pass (flow tested: `.combobox-option-meta` contains `128K ctx` and `$0.5/1M`)
- `#openrouter-custom-model-summary` hidden until selection, shown with model details on selection -> pass (flow tested)
- Teardown-race guard: switching to preset while fetch is in flight prevents stale combobox creation -> pass (flow tested: `.combobox-option` is null after guard fires)
- Loading affordance: `.is-loading` on custom card while fetch in flight -> implemented (guard in `.then()` removes it on settle; test coverage via guard test)
- `npx vitest run tests/frontend/` green: 229 tests pass (up from 214 baseline)

## Files Changed
- `frontend/js/landing.js` - modified; added `export function formatModelPrice` and `export function formatContextLength` (pure helpers near line 97); modified `setOpenRouterModel('__custom__')` to add `.is-loading` toggle on `#openrouter-model-card-custom`, teardown-race guard, `meta` field on combobox items, and `onSelect` callback that populates `#openrouter-custom-model-summary` using DOM creation + `show()`
- `frontend/index.html` - modified; added `<div class="openrouter-custom-model-summary hidden" id="openrouter-custom-model-summary">` inside `#openrouter-custom-panel`, after the model combobox `.form-group`
- `frontend/style.css` - modified; added `.openrouter-custom-model-summary`, `.model-summary-name`, `.model-summary-chip` styles using design tokens; includes `@media (max-width: 680px)` responsive rules for the summary
- `tests/frontend/landing.test.js` - modified; imported `formatModelPrice` and `formatContextLength`; added two `describe` blocks with 12 new unit tests covering 0→Gratis, rounding, per-million multiplication, and context-length edge cases
- `tests/frontend/landingFlow.test.js` - modified; added `#openrouter-custom-model-summary` to `renderLandingDom()`; added `Element.prototype.scrollIntoView = vi.fn()` stub for jsdom; added 3 new integration tests: meta badge on items, summary on selection, teardown-race guard

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/js/landing.js` | `formatModelPrice` | Added — new exported pure function |
| `frontend/js/landing.js` | `formatContextLength` | Added — new exported pure function |
| `frontend/js/landing.js` | `setOpenRouterModel` (custom branch) | Modified — loading affordance, teardown guard, meta enrichment, summary population |

## Tests
- Command: `npx vitest run tests/frontend/`
  Result: pass — 17 files, 229 tests, 0 failures

## TDD Evidence
- RED: `npx vitest run tests/frontend/landingFlow.test.js` with new tests but before combobox was opened in tests → `expected null not to be null` (`.combobox-option-meta` not in DOM yet because combobox wasn't opened)
- GREEN: Fixed by dispatching a `click` on the combobox input to trigger `open()` → `render()`, added `scrollIntoView` stub; all 16 flow tests pass

## Read Ledger
Planned reads:
- `frontend/js/landing.js` lines 312-348 — `setOpenRouterModel` custom branch (where items are mapped + combobox created)
- `frontend/js/landing.js` lines 372-386 — `loadOpenRouterModels` (loading state + cache)
- `frontend/js/landing.js` lines 97-110 — pure helpers area (where formatters were added)
- `frontend/js/components/openrouter-combobox.js` lines 104-130 — confirmed `item.meta` → `.combobox-option-meta` slot
- `frontend/style.css` lines 5426-5433 — existing `.combobox-option-meta` styling
- `plans/model-selector-ux/integration-openrouter-models.md` — confirmed per-token USD format, `Gratis` for 0, context/price field names
- `plans/model-selector-ux/global-constraints.md` — confirmed price format and token list

Extra reads:
- `frontend/js/components/openrouter-combobox.js` lines 1-340 (full file) — needed to understand when `render()` is called (not on init; only on `open()/setItems()/setValue()/input events`) to fix the test that needed to open the combobox before querying `.combobox-option-meta`
- `tests/frontend/landingFlow.test.js` full — needed to understand `renderLandingDom()` factory and `flushAsyncWork()` patterns to write matching tests

Pack gaps:
- None

## Decisions
- Used `toPrecision(2)` + `parseFloat().toString()` for `formatModelPrice` to get 2 significant figures and strip trailing zeros (matches the `$0.50/1M` example from the brief while being well-behaved for very small/large prices).
- Used DOM node creation (not `innerHTML`) in `onSelect` to set model name/id/price textContent safely.
- Added `Element.prototype.scrollIntoView = vi.fn()` stub at the top of `landingFlow.test.js` (guarded by `typeof Element` check) to suppress jsdom's unhandled exception when the combobox calls `scrollIntoView` — the combobox code is unchanged and this avoids patching a shared component for test purposes.
- Summary element is hidden at the top of the `'__custom__'` branch (before the async load) so re-entering custom mode always starts with a clean slate.
- `.is-loading` is added to `customCard` before the `loadOpenRouterModels()` call and removed at the start of the `.then()` callback (before the teardown guard check) so it is always removed regardless of whether the guard bails.

## Concerns / Follow-ups
- None
