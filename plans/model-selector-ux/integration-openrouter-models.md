# Integration Recipe: OpenRouter Models (text-only + metadata)

Verified 2026-06-30 against OpenRouter docs + repo. Scope: the custom/free OpenRouter
model picker in the landing selector must list **only models whose output modality is
text**, and surface per-model metadata (context length + price).

## Upstream contract — `GET https://openrouter.ai/api/v1/models`
Returns `{ "data": [ Model, ... ] }`. Each `Model` includes:
- `id` (e.g. `"author/slug"`), `name`, `context_length`
- `pricing: { prompt, completion, ... }` (string/float USD per token)
- `architecture: { input_modalities: string[], output_modalities: string[], tokenizer, instruct_type }`
  - **`output_modalities`** is the field that matters: `["text"]` for text-output models; may include `"image"` etc.
- Query param **`?output_modalities=text`** filters server-side to text-output models (documented, default-ish behavior).

## Repo reality — `main.py`
- `_fetch_openrouter_models()` (main.py:4086) fetches `https://openrouter.ai/api/v1/models`,
  reads `resp.json().get("data", [])`, and normalizes each model to:
  `{id, name, context_length, prompt_price (float), completion_price (float)}` — **drops `architecture`**.
  Result cached under key `("models",)` via `_cache_set`; stale fallback via `_cache_get_stale`.
- `get_openrouter_models` (main.py:4188) returns `{models, stale, fetched_at}`.
- Frontend `loadOpenRouterModels()` (landing.js:372) consumes `{models:[{id,name,...}]}`.

## Required change (backend, text-only)
In `_fetch_openrouter_models`:
1. Add `params={"output_modalities": "text"}` to the `requests.get` call (server-side filter).
2. **Defensive** in-comprehension guard (the param may not be honored for cached/edge cases):
   keep a model only if `"text" in (m.get("architecture", {}).get("output_modalities") or [])`.
   Apply this guard so any non-text-output model is excluded regardless of the query param.
3. Metadata is already passed through (`context_length`, `prompt_price`, `completion_price`) — no
   new fields strictly required for the UI. (Optional: also pass `output_modalities` for future use.)
4. Cache key stays `("models",)`; the cached list is now text-only and consistent for all callers.

### Notes / risks
- `prompt_price`/`completion_price` are USD **per token** (very small floats). UI must format
  as "$/1M tokens" (multiply by 1e6) or "$/1K" for a readable badge — decide in plan.
- Some models report `prompt_price == 0` (free) — UI should render "Gratis"/"Free" not "$0.00".
- Existing backend tests for the models endpoint: `tests/backend/test_api.py`. Add/extend a test
  asserting non-text-output models are filtered out (mock a `data` payload mixing modalities).
- Frontend `_resolve_explainer_model` / validation unaffected; this only narrows the listing.
