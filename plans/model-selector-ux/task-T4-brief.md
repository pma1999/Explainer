# Task T4: Inline per-card API-key status indicators

## Goal
Before submit, each provider card (and the DeepSeek-direct model context) shows a clear inline
indicator when its required API key is missing — so the user understands which engines are usable
without having to click submit and read a validation error.

## Acceptance Criteria
- Each provider card renders a status slot `.provider-card-status` (added in markup). When the
  card's required key is missing, it shows Spanish utility copy, e.g.
  `Falta API key — configúrala en Ajustes`, and the card gets a `.needs-key` class.
- Key requirements per provider (read from `state`, never mutate):
  - Gemini card: needs `state.hasApiKey`.
  - OpenRouter card: needs `state.hasOpenRouterKey` (Gemini key is also required by the flow, but
    the card's primary missing-key signal is the OpenRouter key; if `hasApiKey` is false show that
    too — keep copy concise, e.g. mention OpenRouter; reuse the existing validation message intent
    from `validateExplainerProviderSelection` without duplicating its full branching).
  - DeepSeek card: needs `state.hasDeepSeekKey`.
- The indicator updates inside `syncExplainerProviderUI()` (called after every state mutation and on
  init) — not only at submit time.
- A needs-key card remains understandable: even when also `.disabled` (unsupported for source type),
  the needs-key reason must be distinguishable from the unsupported-for-source reason. Do not hide
  the card; keep text legible (coordinate with T3's refined `.disabled` so opacity doesn't bury it).
- `.needs-key` visual state is styled in `style.css` using existing tokens (e.g. a muted warning
  treatment — amber/`--text-muted`, NOT a new red accent).
- Submit-time `validateExplainerProviderSelection` behavior is unchanged (still the authority); this
  task only adds an earlier, inline hint.
- New/updated tests assert the indicator shows/hides based on `state.has*Key`. `npx vitest run
  tests/frontend/` green.

## Scope
Touch:
- `frontend/index.html` — add a `<span class="provider-card-status" id="...-status" aria-hidden="false">`
  (or `<p>`) inside each of the three provider cards (`#provider-card-gemini/openrouter/deepseek`).
  Keep it empty by default. Optionally add to DeepSeek model cards if a key gates them (it does not
  per-model — DeepSeek key gates the provider, so card-level on the provider card is sufficient).
- `frontend/js/landing.js` — extend `syncExplainerProviderUI()` (lines 256-305) to set/clear each
  card's status text + `.needs-key` class from `state` flags. Add a small helper
  `providerNeedsKey(provider)` -> bool/message if it keeps sync readable. No new listeners.
- `frontend/style.css` — `.provider-card-status` + `.provider-card.needs-key` rules (tokens only).

Do not touch:
- `validateExplainerProviderSelection` logic, the submit path, `state`.

## Constraints
(see global-constraints.md) `state` read-only; tokens only; Spanish utility copy; new logic inside
`syncExplainerProviderUI` (no listeners outside the guard).

## Interfaces
Consumes: `state.hasApiKey`, `state.hasOpenRouterKey`, `state.hasDeepSeekKey`; T2 card structure;
T3 `.disabled` treatment. Produces: `.provider-card-status` slot + `.needs-key` state.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/js/landing.js` | `syncExplainerProviderUI` | lines 256-305 | Where to set status; already toggles `.selected`/`.disabled` per card id |
| `frontend/js/landing.js` | `validateExplainerProviderSelection` | lines 112-154 | Source of truth for which key each provider needs (mirror intent, don't duplicate) |
| `frontend/js/state.js` | `state` flags | read file | `hasApiKey`,`hasOpenRouterKey`,`hasMistralKey`,`hasDeepSeekKey`,`hasTavilyKey` |
| `frontend/index.html` | provider cards | lines 238-260 | Where to add status slots |

## Existing Patterns To Reuse
- `syncExplainerProviderUI` already does `$('provider-card-x').classList.toggle('selected', …)` —
  follow the same per-card pattern for `.needs-key` and `textContent` of the status slot.

## Tests
- Extend `renderLandingDom()` (single factory) to include the status slots; add a `landingFlow`
  test that sets `state.hasOpenRouterKey=false` and asserts the OpenRouter card shows the
  needs-key copy + class after `syncExplainerProviderUI` runs (or after selecting the provider).
- `npx vitest run tests/frontend/` green.

## Task Review
Required: no
Why: final review sufficient — logic is small and covered by unit tests; submit validation
(authority) is untouched.

## Named Risks
- Don't let a card be simultaneously `disabled` (unsupported for source) AND needs-key in a way that
  hides the message — keep the status text readable in both states (works with T3's `.disabled`).
- Keep copy concise; the long contextual explanation already lives in `#explainer-provider-hint`.

## Report Path
`plans/model-selector-ux/task-T4-report.md`
