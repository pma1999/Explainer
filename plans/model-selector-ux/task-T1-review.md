# Review: task T1

## Verdict
PASS

## Functional Verification
- `python scripts/run_pytest.py tests/backend/test_api.py` — 29 passed (27 pre-existing + 2 new) in 1.88 s. Run confirmed live in this session.
- Diff inspected from baseline `dcba671`: two hunks in `main.py` (one inside `requests.get`, one extending the comprehension guard), one new class `TestGetOpenRouterModels` in `tests/backend/test_api.py`.

## Spec Compliance
- `params={"output_modalities": "text"}` added to `requests.get` call (line 4099). Met.
- Defensive comprehension guard `and "text" in (m.get("architecture", {}).get("output_modalities") or [])` added at line 4115. Met.
- Response shape `{models, stale, fetched_at}` and model dict keys `{id, name, context_length, prompt_price, completion_price}` unchanged. Verified by reading `get_openrouter_models` (lines 4190-4198) and confirmed by `test_response_model_shape_is_unchanged` which asserts `set(model.keys()) == {"id", "name", "context_length", "prompt_price", "completion_price"}`. Met.
- New test `test_filters_non_text_output_models` mocks a 3-item payload (one `["text"]`, one `["image"]`, one missing `architecture`) and asserts only the text model appears. Met.
- All tests pass. Met.

## Code Quality
- Guard expression is correct: `m.get("architecture", {})` handles missing `architecture` key (returns `{}`); `.get("output_modalities")` then returns `None`; `or []` coerces `None` to `[]`; `"text" in []` is `False`. All three failure modes (no `architecture` key, `output_modalities` absent, `output_modalities` is a non-text list) are excluded.
- Minor unguarded case: if a model has `{"architecture": null}` (key present, value JSON null), `m.get("architecture", {})` returns `None` (the default `{}` is only applied when the key is absent), and `None.get(...)` raises `AttributeError`. This propagates to the `except Exception: pass` at line 4119, causing the request to fall through to the stale-cache path and eventually 503 if no stale entry exists. This edge case is outside the brief's scope and not documented by the OpenRouter contract; the exception boundary provides a safe fallback. Not a required change.
- Cache manipulation in tests via `patch.dict("main._cache", {}, clear=True)` is correct and minimal — it ensures the fetch path runs without touching TTL or locking logic, consistent with the pattern described in the brief.
- Two tests instead of one is a sound decision: they prove distinct properties (filtering vs. shape contract) and both run fast.

## Named Risk Checks

**Risk 1 — Guard is the real filter, not just the query param.**
The guard at `main.py:4115` is inside the comprehension that builds `normalized`, executed on the raw `data` returned by `resp.json().get("data", [])`. It runs regardless of whether the upstream `?output_modalities=text` param was honored. The test bypasses the param entirely (mock response returns all three modality types) and the guard correctly excludes image-only and no-architecture models. Confirmed: the guard is the real filter.

**Risk 2 — Stale cache path not broken by the filter.**
`_cache_get_stale` (lines 4078-4083) is entirely unchanged in the diff. The filter operates only at normalization time before `_cache_set` (line 4117); the stale retrieval path just returns whatever `_cache[("models",)]` holds. After this fix is deployed, every cache write stores an already-filtered text-only list. The stale path is not broken.

**Risk 3 — Test cache masking the fetch path.**
`patch.dict("main._cache", {}, clear=True)` clears the cache dictionary for the test scope. `_cache_get` at line 4089 finds no entry and returns `(None, False)`, so the code falls through to the live fetch (mocked). The guard is therefore exercised in both tests. Confirmed.

## Required Changes
None.

## Evidence
- `git diff dcba671 -- main.py tests/backend/test_api.py` reviewed: two targeted hunks, no scope creep.
- `main.py` lines 4086-4131: full `_fetch_openrouter_models` read; comprehension guard and stale path both confirmed.
- `main.py` lines 4063-4083: `_cache_get`, `_cache_set`, `_cache_get_stale` read; stale semantics confirmed.
- `main.py` lines 4190-4198: `get_openrouter_models` endpoint unchanged.
- `tests/backend/test_api.py` diff: `TestGetOpenRouterModels` class with two methods confirmed.
- Test run: 29/29 passed (1.88 s).

## Limitations
- Stale-path behavior for cache entries written before this fix (pre-deployment) is not tested. Those entries could contain non-text models for up to one CACHE_TTL (1 hour) after deployment. This is a deployment-window concern, not a code defect, and is outside the brief's scope.
- The `{"architecture": null}` edge case is not exercised by the test suite. As documented under Code Quality, the exception boundary handles it safely.
