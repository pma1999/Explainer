# Context Map: OpenRouter Provider Pricing

## Objective
Support planning and implementation for improving the OpenRouter model selector so pricing and context window information can reflect provider-specific endpoint differences instead of only aggregate model-level metadata.

## CodeGraph Status
Absent for this investigation. `.codegraph/config.json` exists in the repo, but the `codegraph_status` MCP call returned `CodeGraph not initialized for this project`. Fallback used here: `rg`, targeted file reads, prior plan artifacts already in the repo, and live OpenRouter API/doc sampling.

## Relevant Areas
| Area | File | Symbol(s) | Contract / role | Read-hint | Why it matters |
|---|---|---|---|---|---|
| Selector state + persistence | `frontend/js/landing.js` | module state, `persistModelSelector()`, `restoreModelSelector()` | Stores only `explainerProvider`, `openrouterMode`, `openrouterModel`, `customOpenrouterModel`, `openrouterProvider`, `openrouterProviderOnly`, `deepseekModel`; no endpoint metadata survives reloads | `landing.js:12-35`, `landing.js:139-221`, `landing.js:762-791` | Any richer provider selection or provider-derived display state will touch persistence and restore |
| Custom model metadata UI | `frontend/js/landing.js` | `formatModelPrice()`, `formatContextLength()`, `setOpenRouterModel('__custom__')` | The custom model combobox and chosen-model summary render `context_length`, `prompt_price`, and `completion_price` from `GET /api/openrouter/models` | `landing.js:105-129`, `landing.js:460-555` | Current selector already surfaces model-level aggregate metadata here |
| Provider endpoint fetch + collapse | `frontend/js/landing.js` | `_orEndpointsCache`, `fetchEndpointsForModel()`, `formatProviderItems()` | Caches `modelId -> string[]`; provider UI items are built from plain strings with `value`, `label`, `sublabel`, and `meta` all derived from the same string | `landing.js:30-31`, `landing.js:585-614` | Primary frontend loss point for provider-specific price/context/limits |
| Submit payload | `frontend/js/landing.js` | `handleUpload()` | Sends `openrouter_model`, plus optional `openrouter_provider` and `openrouter_provider_only`; no provider metadata is sent to the backend | `landing.js:835-955` | UI can become richer without changing the process contract, as long as one canonical provider tag is preserved |
| Static preset selector copy | `frontend/index.html` | `#provider-card-openrouter`, `#openrouter-model-card-*`, `#openrouter-custom-panel` | OpenRouter preset cards are hardcoded Spanish copy; only the custom panel is hydrated from live API data | `index.html:247-326` | Preset cards currently cannot reflect live provider differences without a design/implementation change |
| Combobox renderer | `frontend/js/components/openrouter-combobox.js` | `createCombobox()` | Existing reusable combobox supports rich items with `{ value, label, sublabel, meta }` and already renders `.combobox-option-meta` | `openrouter-combobox.js:18-24`, `openrouter-combobox.js:84-189` | No new component is needed to show provider-specific badges |
| Selector styles | `frontend/style.css` | `.provider-card-sub`, `.provider-card-status`, `.combobox-option-meta`, `.openrouter-custom-model-summary` | Existing styles support metadata rows and summary chips; preset cards are still simple text blocks | `style.css:690-726`, `style.css:5426-5490` | Natural landing spots for provider-specific context/price/max-token badges |
| Model list proxy | `main.py` | `_fetch_openrouter_models()`, `get_openrouter_models()` | Fetches `https://openrouter.ai/api/v1/models?output_modalities=text` and normalizes each model to `{id, name, context_length, prompt_price, completion_price}` | `main.py:4086-4198` | Backend model-level loss point; drops richer upstream model fields before the frontend sees them |
| Endpoint proxy | `main.py` | `_fetch_openrouter_endpoints()`, `get_openrouter_endpoints()` | Fetches `https://openrouter.ai/api/v1/models/{model}/endpoints`, then reduces each endpoint dict to `ep.id or ep.slug or ep.name`; returns `{providers: string[]}` only | `main.py:4134-4212` | Backend provider-level loss point and current bottleneck for provider-specific UI |
| Request/routing contract | `main.py` | `ProcessProjectRequest`, `_build_openrouter_provider_routing()`, `api_process_project()`, `_process_project()` | Backend only needs a canonical provider identifier string to build `{"order":[slug], "allow_fallbacks"?: false}` and thread it into the worker | `main.py:179-229`, `main.py:3795-3929`, `main.py:1934-1941`, `main.py:3107-3114` | Rich UI data can stay frontend-only if it still emits one valid provider tag |
| OpenRouter explainer routing seam | `backend/agents/explainer_openrouter.py` | `_OPENROUTER_PROVIDER_OVERRIDES`, `_call_openrouter_json_with_pdf_fallback()`, `run_explainer_or()`, `run_subpart_explainer_or()` | `provider_routing` is already supported end-to-end and overrides the preset-specific fallback map when present | `explainer_openrouter.py:50-52`, `explainer_openrouter.py:531-611`, `explainer_openrouter.py:648-758` | Runtime routing is already capable; the current gap is selector data shaping |
| Final OpenRouter HTTP call | `backend/openrouter_client.py` | `call_openrouter_chat()` | Final request builder already accepts `provider: dict | None` | `openrouter_client.py:1560-1595` | No lower-level API change is required for provider-aware routing |

## Existing Patterns To Reuse
- `formatModelPrice()` and `formatContextLength()` in `frontend/js/landing.js` already turn tiny per-token values and raw token counts into user-facing badges.
- `createCombobox()` in `frontend/js/components/openrouter-combobox.js` already supports a third metadata column via `item.meta`; provider-specific context/price/max-token info can reuse that slot.
- `_orModelsCache` and `_orEndpointsCache` in `frontend/js/landing.js` are the existing in-memory fetch cache pattern for selector data.
- `syncExplainerProviderUI()` is the single UI sync point for provider/model state; new display state should stay coordinated through it rather than ad hoc DOM writes.
- `show()` / `hide()` from `frontend/js/dom.js` are the established visibility helpers used throughout the selector.
- `persistModelSelector()` / `restoreModelSelector()` own selector persistence; if provider identity or display state changes, extend these rather than introducing extra localStorage keys.
- `_build_openrouter_provider_routing()` in `main.py` and `provider_routing` threading in `backend/agents/explainer_openrouter.py` are the existing runtime contract for a chosen provider.
- `renderLandingDom()` in `tests/frontend/landingFlow.test.js` is the shared DOM factory to extend when adding new selector surfaces.

## Tests And Verification Entry Points
- `tests/frontend/landingFlow.test.js`: primary selector integration file. Covers custom model metadata, upload payloads, restore flow, and provider-only flag. Important gap: it does not assert live provider suggestion shaping; the payload test manually types `'deepseek'` into the provider combobox instead of selecting an API-returned item.
- `tests/frontend/landing.test.js`: unit tests for pure selector helpers. Good home for provider metadata formatters, normalization helpers, or provider label logic.
- `tests/backend/test_api.py`: currently covers `GET /api/openrouter/models` text-only filtering and unchanged aggregate response shape. There is no direct test for `GET /api/openrouter/models/endpoints`.
- `tests/backend/test_main_helpers_v2.py`: covers `_build_openrouter_provider_routing()` and proves routing currently accepts only `[\\w.-]+` tags up to 64 chars.
- Likely verification commands:
- `npx vitest run tests/frontend/landing.test.js tests/frontend/landingFlow.test.js`
- `python scripts/run_pytest.py tests/backend/test_api.py -v`
- `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py -v`

## Integration / Data Contracts
- Current repo contract: `GET /api/openrouter/models` returns `{models:[{id,name,context_length,prompt_price,completion_price}], stale, fetched_at}`. This is aggregate model-level data only.
- Current repo contract: `GET /api/openrouter/models/endpoints?model=<author/slug>` returns `{providers:[string], stale}`. Those strings are cached in `_orEndpointsCache` and rendered through `formatProviderItems()`.
- Current submit contract: `POST /api/projects/{id}/process` accepts `openrouter_model`, optional `openrouter_provider`, and optional `openrouter_provider_only`. Backend reduces this to a routing dict; it does not require UI pricing/context metadata.
- Documented OpenRouter model contract: `GET /api/v1/model/{author}/{slug}` (and the model-list docs) expose model-level `pricing` plus `top_provider.{context_length,max_completion_tokens,is_moderated}` and `supported_parameters`. The current repo fetches model lists but drops `top_provider`, `supported_parameters`, and the rest of the full `pricing` object.
- Live sampled OpenRouter text-endpoint payload (`GET https://openrouter.ai/api/v1/models/{model}/endpoints`) is much richer than the repo contract. For `deepseek/deepseek-v4-pro`, each endpoint object included `name`, `model_id`, `model_name`, `provider_name`, `tag`, `context_length`, `pricing`, `max_completion_tokens`, `max_prompt_tokens`, `supported_parameters`, `supports_implicit_caching`, `status`, and uptime/latency/throughput metrics.
- Provider-specific variation is real in current live data, including existing preset models:
- `xiaomi/mimo-v2.5-pro`: endpoints ranged from roughly `1048576` context / `$0.435` in / `$0.87` out per 1M to `87040` context / `$0.6` in / `$3` out per 1M.
- `xiaomi/mimo-v2.5`: one endpoint exposed only `32000` context while others exposed about `1,000,000+`; pricing also varied.
- `deepseek/deepseek-v4-pro`: 15 endpoints with materially different context lengths, max completion tokens, and prices.
- Exact data-loss points in the repo today:
- `_fetch_openrouter_models()` drops provider-aware fields before they ever reach the frontend.
- `_fetch_openrouter_endpoints()` drops every provider-specific field except a best-effort identifier string.
- `formatProviderItems()` only receives strings, so the selector cannot render provider-specific badges even though the combobox supports them.
- Canonical provider identity is already a live contract problem: sampled text endpoints expose `tag`, but `_fetch_openrouter_endpoints()` ignores `tag` and instead falls back to `name`. On a live sample, that produces values like `"DeepSeek | deepseek/deepseek-v4-pro-20260423"`, and `_build_openrouter_provider_routing()` then rejects them (`None`) because it only accepts `[\\w.-]+`. This means API-provided provider suggestions are not currently guaranteed to be valid routing keys.

## Named Risks
- The endpoint response shape for live text models is already mismatched with the current parser: provider suggestions can become human-readable endpoint names instead of canonical routing tags.
- Any change from `providers: string[]` to richer endpoint objects will ripple through `main.py`, `_orEndpointsCache`, `fetchEndpointsForModel()`, `formatProviderItems()`, restore logic, and selector tests.
- Persisted selector state currently stores only `openrouterProvider` as a string. If the chosen provider needs display name, tag, or cached metadata after reload, the persistence schema must evolve.
- Showing aggregate model pricing with provider-specific context (or vice versa) will be misleading when no provider is pinned. The planner needs a clear source-of-truth rule per UI state.
- Preset cards are hardcoded marketing/copy text and may disagree with live provider data; hydrating only custom mode could leave inconsistent semantics between preset and custom paths.
- Both model and endpoint proxies are cached in `main.py` for one hour. Provider-specific prices and limits can drift within that TTL.
- There is no direct backend test for the endpoint proxy route or its stale-fallback behavior.
- `top_provider` is a single provider summary, not a full representation of all endpoint options. It cannot replace endpoint-level data when a user is choosing among providers.

## Open Unknowns
- Before a user chooses a provider, should the UI show model-level aggregate numbers, `top_provider` numbers, the cheapest endpoint, or no provider-specific metrics yet?
- Should the three preset OpenRouter cards stay curated/static, or should they be hydrated from the same live endpoint data as the custom path?
- Which endpoint field should become the canonical routing key in this app: `tag`, a future `provider_slug`, or something else if OpenRouter evolves the contract?
- If provider metadata is not persisted, should restore refetch endpoints and recompute the displayed provider/context/price state on every landing re-entry?
- Is provider-specific information needed only inside the provider combobox, or also in the chosen-model summary, preset cards, and upload-ready confirmation state?
