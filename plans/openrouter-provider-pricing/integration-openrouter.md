# Integration Recipe: OpenRouter

## Objective

Verify the OpenRouter metadata contract needed to make the selector provider-aware: preserve a canonical routing key, surface per-provider pricing/context limits, and avoid treating aggregate model metadata as if it were provider-specific.

## Chosen Approach

Use the public OpenRouter REST metadata endpoints directly from the repo's existing Python `requests` pattern instead of introducing an SDK.

- Model catalog: `GET /api/v1/models?output_modalities=text`
- Provider endpoint metadata: `GET /api/v1/models/{author}/{slug}/endpoints`
- Canonical routing key: endpoint `tag`
- Display-only labels: endpoint `provider_name` and `name`

Sampled live against `openrouter.ai` on `2026-06-30`.

## Verified Contract

- Auth:
  - `GET /api/v1/models` returned `200` without an `Authorization` header. `VERIFIED`.
  - `GET /api/v1/models/{model}/endpoints` also returned `200` without an `Authorization` header for sampled models, even though the docs page still advertises Bearer auth. Treat public access as current behavior, not a hard guarantee. `VERIFIED` + `per-docs`.
  - Actual chat/completions routing in this repo still depends on `OPENROUTER_API_KEY`.
- Calls/endpoints/selectors:
  - `GET https://openrouter.ai/api/v1/models?output_modalities=text`
  - `GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints`
  - The sampled `links.details` field on model-list entries pointed at dated endpoint URLs such as `/api/v1/models/xiaomi/mimo-v2.5-20260422/endpoints`, but direct requests using the stable model `id` returned the same endpoint tags and normalized back to the stable `data.id`. `VERIFIED`.
- Request params:
  - `output_modalities=text` keeps the catalog text-only. `VERIFIED`.
  - `supported_parameters` and `sort` are documented optional filters on the model list. `per-docs`.
  - No request body or query params were needed for the sampled endpoint-detail calls. `VERIFIED`.
- Response/extracted shape:
  - `GET /api/v1/models` returns `{ "data": Model[] }`. `VERIFIED`.
  - Each sampled `Model` object included: `id`, `name`, `context_length`, `pricing`, `supported_parameters`, `links`, `top_provider`, `architecture`, `created`, `description`, and related metadata. `VERIFIED`.
  - `top_provider` was a short summary object with `context_length`, `max_completion_tokens`, and `is_moderated`; it was not a full provider record. `VERIFIED`.
  - `GET /api/v1/models/{model}/endpoints` returned `{ "data": { ...model fields..., "endpoints": Endpoint[] } }`, not a flat array and not `{ "providers": [...] }`. `VERIFIED`.
  - Each sampled endpoint row included: `tag`, `provider_name`, `name`, `model_id`, `model_name`, `context_length`, `max_completion_tokens`, `max_prompt_tokens`, `pricing`, `supported_parameters`, `supports_implicit_caching`, `status`, `quantization`, `latency_last_30m`, `throughput_last_30m`, `uptime_last_5m`, `uptime_last_1d`, and `uptime_last_30m`. `VERIFIED`.
  - `tag` is the field to preserve for routing. `provider_name` is human-readable. `name` is a verbose display string that included provider plus hosted model revision in live samples (for example, `"DeepSeek | deepseek/deepseek-v4-pro-20260423"`). `VERIFIED`.
- Pagination/rate limits:
  - No pagination fields were present in the sampled responses. `VERIFIED`.
  - The fetched docs did not describe pagination or rate-limit headers for these metadata endpoints. `UNVERIFIED` for server-side limits beyond the sampled calls.
- Errors:
  - The model-list docs describe `400` and `500` responses. `per-docs`.
  - The endpoint docs describe `404` and `500` responses. `per-docs`.
  - Valid sampled calls returned `200`; invalid-model error bodies were not exercised. `UNVERIFIED`.

## Minimal Working Snippet

```python
from urllib.parse import quote

import requests

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def fetch_openrouter_models() -> list[dict]:
    resp = requests.get(
        f"{OPENROUTER_BASE}/models",
        headers={"User-Agent": "Explainer/1.0"},
        params={"output_modalities": "text"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_openrouter_endpoints(model_id: str) -> dict:
    resp = requests.get(
        f"{OPENROUTER_BASE}/models/{quote(model_id, safe='/')}/endpoints",
        headers={"User-Agent": "Explainer/1.0"},
        timeout=15,
    )
    resp.raise_for_status()

    payload = resp.json()["data"]
    endpoints = []
    for ep in payload.get("endpoints", []):
        tag = (ep.get("tag") or "").strip()
        if not tag:
            continue  # no safe routing key
        endpoints.append(
            {
                "tag": tag,  # canonical slug for provider.order / provider.only / provider.ignore
                "provider_name": ep.get("provider_name") or tag,
                "name": ep.get("name") or tag,  # display-only
                "pricing": ep.get("pricing") or {},
                "context_length": ep.get("context_length"),
                "max_completion_tokens": ep.get("max_completion_tokens"),
                "supported_parameters": ep.get("supported_parameters") or [],
                "supports_implicit_caching": ep.get("supports_implicit_caching"),
                "status": ep.get("status"),
            }
        )

    return {
        "model_id": payload["id"],
        "model_name": payload.get("name"),
        "endpoints": endpoints,
    }
```

## Setup

- Env vars:
  - No new env var is required for the sampled metadata GETs today.
  - Keep using `OPENROUTER_API_KEY` for actual chat/completion requests and as a fallback if OpenRouter later enforces auth on endpoint metadata.
- Install/version:
  - Reuse the repo's existing `requests` dependency; no SDK is required for this metadata work.
  - Contract sampled against the live OpenRouter REST API on `2026-06-30`.
- Permissions/scopes:
  - Outbound HTTPS access to `openrouter.ai`.

## Gotchas

- Do not collapse endpoint rows down to strings. The provider-aware fields that materially differ per provider live on each endpoint row.
- Use `tag` as the routing slug. Do not route using `provider_name` or `name`.
- `tag` can include variant suffixes such as `xiaomi/fp8`, `novita/fp8`, or region/variant-style slugs documented by OpenRouter. Base slugs match all variants; exact slugs target a specific endpoint. `per-docs` + `VERIFIED`.
- The current repo helper `_build_openrouter_provider_routing()` only accepts `[\w.-]+`, so live tags containing `/` will be rejected until that validation is widened.
- Model-level `pricing` matched the cheapest sampled provider for all three sampled models; it is not a per-provider schedule.
- Model-level `context_length` and `top_provider.context_length` are not interchangeable. For `xiaomi/mimo-v2.5`, the sampled model-level `context_length` was `1048576` while `top_provider.context_length` matched a `32000`-token endpoint.
- `supported_parameters` varied materially by provider for the same model. Across the sampled models, endpoint counts ranged from `8` to `18` supported parameters, with only a smaller shared core present everywhere.
- Some listed endpoints had non-zero `status` values (for example `-2`) while still appearing in the list; treat status/latency/uptime as dynamic runtime signals, not stable metadata.

## Test Strategy

- Extend `tests/backend/test_api.py` with direct coverage for `GET /api/openrouter/models/endpoints`:
  - verify the route preserves nested endpoint metadata instead of flattening to strings
  - verify `tag`, `provider_name`, `pricing`, `context_length`, `max_completion_tokens`, and `supported_parameters` survive normalization
  - verify stale-cache fallback on the richer shape
- Extend `tests/backend/test_main_helpers_v2.py` for provider-routing acceptance:
  - accept slash-containing provider tags such as `novita/fp8`
  - keep rejecting spaces and punctuation that are not valid provider slugs
- Keep `tests/frontend/landingFlow.test.js` focused on payload/rich combobox behavior:
  - provider item labels should use `provider_name`
  - payload should submit canonical `tag`
  - provider-specific price/context badges should come from endpoint rows, not model aggregate metadata

## Verification Status

- `GET /api/v1/models?output_modalities=text` returned `{data:[...]}` with `pricing`, `supported_parameters`, `links`, and `top_provider` present on sampled models. - `VERIFIED` - Live GET succeeded without auth on `2026-06-30`.
- `GET /api/v1/models/{model}/endpoints` returned `{data:{id,name,architecture,created,description,endpoints:[...]}}` for `deepseek/deepseek-v4-pro`, `xiaomi/mimo-v2.5-pro`, and `xiaomi/mimo-v2.5`. - `VERIFIED` - Live GETs succeeded without auth on `2026-06-30`.
- Endpoint rows included `tag`, `provider_name`, `name`, `pricing`, `context_length`, `max_completion_tokens`, `supported_parameters`, and operational metrics. - `VERIFIED` - Observed across `24` sampled endpoint rows.
- `tag` is the provider slug used by `provider.order`, `provider.only`, and `provider.ignore`; exact slugs target one variant while base slugs match all variants. - `per-docs` - OpenRouter provider-routing guide.
- `provider_name` is a display label and `name` is verbose display text, not a safe routing key. - `VERIFIED` - Sampled `name` values contained spaces, pipes, and dated hosted-model suffixes.
- Provider-specific differences are material for the same model. - `VERIFIED` - In sampled models, prompt price ranged from `0.000000105` to `0.00000174`, context length ranged from `32000` to `1048576`, and supported-parameter counts ranged from `8` to `18`.
- Model-level `pricing` matched the cheapest sampled endpoint, while `top_provider` was only one provider snapshot and did not always match model-level `context_length`. - `VERIFIED` + `per-docs` - Live comparisons plus model docs separating `pricing` from `top_provider`.
- The endpoint docs page advertises Bearer auth and `404`/`500` errors, but sampled public GETs still succeeded without auth. - `VERIFIED` + `per-docs` - Current behavior may change.

## Open Risks

- OpenRouter may begin enforcing auth on `/models/{model}/endpoints`, which would break today's unauthenticated metadata fetch unless the app adds `OPENROUTER_API_KEY`.
- Text-endpoint docs are thinner than the live payload; new endpoint fields may appear before they are documented.
- No pagination or rate-limit contract was observed for these metadata endpoints, so parsers should fail loudly if a future response adds paging.
- The repo's current provider-routing validation is narrower than the live `tag` shape and must be widened before provider pinning can rely on exact endpoint tags.
