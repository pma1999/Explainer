# Global Constraints — Model Selector UX

Binding across all tasks. Use exact values.

## Theme / Visual
- Use ONLY the existing `:root` design tokens at `frontend/style.css` lines 7-30. No new theme,
  no second accent. Single accent = `--amber:#f59e0b` (dim fill `--amber-dim:rgba(245,158,11,0.12)`).
- Tokens available: `--bg-base:#0d1117`, `--bg-surface:#161b22`, `--bg-elevated:#1f2937`,
  `--border:#2d3748`, `--text-primary:#f0ece3`, `--text-secondary:#9ca3af`, `--text-muted:#6b7280`,
  fonts `--font-ui:'Syne'`, `--font-display:'Playfair Display'`, `--font-body:'Crimson Pro'`.
- Utility copy only (Spanish UI). Labels state what the control does / its state. No hero or
  marketing language. Match the tone of existing copy.
- Cards only where the card IS the interaction (provider/model selection). No decorative chrome.
- Respect `prefers-reduced-motion: reduce` for any new transition/animation.

## JavaScript / DOM
- All new DOM event listeners MUST be added inside the `if (!_landingListenersAttached)` block
  (`frontend/js/landing.js:455`). Never attach listeners outside it.
- Never use `el.style.display`. Toggle visibility only via `show(el)` / `hide(el)` from `dom.js`
  (they toggle the `.hidden` class).
- Reuse `createCombobox` for any searchable picker. Do not build a new combobox.
- Reuse `$`, `show`, `hide`, `toast` from `frontend/js/dom.js`.
- Treat `state` (`frontend/js/state.js`) as read-only from landing: `hasApiKey` (Gemini),
  `hasOpenRouterKey`, `hasMistralKey`, `hasDeepSeekKey`, `hasTavilyKey`. Never mutate it.
- Do NOT add any async gap between `POST /api/projects` and `POST /api/projects/{id}/process`
  in `handleUpload`.

## Contracts (frozen)
- Submit payload shape `ProcessProjectRequest` (`main.py:179-185`) MUST NOT change. Fields:
  `explainer_provider` ("gemini"|"openrouter"|"deepseek"), `openrouter_model` (str|null),
  `deepseek_model` ("deepseek-v4-pro"|"deepseek-v4-flash"|null), `target_language` (default "es-ES"),
  `openrouter_provider` (str|null), `openrouter_provider_only` (bool, default false).
- Frontend preset model constants MUST equal backend `OPENROUTER_EXPLAINER_MODELS` (`main.py:161`):
  `xiaomi/mimo-v2.5-pro`, `xiaomi/mimo-v2.5`, `deepseek/deepseek-v4-pro`;
  DeepSeek-direct: `deepseek-v4-pro`, `deepseek-v4-flash`. Do not change the preset set.
- `GET /api/openrouter/models` returns `{models:[{id,name,context_length,prompt_price,completion_price}], stale, fetched_at}`.
  After T1 the list is text-output-only; the shape is unchanged.

## Accessibility floor
- Exactly one `role="combobox"` per combobox (on the `<input>`). The wrapper `<div>` carries no role.
- `#explainer-provider-hint` => `aria-live="polite"`; `#explainer-provider-error` => `aria-live="assertive"`.
- `.provider-card` must show a visible `:focus-visible` ring (radios are visually hidden).
- Keyboard nav for the radio-backed cards must work (arrow/space/enter) and selection changes
  must be announced (do not break native radio semantics).

## Persistence
- One key only: `explainer.modelSelector.v1` in `localStorage`. Restore must never throw on
  corrupt/missing data and must validate every field before applying, falling back to safe
  defaults (`explainer_provider='gemini'`, preset model defaults).

## Price / metadata formatting (settled)
- Prices are USD per token (tiny floats). Display as `$/1M tokens` = `perTokenUsd * 1e6`.
  Render `Gratis` when the price is exactly 0. Context length displayed as `NNK ctx`.

## Tests
- Extend the single `renderLandingDom()` factory in `tests/frontend/landingFlow.test.js`; do not
  duplicate it. Pure functions go in `tests/frontend/landing.test.js`. Backend tests in
  `tests/backend/test_api.py`.
