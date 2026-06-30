# Task 01: Backend Endpoint Contract And Routing Tags

## Goal
Return rich OpenRouter endpoint metadata from the backend and fix provider routing so endpoint `tag` values with slash variants are accepted.

## Acceptance Criteria
- `GET /api/openrouter/models/endpoints?model=<author/slug>` returns `model_id`, `model_name`, `endpoints`, and `stale`.
- Each returned endpoint row with a non-empty upstream `tag` includes:
  - `tag`
  - `provider_name`
  - `name`
  - `context_length`
  - `max_completion_tokens`
  - `max_prompt_tokens`
  - `pricing`
  - `prompt_price`
  - `completion_price`
  - `supported_parameters`
  - `supports_implicit_caching`
  - `status`
- Endpoint rows without `tag` are skipped.
- `_fetch_openrouter_endpoints()` caches and serves the same rich response shape for live and stale fallback paths.
- `_build_openrouter_provider_routing()` accepts slash-containing provider tags such as `novita/fp8`, lowercases them, and keeps rejecting strings with spaces, pipes, or other display-name punctuation.
- Existing `/api/openrouter/models` response shape remains unchanged.

## Scope
Touch:
- `main.py`
  - `_fetch_openrouter_endpoints()`
  - `get_openrouter_endpoints()`
  - `_build_openrouter_provider_routing()`
  - imports near the existing OpenRouter metadata helpers if URL quoting is needed
- `tests/backend/test_api.py`
  - add direct endpoint route tests
- `tests/backend/test_main_helpers_v2.py`
  - extend provider routing tests

Do not touch:
- `frontend/js/landing.js`
- `frontend/js/components/openrouter-combobox.js`
- `backend/agents/explainer_openrouter.py`
- `backend/openrouter_client.py`
- `/api/openrouter/models` model-list shape

## Constraints
- Canonical provider routing key is endpoint `tag`.
- Do not route with endpoint `name` or `provider_name`.
- Keep processing request fields unchanged: `openrouter_model`, `openrouter_provider`, `openrouter_provider_only`.
- Reuse the existing `requests.get` plus `asyncio.to_thread` pattern.
- Do not add an OpenRouter SDK or a new env var.

## Interfaces
Consumes:
- OpenRouter endpoint metadata from `GET https://openrouter.ai/api/v1/models/{model}/endpoints`.
- Verified upstream shape from `plans/openrouter-provider-pricing/integration-openrouter.md`: response is `{ "data": { "id": ..., "name": ..., "endpoints": [...] } }`.
- Existing cache helpers in `main.py`: `_cache_get()`, `_cache_set()`, `_cache_get_stale()`.

Produces:
- Backend endpoint response:

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

- Provider routing dicts where `novita/fp8` is valid:

```python
{"order": ["novita/fp8"]}
{"order": ["novita/fp8"], "allow_fallbacks": False}
```

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `main.py` | `_build_openrouter_provider_routing()` | around lines 216-229 | Narrow validation currently rejects slash-containing endpoint tags. |
| `main.py` | `_fetch_openrouter_models()` | around lines 4086-4131 | Existing model-list response shape must stay unchanged. |
| `main.py` | `_fetch_openrouter_endpoints()` | around lines 4134-4176 | Current loss point: flattens endpoint dicts to strings and ignores `tag`. |
| `main.py` | `get_openrouter_endpoints()` | around lines 4201-4212 | Route response must change from `providers` to rich `endpoints`. |
| `tests/backend/test_api.py` | `TestGetOpenRouterModels` | around lines 528-610 | Pattern for patching `requests.get`, clearing cache, and asserting metadata route behavior. |
| `tests/backend/test_main_helpers_v2.py` | `TestBuildProviderRouting` | around lines 93-140 | Extend existing provider routing acceptance tests. |
| `plans/openrouter-provider-pricing/integration-openrouter.md` | verified OpenRouter endpoint contract | lines 32-45 and 114-123 | Source of truth for upstream endpoint field names and tag semantics. |

## Existing Patterns To Reuse
- Use `float(m.get("pricing", {}).get("prompt", 0))` and `float(...completion...)` style from `_fetch_openrouter_models()` for display-ready prices.
- Use existing cache key `("endpoints", model)` but store the rich normalized payload, not a string list.
- Use `HTTPException(status_code=503, detail=...)` fallback behavior already in `_fetch_openrouter_endpoints()`.
- Keep tests isolated with `patch.dict("main._cache", {}, clear=True)` as in `tests/backend/test_api.py`.

## Tests
- Add `tests/backend/test_api.py` coverage for `/api/openrouter/models/endpoints`:
  - mocked OpenRouter payload includes at least two endpoints, one with `tag: "novita/fp8"` and one missing `tag`; assert only the tagged endpoint is returned.
  - assert `model_id`, `model_name`, `stale`, and all endpoint fields listed in Acceptance Criteria.
  - assert `prompt_price` and `completion_price` are floats derived from `pricing`.
  - assert stale cache fallback returns the rich response shape with `stale: true`.
- Extend `tests/backend/test_main_helpers_v2.py`:
  - accept `novita/fp8`.
  - accept `Novita/FP8` and lowercase to `novita/fp8`.
  - keep rejecting `DeepSeek | model`, `bad provider!`, whitespace-only, and too-long values.
- Run:
  - `python scripts/run_pytest.py tests/backend/test_api.py -v`
  - `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py -v`

## Task Review
Required: yes
Why: This task changes a shared backend wire contract and fixes a routing validation bug that Task 02 depends on.

## Named Risks
- Upstream endpoint `pricing` values are strings in live samples; `prompt_price` and `completion_price` must not crash if a price is absent or malformed. Use the existing model-list default behavior as the guide.
- The route path includes model IDs with `/`; preserve the existing model ID validation and quote the outbound URL if needed without changing accepted model ID semantics.
- Do not accidentally relax provider routing enough to accept display names with spaces or pipes.

## Report Path
`plans/openrouter-provider-pricing/task-01-report.md`
