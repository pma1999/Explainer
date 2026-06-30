# Task 01 Report

## Status
DONE

## Outcome
`GET /api/openrouter/models/endpoints` now returns rich, tag-gated endpoint metadata (`model_id`, `model_name`, `endpoints[]`, `stale`) for both live and stale-cache fallback paths. Provider routing now accepts slash-containing endpoint tags such as `novita/fp8`, lowercases them, and still rejects display-name punctuation (spaces, pipes) and malformed slash shapes. `/api/openrouter/models` is unchanged.

## Acceptance Criteria
- `GET /api/openrouter/models/endpoints?model=<author/slug>` returns `model_id`, `model_name`, `endpoints`, `stale` -> pass (`TestGetOpenRouterEndpoints::test_returns_rich_endpoints_and_skips_untagged`)
- Each tagged endpoint row includes `tag`, `provider_name`, `name`, `context_length`, `max_completion_tokens`, `max_prompt_tokens`, `pricing`, `prompt_price`, `completion_price`, `supported_parameters`, `supports_implicit_caching`, `status` -> pass (same test asserts every field)
- Endpoint rows without `tag` are skipped -> pass (mocked payload has one tagged + one untagged endpoint; only one returned)
- `_fetch_openrouter_endpoints()` caches and serves the same rich shape for live and stale fallback -> pass (`test_stale_cache_fallback_returns_rich_shape` seeds an expired cache entry, live fetch returns 500, route still returns the rich shape with `stale: true`)
- `_build_openrouter_provider_routing()` accepts `novita/fp8`, lowercases, keeps rejecting spaces/pipes -> pass (`test_accepts_slash_variant_tag`, `test_lowercases_slash_variant_tag`, `test_rejects_display_name_with_pipe`, plus leading/trailing-slash rejection)
- `/api/openrouter/models` response shape unchanged -> pass (`TestGetOpenRouterModels::test_response_model_shape_is_unchanged` still green; key set is exactly `{id, name, context_length, prompt_price, completion_price}`)

## Files Changed
- `main.py` - modified
  - Import line widened from `from urllib.parse import urlparse` to `from urllib.parse import quote, urlparse` so the outbound endpoint URL can be safely quoted.
  - `_build_openrouter_provider_routing()` regex widened from `r"[\w.-]+"` to `r"[\w.-]+(?:/[\w.-]+)*"` to accept slash-separated variant tags while still rejecting leading/trailing/double slashes, spaces, and pipes.
  - Added module-level `_safe_float()` helper for malformed/absent pricing values (Named Risk defense).
  - Added module-level `_normalize_openrouter_endpoints()` helper that filters to tagged endpoints and projects the rich metadata fields keyed by `tag`.
  - Rewrote `_fetch_openrouter_endpoints()` to return `tuple[dict, bool]` where the dict is `{"model_id", "model_name", "endpoints": [...]}`; uses `quote(model, safe='/')` on the outbound URL; caches and serves the same rich payload on the stale fallback path.
  - Rewrote `get_openrouter_endpoints()` route response from `{"providers": [...], "stale": ...}` to `{"model_id", "model_name", "endpoints": [...], "stale": ...}`.
- `tests/backend/test_api.py` - modified
  - Added `TestGetOpenRouterEndpoints` with three tests: rich shape + untagged skip + outbound URL target; stale-cache fallback returns rich shape with `stale: true`; malformed pricing does not crash and defaults to `0.0`.
- `tests/backend/test_main_helpers_v2.py` - modified
  - Extended `TestBuildProviderRouting` with six tests: accept `novita/fp8`, lowercase `Novita/FP8`, slash variant with `only=True`, reject `DeepSeek | model` (pipe), reject leading slash, reject trailing slash.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `main.py` | `quote` import | Added to `urllib.parse` import for safe URL path quoting. |
| `main.py` | `_build_openrouter_provider_routing()` | Validation regex now accepts slash-separated variant tags; lowercasing and length/rejection behavior preserved. |
| `main.py` | `_safe_float()` | New private helper; coerces pricing strings to float, defaults to `0.0` on `TypeError`/`ValueError`. |
| `main.py` | `_normalize_openrouter_endpoints()` | New private helper; tag-gates endpoint rows and projects the rich metadata field set. |
| `main.py` | `_fetch_openrouter_endpoints()` | Return type changed from `tuple[list[str], bool]` to `tuple[dict, bool]`; builds and caches the rich payload; quotes the outbound URL; serves the same rich shape on stale fallback. |
| `main.py` | `get_openrouter_endpoints()` | Response contract changed from `{providers, stale}` to `{model_id, model_name, endpoints, stale}`. |
| `tests/backend/test_api.py` | `TestGetOpenRouterEndpoints` | New test class covering the endpoint route contract. |
| `tests/backend/test_main_helpers_v2.py` | `TestBuildProviderRouting` | Extended with slash-tag acceptance and display-name rejection cases. |

## Tests
- Command: `python scripts/run_pytest.py tests/backend/test_api.py tests/backend/test_main_helpers_v2.py -v`
  Result: pass — 62 passed, 0 failed (1 unrelated `RequestsDependencyWarning`).
- Command: `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py::TestBuildProviderRouting tests/backend/test_api.py::TestGetOpenRouterEndpoints -v`
  Result: pass — 19 passed (16 routing + 3 endpoint cases).

## TDD Evidence
- RED: `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py::TestBuildProviderRouting tests/backend/test_api.py::TestGetOpenRouterEndpoints -v` -> 6 failed, 13 passed. Slash-tag cases failed with `assert None == {'order': ['novita/fp8']}` (old regex rejected `/`); endpoint cases failed with `KeyError: 'model_id'` / `KeyError: 'endpoints'` (old route returned `{providers, stale}`). Existing tests stayed green, confirming the failures were the intended behavior gaps.
- GREEN: Same command after implementation -> 19 passed. Full-file run -> 62 passed, no regressions.

## Read Ledger
Planned reads:
- `plans/openrouter-provider-pricing/task-01-brief.md` (full) — task scope, acceptance criteria, context pack, named risks.
- `plans/openrouter-provider-pricing/global-constraints.md` (full) — canonical routing key is `tag`; endpoint route must surface `endpoints[]` not a flattened `providers` list.
- `plans/openrouter-provider-pricing/integration-openrouter.md` (full) — verified upstream endpoint field names, `tag` semantics, `quote(model_id, safe='/')` snippet, slash-variant gotcha.
- `main.py` lines 200-260 — `_build_openrouter_provider_routing()` current regex and `_resolve_explainer_model` context.
- `main.py` lines 4055-4226 — cache helpers, `_fetch_openrouter_models()` (unchanged-shape reference), `_fetch_openrouter_endpoints()`, `_validate_model_id()`, both OpenRouter routes.
- `main.py` lines 1-60 — imports (confirmed `urlparse` already imported, `quote` not yet).
- `tests/backend/test_api.py` lines 1-40, 520-610 — `TestGetOpenRouterModels` patch/cache pattern and `auth_client` usage.
- `tests/backend/test_main_helpers_v2.py` lines 1-140 — helper import pattern and existing `TestBuildProviderRouting` cases.
- `tests/backend/conftest.py` — `auth_client` / `override_get_current_user` fixtures.
- `scripts/run_pytest.py` — runner mechanics (`PYTEST_PLUGINS=pytest_asyncio.plugin`, basetemp handling).

Extra reads:
- `requirements-dev.txt` — confirmed `pytest-asyncio>=1.0.0` and `httpx>=0.27.0` are declared dev deps; installed `pytest-asyncio` (was missing locally) to unblock the runner.
- Grep for `_fetch_openrouter_endpoints` callers — confirmed the route is the only caller, so the return-type change is safe.
- Grep for `models/endpoints` / `get_openrouter_endpoints` / `"providers"` across `tests/` — confirmed no other test depends on the old `{providers}` shape (the `test_pipeline_live_neural_compare.py` `providers` hits are an unrelated pipeline summary object).

Pack gaps:
- None.

## Decisions
- Routing regex chosen as `r"[\w.-]+(?:/[\w.-]+)*"` rather than a permissive `r"[\w./-]+"`. This accepts `novita/fp8` and multi-segment variant slugs while still rejecting leading slash (`/novita`), trailing slash (`novita/`), double slashes (`novita//fp8`), spaces, and pipes — satisfying the Named Risk "do not accidentally relax provider routing enough to accept display names with spaces or pipes."
- Added a module-level `_safe_float()` helper instead of mirroring `_fetch_openrouter_models()`'s bare `float(...)` call. The Named Risk explicitly requires no crash on malformed/absent pricing, and a single malformed endpoint row must not take down the whole response (the model-list `float()` is wrapped in a whole-fetch try/except, which would drop every endpoint on one bad price). `_safe_float` returns `0.0` on `TypeError`/`ValueError` and otherwise matches the model-list default-on-absent behavior via `pricing.get("prompt", 0)`.
- `provider_name` and `name` fall back to `tag` when upstream omits them, matching the verified Integration Recipe snippet and guaranteeing non-None display values for the frontend combobox.
- `model_id`/`model_name` fall back to the validated `model` string when upstream `data.id`/`data.name` are absent, so the response is always well-formed even on a partial upstream payload.
- Applied `quote(model, safe='/')` to the outbound endpoint URL even though the current `_validate_model_id` regex (`^[\w.-]+/[\w.:-]+$`) only produces URL-safe characters. This aligns with the verified Integration Recipe, is a no-op today, and defends against future model-id validation changes without altering accepted model-ID semantics.

## Concerns / Follow-ups
- The frontend (Task 02 scope) currently consumes the old `providers` string list from this route; it must switch to reading `endpoints[]` and using `tag` as the canonical routing key. This is expected and out of scope for Task 01; the wire contract change is intentional and gated by this task's review.
- Operational endpoint fields (`status`, latency, uptime) are passed through verbatim per the Integration Recipe note that they are dynamic runtime signals, not stable metadata. If the frontend later needs to filter out non-zero `status` endpoints, that belongs in Task 02's restore/match logic, not here.
- `pytest-asyncio` was not installed in the local environment despite being declared in `requirements-dev.txt`; installed it (1.4.0) to run the verification commands. No code impact.
