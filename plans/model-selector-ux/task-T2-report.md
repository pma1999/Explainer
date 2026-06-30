# Task T2 Report

## Status
DONE

## Outcome
All provider/model cards now share one canonical inner structure. The "Personalizado" custom card was normalized to `label[for] > input[radio] + span.provider-card-main > (span.provider-card-title + span.provider-card-sub)`. Inline styles removed from custom panel and its children; spacing moved to new CSS classes. `aria-live` attributes added to provider hint/error elements. Duplicate `role="combobox"` removed from combobox wrapper div. Tests remain green (209/209).

## Acceptance Criteria
- Every card in `#explainer-provider-group`, `#openrouter-model-group`, and `#deepseek-model-group` uses the canonical structure -> pass (provider group and deepseek group already matched; openrouter preset cards already matched; custom card now normalized)
- `#openrouter-model-card-custom` converted: `for="openrouter-model-custom"` added, `.provider-card-content`/`.provider-card-desc` replaced with `.provider-card-main`/`.provider-card-sub` -> pass
- `#explainer-provider-hint` has `aria-live="polite"` -> pass
- `#explainer-provider-error` has `aria-live="assertive"` -> pass
- Wrapper `<div>` in `openrouter-combobox.js` no longer has `role="combobox"`; input retains sole role -> pass
- `#openrouter-provider-only` checkbox + label have no inline `style` attributes; `.provider-only-toggle` CSS class added with flex/gap/accent-color/font/color rules -> pass
- Inline `margin-top` on `#openrouter-custom-panel` and inner elements removed; `.openrouter-custom-panel` CSS class added + id rules for fetch-error, loading, fetch-error -> pass
- `syncExplainerProviderUI` still toggles `.selected` on `#openrouter-model-card-custom` by id (no inner span reads) -> pass (unchanged)
- `npx vitest run tests/frontend/` -> pass (209/209)

## Files Changed
- `frontend/index.html` - modified; lines 285-323 custom card + custom panel: normalized custom card markup, removed all inline styles, updated checkbox label class; lines 344-347 provider hint/error: added aria-live attributes
- `frontend/js/components/openrouter-combobox.js` - modified; removed `wrapper.setAttribute("role", "combobox")` from line 43 (wrapper creation block)
- `frontend/style.css` - modified; added `.provider-only-toggle` (label+input+span rules) and `.openrouter-custom-panel` + child spacing rules after `.openrouter-model-grid .provider-card`

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `frontend/index.html` | `#openrouter-model-card-custom` label | Added `for`, replaced `.provider-card-content`/`.provider-card-desc` div with `.provider-card-main`/`.provider-card-sub` span structure |
| `frontend/index.html` | `#openrouter-custom-panel` div | Added class `openrouter-custom-panel`, removed `style="margin-top:12px;"` |
| `frontend/index.html` | second `.form-group` in custom panel | Removed `style="margin-top:10px;"` |
| `frontend/index.html` | `#openrouter-provider-fetch-error` | Removed `style="margin-top:6px;"` |
| `frontend/index.html` | checkbox label `.checkbox-label` | Changed class to `provider-only-toggle`, added `for`, removed all inline styles |
| `frontend/index.html` | `#openrouter-provider-only` input | Removed `style="accent-color:var(--amber);"` |
| `frontend/index.html` | inner span of toggle label | Removed `style="font-family:...;font-size:...;color:..."` |
| `frontend/index.html` | `#openrouter-custom-loading` | Removed `style="margin-top:8px;"` |
| `frontend/index.html` | `#openrouter-custom-fetch-error` | Removed `style="margin-top:8px;"` |
| `frontend/index.html` | `#explainer-provider-hint` | Added `aria-live="polite"` |
| `frontend/index.html` | `#explainer-provider-error` | Added `aria-live="assertive"` |
| `frontend/js/components/openrouter-combobox.js` | `createCombobox` wrapper div | Removed `wrapper.setAttribute("role", "combobox")` |
| `frontend/style.css` | `.provider-only-toggle` | New rule: flex row, gap 8px, margin-top 8px, cursor pointer; child input accent-color; child span font/size/color |
| `frontend/style.css` | `.openrouter-custom-panel` | New rule: margin-top 12px |
| `frontend/style.css` | `.openrouter-custom-panel .form-group + .form-group` | New rule: margin-top 10px |
| `frontend/style.css` | `#openrouter-provider-fetch-error` | New rule: margin-top 6px |
| `frontend/style.css` | `#openrouter-custom-loading, #openrouter-custom-fetch-error` | New rule: margin-top 8px |

## Tests
- Command: `npx vitest run tests/frontend/`
  Result: pass — 17 test files, 209 tests, 0 failures

## TDD Evidence
- RED: N/A — no behavior change; tests stayed green throughout (no new test assertions needed for structural/markup changes)
- GREEN: `npx vitest run tests/frontend/` — 209/209 pass after all changes

## Read Ledger
Planned reads:
- `frontend/index.html` lines 238-347 — current provider/model/custom markup including inconsistent custom card and inline styles
- `frontend/js/landing.js` lines 256-305 — `syncExplainerProviderUI` confirmed it reads no inner spans, only card ids
- `frontend/js/components/openrouter-combobox.js` lines 38-62, 190-213 — confirmed wrapper has duplicate role on line 43; open/close update both wrapper and input aria-expanded (both kept per brief)
- `frontend/style.css` lines 1-30, 601-740 — design tokens, `.form-group`, `.provider-card`, `.openrouter-model-panel`
- `tests/frontend/landingFlow.test.js` — confirmed `renderLandingDom()` does not hardcode `.provider-card-content`/`.provider-card-desc`; label at line 81 uses `checkbox-label` but no landing.js code queries by that class (JS uses `#openrouter-provider-only` id only) so no factory update needed

Extra reads:
- `frontend/style.css` (checkbox-label grep) — confirmed `.checkbox-label` has no CSS rule; only present as class in HTML (all styling was inline)
- `frontend/js/landing.js` lines 1-30, 221-232 — confirmed provider-only checkbox is always referenced by id, not label class

Pack gaps:
- None

## Decisions
- Kept `aria-expanded` mirroring on the wrapper div (lines 198, 209 in combobox.js) — brief explicitly says "Do not touch the input's ARIA or the open/close `aria-expanded` updates"; only `role="combobox"` on wrapper was removed
- Used class selector `.openrouter-custom-panel` added to the div (alongside the id) rather than a CSS id selector, to match the brief's stated rule name
- Changed `class="checkbox-label"` to `class="provider-only-toggle"` on the toggle label — `.checkbox-label` had no CSS rule (all styling was inline); `.provider-only-toggle` is the new owner of that styling
- Added `for="openrouter-provider-only"` to the toggle label — redundant since input is nested, but improves semantic clarity; no test impact
- `renderLandingDom()` in `landingFlow.test.js` did not need updating — the factory uses bare card labels with no inner markup for `openrouter-model-card-custom`, and the checkbox label class is not asserted anywhere in tests

## Concerns / Follow-ups
- None
