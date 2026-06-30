# Task T1: Backend — text-only OpenRouter model listing + test

## Goal
`GET /api/openrouter/models` lists only models whose output modality includes text, both via a
server-side query param and a defensive in-code guard. Existing metadata pass-through is unchanged.

## Acceptance Criteria
- `_fetch_openrouter_models` requests OpenRouter with `params={"output_modalities": "text"}`.
- The normalization comprehension keeps a model ONLY if
  `"text" in (m.get("architecture", {}).get("output_modalities") or [])`, in addition to the
  existing `if m.get("id")` guard.
- Returned model dicts keep the existing keys exactly: `id`, `name`, `context_length`,
  `prompt_price`, `completion_price` (shape unchanged for all callers).
- New backend test in `tests/backend/test_api.py`: mock a `data` payload mixing output
  modalities (e.g. one `["text"]`, one `["image"]`, one missing `architecture`) and assert the
  response `models` contains only the text-output model id(s).
- `python scripts/run_pytest.py tests/backend/test_api.py` passes.

## Scope
Touch:
- `main.py` — `_fetch_openrouter_models` (starts at `main.py:4086`). Only the `requests.get`
  call and the `normalized = [...]` comprehension.
- `tests/backend/test_api.py` — add one test (and a fixture/mock as needed).

Do not touch:
- `get_openrouter_models` endpoint shape, the cache key `("models",)`, `_resolve_explainer_model`,
  `OPENROUTER_EXPLAINER_MODELS`, or any frontend file.

## Constraints
- Cache key stays `("models",)`; the cached list becomes text-only and consistent for all callers.
- Model dict keys must not change (frozen contract — see global-constraints.md).

## Interfaces
Consumes: upstream `GET https://openrouter.ai/api/v1/models` -> `{data:[Model,...]}` where each
`Model` has `architecture.output_modalities: string[]` and `pricing.{prompt,completion}`.
Produces: text-only `{models:[{id,name,context_length,prompt_price,completion_price}], stale, fetched_at}`.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `main.py` | `_fetch_openrouter_models` | lines 4086-4129 | Exact change site; current `requests.get` + comprehension shown in recipe |
| `main.py` | `get_openrouter_models` | ~4188-4196 | Confirms response wrapper (do not change) |
| `tests/backend/test_api.py` | top fixtures `client`, `patch`/`MagicMock` | lines 1-44 | Test patterns: `patch("main.<symbol>", ...)`, `TestClient` |
| `plans/model-selector-ux/integration-openrouter-models.md` | full recipe | whole file | Authoritative contract + required change + risks |

## Existing Patterns To Reuse
- Mocking: tests use `from unittest.mock import patch, MagicMock` and `with patch("main.<x>")`.
  Patch the `requests.get` boundary used inside `_fetch_openrouter_models` (e.g.
  `patch("main.requests.get", return_value=<mock resp with .status_code=200 and .json()>)`),
  and clear/avoid the `("models",)` cache so the fetch path runs (inspect `_cache_get`/`_cache_set`
  near the function; reset the cache store before the call if needed).

## Tests
- `python scripts/run_pytest.py tests/backend/test_api.py` — new test green; existing tests stay green.
- Red-first: mixed-modality mock should fail before the guard is added (non-text leaks in), pass after.

## Task Review
Required: yes
Why: shared contract for every model-list consumer; verifies the defensive guard actually filters
(not just the unverifiable query param) and that cache semantics are unchanged.

## Named Risks
- The `output_modalities` query param may not be honored for cached/edge responses — the in-code
  guard is the real filter; the test must prove the guard, not the param.
- Don't let a stale `("models",)` cache entry mask the fetch path in the test.

## Report Path
`plans/model-selector-ux/task-T1-report.md`
