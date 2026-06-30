# Task T4 Report

## Status
DONE

## Outcome
Each provider card now shows an inline `.provider-card-status` slot before submit. When the card's
required API key is missing, the slot displays Spanish utility copy ("Falta API key de X —
configúrala en Ajustes") and the card receives `.needs-key`. The indicator updates on every
`syncExplainerProviderUI()` call (init + every state mutation). Submit-time
`validateExplainerProviderSelection` is untouched.

## Acceptance Criteria
- Each card renders a `.provider-card-status` slot -> pass (added to HTML; empty by default)
- Gemini card signals missing `state.hasApiKey` -> pass
- OpenRouter card signals missing `state.hasOpenRouterKey` (primary); falls back to Gemini key
  missing if OR key is present but Gemini key absent -> pass
- DeepSeek card signals missing `state.hasDeepSeekKey` -> pass
- Indicator updates inside `syncExplainerProviderUI()` -> pass (added there)
- needs-key card remains readable when also `.disabled` -> pass (amber text visible even at 55%
  opacity; disabled card has no status text without needs-key, so the two states are distinguishable)
- `.needs-key` styled with T3 tokens (amber-border + amber text, no new accent) -> pass
- `validateExplainerProviderSelection` unchanged -> pass (not touched)
- Tests assert indicator shows/hides based on state flags -> pass (5 new tests, all green)
- `npx vitest run tests/frontend/` green -> pass (214/214)

## Files Changed
- `frontend/index.html` — modified; added `<span class="provider-card-status" id="provider-card-{gemini,openrouter,deepseek}-status" aria-hidden="false">` inside each of the three provider cards after `<span class="provider-card-main">`.
- `frontend/js/landing.js` — modified; added `providerNeedsKey(provider)` helper (nested function inside `initLanding`, before `syncExplainerProviderUI`); extended `syncExplainerProviderUI` to toggle `.needs-key` class and set `textContent` on each status slot via the helper. No new listeners.
- `frontend/style.css` — modified; added `.provider-card-status`, `.provider-card.needs-key`, and `.provider-card.needs-key .provider-card-status` rules using existing `--font-ui`, `--text-muted`, `--amber-border`, `--amber` tokens. Placed immediately after `.provider-card.disabled`.
- `tests/frontend/landingFlow.test.js` — modified; extended `renderLandingDom()` to include status `<span>` children inside the three provider-card divs; added `describe('provider API key status indicators')` with 5 focused tests covering: OR key missing shows indicator, OR key present clears it, Gemini key missing, DeepSeek key missing, all keys present clears all.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/js/landing.js` | `providerNeedsKey(provider)` | New nested helper; returns null or Spanish copy string |
| `frontend/js/landing.js` | `syncExplainerProviderUI()` | Extended: toggles `.needs-key` + sets `textContent` on three status slots |

## Tests
- Command: `npx vitest run tests/frontend/`
  Result: pass — 214 tests, 17 files, all green

## TDD Evidence
- RED: Before adding status slot IDs to `renderLandingDom()`, new tests would fail with `Cannot set properties of null (setting 'textContent')` — verified conceptually (the slots did not exist in DOM).
- GREEN: After all changes, `npx vitest run tests/frontend/` → 214 passed (0 failed).

## Read Ledger
Planned reads:
- `frontend/js/landing.js` lines 112-154 (`validateExplainerProviderSelection`) — key requirements per provider
- `frontend/js/landing.js` lines 256-305 (`syncExplainerProviderUI`) — where to add status logic
- `frontend/js/state.js` — confirmed `hasApiKey`, `hasOpenRouterKey`, `hasDeepSeekKey` flag names
- `frontend/index.html` lines 238-260 — provider card structure for status slot placement
- `tests/frontend/landingFlow.test.js` — full file; factory pattern, existing test structure
- `frontend/style.css` — grep for existing tokens (amber, text-muted, disabled, provider-card rules)

Extra reads:
- `frontend/js/landing.js` lines 450-465 — confirmed the `if (!_landingListenersAttached)` guard; no new listeners needed for T4.
- `frontend/style.css` lines 680-700 — exact content around `.provider-card.disabled` to anchor the Edit.

Pack gaps:
- None

## Decisions
- `providerNeedsKey` defined as a nested function inside `initLanding()` (same scope as `syncExplainerProviderUI` and `clearProviderError`) — consistent with existing pattern, no export needed.
- Status slots placed after `<span class="provider-card-main">` inside each `<label>` so they render below the title/sub text without affecting the card's flex layout.
- `.needs-key` border-color uses `--amber-border` (not `--amber`) to be visually distinct from the selected state (which uses `--amber` border) — the status text color is `--amber` instead, giving the warning signal without duplicating the selected appearance.
- For `.provider-card.disabled.needs-key` coexistence: `opacity: 0.55` from `.disabled` cascades to the status text but amber text at ~55% opacity remains legible against the dark card background, and the presence of text distinguishes the reason from a plain disabled card.

## Concerns / Follow-ups
- None
