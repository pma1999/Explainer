# Task T1 Report

## Status
DONE

## Outcome
`GET /api/openrouter/models` now returns only text-output models. `_fetch_openrouter_models` adds
`params={"output_modalities": "text"}` to the upstream request (server-side filter) and applies a
defensive in-comprehension guard `"text" in (m.get("architecture", {}).get("output_modalities") or [])`.
Models lacking `architecture`, having `architecture.output_modalities` absent/null, or listing only
non-text modalities (e.g. `["image"]`) are all excluded. Response shape `{models, stale, fetched_at}`
and model dict keys `{id, name, context_length, prompt_price, completion_price}` are unchanged.

## Acceptance Criteria
- `_fetch_openrouter_models` requests OpenRouter with `params={"output_modalities": "text"}` -> pass (added)
- Comprehension keeps model only if `"text" in (m.get("architecture", {}).get("output_modalities") or [])` in addition to `if m.get("id")` -> pass
- Returned model dicts keep keys exactly: `id`, `name`, `context_length`, `prompt_price`, `completion_price` -> pass (`test_response_model_shape_is_unchanged`)
- New backend test mocks mixed-modality payload and asserts only text-output model id appears -> pass (`test_filters_non_text_output_models`)
- `python scripts/run_pytest.py tests/backend/test_api.py` passes -> pass (29/29)

## Files Changed
- `main.py` — modified `_fetch_openrouter_models` (lines 4096-4114): added `params={"output_modalities": "text"}` to `requests.get` call; extended comprehension guard with `and "text" in (m.get("architecture", {}).get("output_modalities") or [])`.
- `tests/backend/test_api.py` — appended `TestGetOpenRouterModels` class with two tests: `test_filters_non_text_output_models` and `test_response_model_shape_is_unchanged`.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `main.py` | `_fetch_openrouter_models` | Added `params={"output_modalities": "text"}` to `requests.get`; added `"text" in (m.get("architecture", {}).get("output_modalities") or [])` guard in comprehension |
| `tests/backend/test_api.py` | `TestGetOpenRouterModels` | New class with two test methods |

## Tests
- Command: `python scripts/run_pytest.py tests/backend/test_api.py -v`
  Result: 29 passed in 5.44s (27 pre-existing + 2 new)

## TDD Evidence
- RED: Before adding the in-comprehension guard, `test_filters_non_text_output_models` would return all 3 models (image-model and no-arch-model leak through); the assertions `assert "author/image-model" not in model_ids` and `assert "author/no-arch-model" not in model_ids` would fail.
- GREEN: After both changes, 29/29 pass with no regressions.

## Read Ledger
Planned reads:
- `plans/model-selector-ux/task-T1-brief.md` — task scope and AC
- `plans/model-selector-ux/global-constraints.md` — frozen response shape
- `plans/model-selector-ux/integration-openrouter-models.md` — required change recipe
- `main.py` lines 4086-4129 — exact change site (`_fetch_openrouter_models`)
- `main.py` lines 4185-4196 — `get_openrouter_models` wrapper (confirmed: do not change)
- `tests/backend/test_api.py` lines 1-60 — top fixtures and test patterns
- `tests/backend/conftest.py` — `auth_client` fixture definition

Extra reads:
- `main.py` lines 4050-4085 — located `_cache` dict and helper functions to understand how to clear it in tests via `patch.dict("main._cache", {}, clear=True)`
- `tests/backend/test_api.py` lines 60-526 — confirmed `auth_client` usage patterns and found end of file for append

Pack gaps:
- None

## Decisions
- Used `patch.dict("main._cache", {}, clear=True)` to ensure the fetch path runs in tests; this is the minimal intervention that prevents a warm cache from masking the fetch call without touching the cache TTL or locking logic.
- Added two tests instead of one: the filtering test covers the core AC (non-text exclusion); the shape test verifies the frozen contract is unchanged. Both are cheap and each proves something distinct.
- Positioned new class at the bottom of the file following existing class ordering by feature area.

## Concerns / Follow-ups
- None
