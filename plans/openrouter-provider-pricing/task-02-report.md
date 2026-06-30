# Task 02 Report

## Status
DONE

## Outcome
The custom OpenRouter model path is now provider-aware. The model combobox keeps using model-list aggregate metadata and shows a `Modelo (agregado)` chip until a provider endpoint is selected. The provider combobox consumes Task 01's rich `endpoints[]` rows: each option's `value` is the canonical endpoint `tag`, its label is `provider_name`, its sublabel is the `tag`, and its `meta` slot shows endpoint context, max completion/max prompt tokens, and endpoint input/output prices. Selecting (or restoring) a provider endpoint by `tag` switches the summary to a `Proveedor exacto` chip with endpoint-specific data, and the process payload submits the endpoint `tag` for `openrouter_provider` — not the displayed `provider_name`. Manual typed providers still submit the typed text and keep aggregate chips. Restore refetches endpoints and re-matches the persisted `tag`. Preset cards are untouched.

## Acceptance Criteria
- Custom model combobox items keep using model-list aggregate `context_length`, `prompt_price`, `completion_price` -> pass (`formatProviderItems`/model combobox `meta` unchanged; `populates and shows #openrouter-custom-model-summary` test still asserts model-list ctx/price).
- Selected custom model with no provider endpoint shows `Modelo (agregado)` chip + model metadata -> pass (`populates and shows...` and `manual typed provider keeps aggregate chips` tests assert `/Modelo \(agregado\)/` and `/Proveedor exacto/` negation).
- `fetchEndpointsForModel()` consumes backend `endpoints` rows and caches endpoint objects by model ID -> pass (`_orEndpointsCache[modelId] = endpoints`; `Array.isArray(data && data.endpoints)`; restore tests assert endpoints refetch).
- Provider combobox items use `value`=tag, `label`=provider_name, `sublabel`=tag, `meta`=endpoint context + max completion (when present) + max prompt (when present) + endpoint input/output prices -> pass (`renders provider combobox option with endpoint tag, provider_name and rich meta`).
- Selecting a provider endpoint updates provider state to the `tag`, uses existing combobox metadata rendering, and updates summary chips with exact endpoint data including endpoint max token limits when present -> pass (`selecting a provider endpoint shows Proveedor exacto summary...`).
- Process payload sends endpoint `tag` for `openrouter_provider`, not the displayed provider label -> pass (same test asserts `openrouter_provider: "novita/fp8"` while input display is `Novita`).
- Manual typed provider still submits the typed value and keeps aggregate chips -> pass (`manual typed provider keeps aggregate chips and submits the typed value` asserts `openrouter_provider: "deepseek"` + `/Modelo \(agregado\)/`).
- Restore refetches endpoints for the saved custom model, re-matches the persisted provider by `tag`, updates the provider combobox display label, and renders endpoint-specific summary chips; if the saved tag is not returned, restores the tag as manual text and renders aggregate chips -> pass (`restore custom mode with saved provider tag...` and `restore with a saved provider tag that is not in endpoint rows...`).
- Static preset cards remain unchanged -> pass (no preset-card code touched; all preset tests green).

## Files Changed
- `frontend/js/landing.js` - modified
  - Added module state `currentOpenRouterProviderEndpoint` (endpoint row matched by tag, or null) and `currentCustomOpenRouterModelMeta` (chosen model aggregate metadata); updated `_orEndpointsCache` comment to `modelId -> [endpoint row objects]`.
  - Added exported helpers `formatEndpointMeta(endpoint)` and `buildEndpointSummaryChips(endpoint)`, plus internal `formatMaxTokens(n, suffix)` and `formatEndpointPriceSegment(endpoint)`.
  - Added module-level `renderCustomModelSummary()` that renders `Proveedor exacto` + endpoint chips or `Modelo (agregado)` + aggregate chips.
  - Provider combobox `onSelect(value, item)` now stores `item.endpoint` and calls `renderCustomModelSummary()`; added a manual-edit `input` listener on the provider combobox input that clears endpoint metadata and reverts the summary to aggregate on typed edits.
  - Model combobox `onSelect` now stores `currentCustomOpenRouterModelMeta`, clears provider state, and calls `renderCustomModelSummary()` instead of inline rendering.
  - `setOpenRouterModel` preset branch clears custom model meta and provider state.
  - `fetchEndpointsForModel()` now consumes `data.endpoints`, caches endpoint rows, and returns them.
  - `formatProviderItems(endpoints)` maps endpoint rows to `{ value: tag, label: provider_name, sublabel: tag, meta: formatEndpointMeta(endpoint), endpoint }`; removed the now-unused `formatProviderLabel()`.
  - Restore continuation is now `async`, `await`s `fetchEndpointsForModel`, re-matches the saved provider by `tag`, sets the provider combobox display to `provider_name` (or to the saved tag as manual text when unmatched), and renders the matching summary chips; a second teardown-race guard runs after the await.
  - `handleUpload()` submits `currentOpenRouterProvider` (canonical tag or manual text) instead of `getValue()`; resets provider/endpoint state after upload.
- `frontend/style.css` - modified
  - Added `.model-summary-chip--label` modifier (amber accent, UI font, bold) to visually distinguish the `Modelo (agregado)` / `Proveedor exacto` source-label chip from data chips.
- `tests/frontend/landing.test.js` - modified
  - Imported `formatEndpointMeta` and `buildEndpointSummaryChips`; added `describe('formatEndpointMeta')` (7 tests) and `describe('buildEndpointSummaryChips')` (5 tests) covering context-only, context + max completion/max prompt, input/output pricing, all-segments join, pricing-omitted-when-absent, falsy endpoint, non-positive max tokens, full-row chips, absent-values-no-misleading-exact-chip, and tag-fallback cases.
- `tests/frontend/landingFlow.test.js` - modified
  - Updated two stale `{ providers: [] }` endpoint mocks to `{ endpoints: [] }` (Task 01 contract) and extended the summary test with `Modelo (agregado)` + price assertions.
  - Added `describe('provider endpoint hydration (Task 02)')` with 4 tests: provider combobox option metadata; select endpoint -> exact summary + submit canonical tag; manual typed provider -> aggregate + submit typed; edit-after-select reverts to aggregate.
  - Added 2 restore tests in the persistence describe: saved tag in endpoints -> exact chips + `provider_name` display + persisted tag; saved tag not in endpoints -> manual text + aggregate chips.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/js/landing.js` | `currentOpenRouterProviderEndpoint` | New module var; endpoint row matched by tag, or null for manual text. |
| `frontend/js/landing.js` | `currentCustomOpenRouterModelMeta` | New module var; chosen model object for aggregate summary rendering. |
| `frontend/js/landing.js` | `_orEndpointsCache` | Comment/type updated from `[provider slugs]` to `[endpoint row objects]`. |
| `frontend/js/landing.js` | `formatMaxTokens()` | New internal helper; `NNK <suffix>` or `''` for absent/non-positive values. |
| `frontend/js/landing.js` | `formatEndpointPriceSegment()` | New internal helper; `$/1M in · $/1M out`, or `''` when both prices are non-positive. |
| `frontend/js/landing.js` | `formatEndpointMeta()` | New exported helper; combobox `meta` slot string for an endpoint row. |
| `frontend/js/landing.js` | `buildEndpointSummaryChips()` | New exported helper; exact-mode summary chip texts, omitting absent values and absent pricing. |
| `frontend/js/landing.js` | `renderCustomModelSummary()` | New module-level function; renders `Proveedor exacto` or `Modelo (agregado)` summary. |
| `frontend/js/landing.js` | provider combobox `onSelect(value, item)` | Now stores `item.endpoint`, renders exact summary, persists the tag. |
| `frontend/js/landing.js` | provider combobox manual-edit listener | New; clears endpoint metadata and reverts summary to aggregate on typed edits. |
| `frontend/js/landing.js` | model combobox `onSelect` | Stores `currentCustomOpenRouterModelMeta`, clears provider state, calls `renderCustomModelSummary()`. |
| `frontend/js/landing.js` | `setOpenRouterModel` preset branch | Clears custom model meta and provider state. |
| `frontend/js/landing.js` | `fetchEndpointsForModel()` | Consumes `data.endpoints`, caches endpoint rows, returns them. |
| `frontend/js/landing.js` | `formatProviderItems()` | Maps endpoint rows to combobox items keyed by `tag` with endpoint meta + `endpoint` payload. |
| `frontend/js/landing.js` | `formatProviderLabel()` | Removed (dead after `formatProviderItems` rewrite). |
| `frontend/js/landing.js` | restore continuation | `async`; `await`s endpoint refetch, re-matches by `tag`, sets display + exact/aggregate chips, second teardown guard. |
| `frontend/js/landing.js` | `handleUpload()` | Submits `currentOpenRouterProvider` (tag/manual text) instead of `getValue()`; resets provider state after upload. |
| `frontend/style.css` | `.model-summary-chip--label` | New modifier for the aggregate/exact source-label chip. |

## Tests
- Command: `npx vitest run tests/frontend/landing.test.js tests/frontend/landingFlow.test.js`
  Result: pass — 101 passed (0 failed). `landing.test.js` 69 tests (+12 helper), `landingFlow.test.js` 32 tests (+6 flow/restore).

## TDD Evidence
- RED: Temporarily reverted `handleUpload()` to the old `getValue().trim()` behavior and ran the submit-tag test. It failed for the expected reason: `openrouter_provider: "Novita"` (the displayed `provider_name`) instead of the expected `"novita/fp8"` (the canonical `tag`). This confirms the test encodes the Named Risk that `createCombobox().getValue()` returns the displayed text, not the routing key.
- GREEN: Restored the canonical-tag logic (`currentOpenRouterProvider`) and re-ran the full suite -> 101 passed.

## Read Ledger
Planned reads:
- `plans/openrouter-provider-pricing/task-02-brief.md` (full) — scope, acceptance criteria, context pack, named risks, required test coverage.
- `plans/openrouter-provider-pricing/global-constraints.md` (full) — `tag` is the canonical routing key; consume `endpoints[]` not `providers`; persist `tag` or manual text; refetch + match on restore; no new persistence key.
- `plans/openrouter-provider-pricing/task-01-report.md` (full) — confirmed backend now returns `{ model_id, model_name, endpoints[], stale }` keyed by `tag`; do not change backend.
- `frontend/js/landing.js` (full) — module state, `persistModelSelector`/`restoreModelSelector`, provider combobox setup, `setOpenRouterModel('__custom__')`, `fetchEndpointsForModel`/`formatProviderItems`, restore continuation, `handleUpload`.
- `frontend/js/components/openrouter-combobox.js` (full) — confirmed `onSelect(item.value, item)` passes the full item; `setValue()`/`commitOption` set `input.value` directly (no `input` event), so a manual-edit listener is safe; `getValue()` returns displayed text.
- `tests/frontend/landingFlow.test.js` (full) — DOM fixture, mock pattern, combobox interaction pattern (click to open, mousedown to commit), flush helper, existing custom-panel/restore tests.
- `tests/frontend/landing.test.js` (full) — formatter test style, `vi.hoisted` mock pattern, restore round-trip pattern.
- `frontend/js/api.js` — confirmed `api()` is a thin fetch wrapper returning JSON.
- `plans/openrouter-provider-pricing/integration-openrouter.md` — verified endpoint field names, `tag` semantics, pricing/context gotchas.
- `vitest.config.js` / `package.json` — confirmed jsdom env, setup file, `npx vitest run` invocation.
- `frontend/style.css` (relevant sections) — confirmed `.model-summary-chip` flex-wrap layout handles extra chips; chose a minimal amber label modifier.

Extra reads:
- None beyond the planned set.

Pack gaps:
- None.

## Decisions
- Submit `currentOpenRouterProvider` (module state) rather than `_openrouterProviderCombobox.getValue()` because `getValue()` returns the displayed `provider_name`, which is not a valid routing key. The module var is kept in sync: provider `onSelect` sets it to the `tag`; the manual-edit `input` listener sets it to the typed text. This satisfies the Named Risk without modifying the combobox component (per the brief's "do not touch" constraint).
- Detected manual edits via an `input` listener attached directly to the provider combobox's `<input>` (after `createCombobox`) rather than by extending `openrouter-combobox.js`. `commitOption`/`setValue` assign `input.value` directly and do not fire an `input` event, so option selections and restore never trigger the manual-edit path. This keeps the combobox component untouched and satisfies the "clear endpoint metadata on manual edit" Named Risk.
- `formatEndpointPriceSegment` and `buildEndpointSummaryChips` omit the pricing chip entirely when both prompt and completion prices are non-positive. Task 01's `_safe_float` defaults absent pricing to `0.0`, so `0` is treated as "absent" on the frontend and never labelled as exact, satisfying the Named Risk. A genuinely-free endpoint (both prices `0`) also omits the price chip — prioritizing "not misleading" over completeness.
- Added a `.model-summary-chip--label` CSS modifier (amber accent) so the `Modelo (agregado)` / `Proveedor exacto` source label is visually distinct from data chips, supporting the brief's "clear `Modelo (agregado)` chip" wording. The existing flex-wrap layout already accommodated the extra chips; this is a minimal visual-only addition.
- Restore now `await`s `fetchEndpointsForModel` and re-matches the saved provider by `tag` against the refetched endpoint rows, with a second teardown-race guard after the await. If the tag is not found, the saved value is restored as manual text and the summary stays aggregate — matching the global constraint to not trust stale display metadata from localStorage.
- Removed the now-unused `formatProviderLabel()` helper to keep the file free of dead code.

## Concerns / Follow-ups
- Task 01's `_safe_float` collapses "absent" and "free" pricing both to `0.0`, so an endpoint that is genuinely free (both prices `0`) will not show a price chip in the exact summary, while the aggregate model summary shows `Gratis`. This is the intended "not misleading" trade-off per the Named Risk. If distinguishing free-vs-absent becomes important later, the backend would need to expose a pricing-present signal — out of scope for Task 02.
- The manual-edit `input` listener calls `persistModelSelector()` on every keystroke. This matches the existing onSelect persistence pattern and localStorage writes are already wrapped in try/catch, but it does mean rapid typing writes localStorage repeatedly. Not a real concern at this scale; noting for awareness only.
