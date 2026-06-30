# Plan: OpenRouter Provider-Aware Pricing

## Objective
Make the OpenRouter custom model selector distinguish model-level aggregate metadata from provider endpoint metadata. Before a provider is pinned, the UI keeps showing the model-list aggregate pricing/context with clear labeling. After a provider endpoint is selected, the provider combobox and chosen-model summary show that endpoint's exact pricing, context length, and max token limits. The processing payload continues to send only the selected model plus the canonical provider `tag`.

## Chosen Approach
- Keep preset cards static and curated for this pass. Do not hydrate preset cards unless the required change is trivial and isolated.
- Treat `GET /api/openrouter/models` as model-level aggregate data. Preserve the current shape and label its UI badges as aggregate when no provider is selected.
- Change `GET /api/openrouter/models/endpoints?model=<author/slug>` to return rich endpoint rows, not strings. Each row must preserve `tag` as the canonical routing key and expose display/summary metadata.
- Fix provider routing validation so slash-containing OpenRouter endpoint tags such as `novita/fp8` are accepted, while whitespace and display names remain rejected.
- Keep runtime processing unchanged below `main.py`: `openrouter_provider` is still reduced to `provider.order` and `openrouter_provider_only` still controls `allow_fallbacks`.
- Reuse the existing combobox `meta` slot for provider endpoint badges. Do not introduce a new component.
- On restore, load models, refetch endpoints for the saved custom model, re-match the persisted provider `tag`, and rebuild provider-specific summary chips. If the tag is not returned, keep the saved tag as manual text and fall back to aggregate model chips.

## Cross-Task Interfaces
Backend endpoint contract produced by Task 01 and consumed by Task 02:

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
      "supported_parameters": ["tools", "reasoning"],
      "supports_implicit_caching": true,
      "status": 0
    }
  ],
  "stale": false
}
```

Routing contract:
- `openrouter_provider` sent to `/api/projects/{id}/process` must be the endpoint `tag`, not `provider_name` and not endpoint `name`.
- `_build_openrouter_provider_routing("Novita/FP8", true)` should return `{"order": ["novita/fp8"], "allow_fallbacks": false}`.
- `_build_openrouter_provider_routing("DeepSeek | deepseek/model", false)` should return `None`.

Frontend display contract:
- No provider selected: chosen-model summary includes a chip containing `Modelo (agregado)` and uses model-list `context_length`, `prompt_price`, and `completion_price`.
- Provider selected from endpoint list: summary includes a chip containing `Proveedor exacto`, the selected `provider_name`, the selected `tag`, endpoint `context_length`, `max_completion_tokens` when present, `max_prompt_tokens` when present, and endpoint prices.
- Manual provider text that does not match an endpoint tag is allowed for submission but must not be displayed as exact endpoint pricing.

## Tasks And Waves
Wave 1:
- Task 01: Backend endpoint contract and routing tag fix.

Wave 2:
- Task 02: Frontend endpoint hydration, provider restore, and summary updates.

The tasks are sequential because Task 02 consumes the Task 01 response shape and routing semantics. They are not safe to run in parallel: they share the endpoint wire contract and tests must agree on the same `tag` meaning.

## Verification Overview
- Backend: `python scripts/run_pytest.py tests/backend/test_api.py -v` and `python scripts/run_pytest.py tests/backend/test_main_helpers_v2.py -v`.
- Frontend: `npx vitest run tests/frontend/landing.test.js tests/frontend/landingFlow.test.js`.
- Final review should run the combined commands above or state clearly which command could not run.

## Risks And Watch-Outs
- OpenRouter may enforce auth for endpoint metadata later. This plan keeps current unauthenticated metadata behavior and does not add a new auth path.
- Endpoint `status`, latency, uptime, and throughput are dynamic runtime signals. This pass preserves only `status` and does not use runtime metrics for sorting or copy.
- Model-level pricing often means "cheapest aggregate", not the selected provider. UI labels must not imply exact provider pricing until a provider `tag` is selected and matched.
- The combobox input displays labels, while processing needs tags. Task 02 must not rely on displayed provider text for selected endpoint submissions.
