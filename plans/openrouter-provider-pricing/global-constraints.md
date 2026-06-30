# Global Constraints: OpenRouter Provider-Aware Pricing

- The canonical OpenRouter provider routing key is endpoint `tag`.
- Do not route using endpoint `name` or `provider_name`; those fields are display-only.
- `GET /api/openrouter/models` remains model-level aggregate metadata with the existing model shape: `id`, `name`, `context_length`, `prompt_price`, `completion_price`.
- `GET /api/openrouter/models/endpoints` returns endpoint-level metadata under `endpoints`; frontend code must consume endpoint rows from `endpoints`, not a flattened `providers` string list.
- Provider tags may include slash-separated variants such as `novita/fp8`; provider routing must lowercase accepted tags and keep rejecting spaces, pipes, and other display-name punctuation.
- The processing request body remains unchanged: `openrouter_model`, optional `openrouter_provider`, optional `openrouter_provider_only`.
- Persist only selector choices needed to restore behavior. Persisted `openrouterProvider` is the provider `tag` or manual user text, not display metadata.
- On restore in custom OpenRouter mode, refetch endpoint metadata and match the saved provider by `tag`; do not trust stale display metadata from localStorage.
- Use existing `landing.js` state/persistence patterns, existing `formatModelPrice()` and `formatContextLength()`, and the existing combobox `meta` slot.
- Keep OpenRouter preset cards static for this work. Do not add live pricing/context hydration to preset cards.
- Provider-specific summary chips are only exact when a selected provider endpoint row is matched by `tag`. Otherwise the summary must be labeled as model aggregate data.
- Do not introduce a new frontend component, a new OpenRouter SDK, or a new persistence key.
