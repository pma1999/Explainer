# Task 02: Frontend Provider Endpoint Hydration

## Goal
Hydrate the custom OpenRouter model path with endpoint-level provider metadata, while keeping model-level aggregate data clearly labeled until a provider endpoint is selected.

## Acceptance Criteria
- Custom model combobox items keep using model-list aggregate `context_length`, `prompt_price`, and `completion_price`.
- When a custom model is selected and no provider endpoint is selected, `#openrouter-custom-model-summary` shows model metadata with a clear `Modelo (agregado)` chip.
- `fetchEndpointsForModel()` consumes backend `endpoints` rows and caches endpoint objects by model ID.
- Provider combobox items use:
  - `value`: endpoint `tag`
  - `label`: endpoint `provider_name`
  - `sublabel`: endpoint `tag`
  - `meta`: endpoint context, max completion tokens when present, max prompt tokens when present, and endpoint input/output prices
- Selecting a provider endpoint updates current provider state to the endpoint `tag`, uses existing combobox metadata rendering, and updates summary chips with exact endpoint data, including endpoint max token limits when present.
- The process payload sends endpoint `tag` for `openrouter_provider`, not the displayed provider label.
- Manual provider text remains possible. If the typed value does not match an endpoint row, submit that text as before and keep summary chips on aggregate model data.
- Restore flow refetches endpoints for the saved custom model, re-matches the persisted provider by `tag`, updates the provider combobox display label, and renders endpoint-specific summary chips. If the saved tag is not returned, restore the tag as manual text and render aggregate chips.
- Static preset cards remain unchanged.

## Scope
Touch:
- `frontend/js/landing.js`
  - module state around OpenRouter provider/endpoint selection
  - `persistModelSelector()`
  - `restoreModelSelector()`
  - `initLanding()` provider combobox setup
  - `setOpenRouterModel('__custom__')`
  - `fetchEndpointsForModel()`
  - `formatProviderItems()`
  - `handleUpload()`
- `tests/frontend/landing.test.js`
  - pure helper or restore validation coverage if new helpers are exported
- `tests/frontend/landingFlow.test.js`
  - custom model summary, provider combobox, payload, and restore coverage
- `frontend/style.css` only if current summary chip layout cannot handle the new labels

Do not touch:
- `frontend/index.html` preset card copy except test DOM fixtures if needed
- `frontend/js/components/openrouter-combobox.js` unless there is no safe way to preserve canonical tag selection with the existing `onSelect(value, item)` callback
- `main.py` beyond consuming Task 01's already-implemented response
- any processing worker files

## Constraints
- Provider endpoint identity is `tag`.
- `openrouterProvider` in localStorage is a tag or manual typed value, not `provider_name`.
- Do not add a new localStorage key.
- Use existing `formatModelPrice()` and `formatContextLength()`.
- Use the existing combobox `meta` slot for endpoint metadata.
- Provider-specific summary chips are exact only after an endpoint row is selected or restored by matching `tag`.
- Keep preset cards static and curated.

## Interfaces
Consumes:
- Task 01 backend endpoint response:

```json
{
  "model_id": "qwen/qwen3.6-plus",
  "model_name": "Qwen 3.6 Plus",
  "endpoints": [
    {
      "tag": "novita/fp8",
      "provider_name": "Novita",
      "name": "Novita | qwen/qwen3.6-plus",
      "context_length": 128000,
      "max_completion_tokens": 16384,
      "max_prompt_tokens": 120000,
      "pricing": { "prompt": "0.0000005", "completion": "0.0000015" },
      "prompt_price": 0.0000005,
      "completion_price": 0.0000015,
      "supported_parameters": ["tools"],
      "supports_implicit_caching": true,
      "status": 0
    }
  ],
  "stale": false
}
```

- Existing combobox selection callback: `onSelect(value, item)`.
- Existing summary chip classes: `.model-summary-name` and `.model-summary-chip`.

Produces:
- Provider combobox item shape:

```js
{
  value: endpoint.tag,
  label: endpoint.provider_name || endpoint.tag,
  sublabel: endpoint.tag,
  meta: "128K ctx · 16K max out · 120K max in · $0.5/1M in · $1.5/1M out",
  endpoint
}
```

- Submit payload for selected endpoint:

```json
{
  "explainer_provider": "openrouter",
  "target_language": "es-ES",
  "openrouter_model": "qwen/qwen3.6-plus",
  "openrouter_provider": "novita/fp8",
  "openrouter_provider_only": true
}
```

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/js/landing.js` | module selector state | around lines 23-35 | Add transient selected endpoint metadata without changing persisted schema. |
| `frontend/js/landing.js` | `persistModelSelector()` and `restoreModelSelector()` | around lines 139-221 | Provider restore currently stores only a string and returns `pendingProvider`. |
| `frontend/js/landing.js` | provider combobox setup in `initLanding()` | around lines 351-361 | Existing `onSelect(value)` persists provider; update to use `item` endpoint metadata. |
| `frontend/js/landing.js` | `setOpenRouterModel('__custom__')` | around lines 460-555 | Chosen model summary and endpoint fetch are built here. |
| `frontend/js/landing.js` | `fetchEndpointsForModel()` and `formatProviderItems()` | around lines 585-614 | Current loss point on frontend: expects `providers: string[]`. |
| `frontend/js/landing.js` | restore continuation | around lines 762-791 | Must refetch endpoints, re-match saved tag, then set provider display and summary. |
| `frontend/js/landing.js` | `handleUpload()` | around lines 914-925 | Must send canonical tag for selected endpoint, while preserving manual typed provider fallback. |
| `frontend/js/components/openrouter-combobox.js` | `createCombobox()` | around lines 18-24 and 177-188 | Existing component passes selected `item` to `onSelect`; prefer not to modify it. |
| `tests/frontend/landingFlow.test.js` | custom model panel tests | around lines 223-550 | Extend existing combobox, summary, and payload tests. |
| `tests/frontend/landingFlow.test.js` | restore tests | around lines 770-808 | Extend restore to assert endpoint refetch and saved tag match. |
| `tests/frontend/landing.test.js` | formatter and restore tests | around lines 299-356 and 546-560 | Add helper/restore assertions if new helpers are exported. |

## Existing Patterns To Reuse
- Build summary chips with `document.createElement('span')`, `model-summary-name`, and `model-summary-chip` as currently done in `setOpenRouterModel('__custom__')`.
- Use `_orModelsCache` and `_orEndpointsCache` as in-memory caches. Update `_orEndpointsCache` comment/type to endpoint rows.
- Use `hide()` and `show()` for loading/error state.
- Keep `fetchEndpointsForModel()` non-blocking on errors: users can still type provider text manually.
- Keep `syncExplainerProviderUI()` as the UI sync point for provider/model mode visibility.

## Tests
- Update or add `tests/frontend/landing.test.js` coverage for any exported helper used to format endpoint meta or summary chips:
  - context only
  - context plus max completion and max prompt tokens
  - input/output endpoint pricing
  - absent endpoint values produce no misleading exact chip
- Update `tests/frontend/landingFlow.test.js`:
  - custom model selection with no provider endpoint shows `Modelo (agregado)` and model-list context/price.
  - mocked endpoint response with `tag: "novita/fp8"` renders provider combobox option label `Novita`, sublabel `novita/fp8`, and endpoint meta using endpoint context, max token limits, and endpoint prices.
  - clicking the provider option updates summary to `Proveedor exacto`, includes `Novita`, `novita/fp8`, endpoint context, max completion tokens, max prompt tokens, and endpoint prices.
  - submit after selecting provider sends `openrouter_provider: "novita/fp8"` even though the input display label is `Novita`.
  - manual typed provider still submits the typed value and does not display exact endpoint chips.
  - restore custom mode with saved `openrouterProvider: "novita/fp8"` refetches endpoints, matches by tag, sets the provider input display to `Novita`, keeps persisted provider as `novita/fp8`, and renders exact endpoint chips.
  - restore with a saved provider tag that is not in endpoint rows sets the provider input to the saved tag and leaves aggregate model chips.
- Run:
  - `npx vitest run tests/frontend/landing.test.js tests/frontend/landingFlow.test.js`

## Task Review
Required: no
Why: final review is sufficient

## Named Risks
- `createCombobox().getValue()` returns the displayed input text. For selected endpoint rows, handle upload must use stored canonical provider state instead of the displayed label.
- If the user manually edits the provider input after selecting an endpoint, clear selected endpoint metadata and treat the current input text as manual provider text.
- Restore uses async model and endpoint loads. Preserve the existing teardown guard so switching away from custom mode before requests resolve does not resurrect stale UI.
- Endpoint prices may be missing; do not label pricing as exact if the endpoint row lacks both input and output prices.

## Report Path
`plans/openrouter-provider-pricing/task-02-report.md`
