# Task T3 Report

## Status
DONE

## Outcome
`frontend/style.css` now delivers a clear 3-level visual hierarchy (provider → model sub-panel → custom panel), motion-safe transitions, a visible amber focus ring on keyboard navigation, a `.provider-card.is-loading` affordance with a guarded pulse animation, a CSS spinner for `#openrouter-custom-loading`, and extended responsive rules under 680px. No HTML or JS was changed.

## Acceptance Criteria

- Provider grid / model panel / custom panel form a clear hierarchy: provider cards on `--bg-elevated`; model sub-panel on `--bg-surface` with a 3px `--amber-border` left accent; custom panel on `--bg-base` with `--radius-sm` — three distinct surface depths. -> **pass**
- `.provider-card:has(input:focus-visible)` shows a 2px amber outline + 4px `--amber-dim` ring. Keyboard Tab/arrow still works (native radio semantics preserved). -> **pass** (CSS rule applied; browser verified visually)
- `.provider-card.selected` uses `--amber-dim` fill + `--amber-border` box-shadow (tokens only, no hardcoded rgba gradient). `.provider-card.disabled` at 0.55 opacity + grayscale(0.25) — readable, T4 can overlay. -> **pass**
- All new transitions and `card-pulse` / `spin-loader` animations are inside `@media (prefers-reduced-motion: no-preference)` blocks. The base `.provider-card` has no `transition` property. -> **pass**
- Responsive <680px: `.provider-grid` collapses to 1-col (pre-existing + extended); `.openrouter-model-panel` reduces to 2px accent + tighter padding; `.openrouter-custom-panel` reduces padding; `.combobox-listbox` capped at 200px height. -> **pass**
- `.provider-card.is-loading` shows `cursor:wait`, amber border/fill, and a guarded pulse animation. `#openrouter-custom-loading` shows an amber spinner (CSS `::before`) guarded by motion preference. -> **pass**
- No new theme tokens introduced; single amber accent reused. -> **pass**
- `npx vitest run tests/frontend/` -> **pass** (209/209)

## Files Changed

- `frontend/style.css` — modified; selector-area rules only (lines ~657–867 and the 680px media block)

## Symbol Change Summary

| File | Symbol / contract | Change |
|---|---|---|
| `frontend/style.css` | `.provider-card` base | Removed `transition` (moved to motion-safe block) |
| `frontend/style.css` | `.provider-card:hover` | Selector tightened to `:not(.disabled):not(.is-loading)`; transform removed from base hover |
| `frontend/style.css` | `.provider-card.selected` | Replaced hardcoded rgba gradient with `--amber-dim`/`--amber-border` tokens |
| `frontend/style.css` | `.provider-card.disabled` | Opacity raised 0.45→0.55; removed redundant `transform:none`; filter lightened |
| `frontend/style.css` | `.provider-card:has(input:focus-visible)` | **New** — amber focus ring for visually-hidden radio |
| `frontend/style.css` | `@media no-preference .provider-card` | **New** — motion-safe transition block |
| `frontend/style.css` | `.provider-card.is-loading` | **New** — loading affordance + guarded `card-pulse` animation |
| `frontend/style.css` | `.openrouter-model-panel` | `bg-surface` + 3px amber left accent; margin/padding tweak |
| `frontend/style.css` | `.openrouter-model-grid .provider-card` | `min-height` 82→72px (compact in sub-panel) |
| `frontend/style.css` | `.openrouter-custom-panel` | **Extended** with `bg-base` surface + border + `radius-sm` |
| `frontend/style.css` | `#openrouter-custom-loading` | **New** flex+spinner via `::before`; `spin-loader` keyframe guarded |
| `frontend/style.css` | `@media (max-width: 680px)` | Extended: model-panel, custom-panel, combobox listbox cap |

## Tests

- Command: `npx vitest run tests/frontend/`
  Result: **pass** — 17 test files, 209 tests, 0 failures

## TDD Evidence

- RED: N/A — CSS-only change; no logic tests cover visual rules. Tests were green before and after.
- GREEN: `npx vitest run tests/frontend/` — 209 passed, 1.85s

## Read Ledger

Planned reads:
- `frontend/style.css` lines 7-30 — `:root` tokens
- `frontend/style.css` lines 651-730 — existing card rules to refine
- `frontend/style.css` lines 5173-5327 — combobox styles (motion pattern)
- `frontend/style.css` ~line 2741 — existing 680px breakpoint
- `frontend/index.html` lines 238-347 — T2 markup structure

Extra reads:
- `frontend/style.css` lines 483-500 — `.input-hint` / `.input-error` typographic scale (to confirm `#openrouter-custom-loading` inherits appropriately before overriding with `display:flex`)
- `frontend/style.css` lines 749-763 — existing `.openrouter-custom-panel` + loading element rules (exact text for Edit precision)

Pack gaps: None

## Decisions

- **`:has()` for focus ring** — used `label.provider-card:has(input:focus-visible)` which is the cleanest approach and widely supported (Chrome 105+, Firefox 121+, Safari 15.4+). The radio's `position:absolute; inset:0; opacity:0` does not prevent keyboard Tab focus; `pointer-events:none` only suppresses mouse events, not keyboard focus.
- **Surface depth order** — provider cards on `--bg-elevated` (#1f2937), model panel on `--bg-surface` (#161b22), custom panel on `--bg-base` (#0d1117). In the dark theme this reads as progressive inset/depth without needing new tokens.
- **Left accent on `.openrouter-model-panel`** — `border-left: 3px solid --amber-border` (25% opacity amber) rather than full amber, to signal nesting without competing with the selected-card amber. The `border` shorthand sets all sides first, then `border-left` overrides just the left.
- **`#openrouter-custom-loading` as `display:flex`** — overrides the block `<p>` to align the spinner and text horizontally. Safe because `.input-hint` does not set `display`.
- **Loading state without `opacity`** — `.provider-card.is-loading` uses amber fill + wait cursor; the `card-pulse` animation adds visual motion when motion is allowed, but the static state is still clearly distinguishable without animation.
- **`min-height` of model sub-cards** reduced 82→72px — cards inside the sub-panel benefit from being visually lighter/tighter than the top-level provider cards.

## Concerns / Follow-ups

- T4 will layer a "needs API key" indicator on `.provider-card.disabled`; current opacity 0.55 leaves room for overlay text to remain legible.
- T5 will wire `.provider-card.is-loading` class toggle; the CSS is ready.
- The `::before` spinner on `<p>` works in all modern browsers; if a very old browser is needed, a fallback (e.g., `…` text) is already present in the element's text content (`"Cargando modelos…"`).
