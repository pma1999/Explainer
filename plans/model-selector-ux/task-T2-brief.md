# Task T2: Frontend foundation — markup normalization + a11y attributes + combobox role fix

## Goal
Give every provider/model card one identical inner structure, fix the highest-impact a11y gaps,
and remove inline styles — producing the stable DOM that the visual redesign and later JS build on.
No behavior change to selection logic.

## Acceptance Criteria
- Every card in `#explainer-provider-group`, `#openrouter-model-group`, and `#deepseek-model-group`
  uses the SAME inner structure:
  `<label class="provider-card" id=... for=...><input type="radio" .../><span class="provider-card-main"><span class="provider-card-title">…</span><span class="provider-card-sub">…</span></span></label>`.
- The "Personalizado" card (`#openrouter-model-card-custom`) is converted to that structure:
  add `for="openrouter-model-custom"` on the label, replace `.provider-card-content`/`.provider-card-desc`
  with `.provider-card-main`/`.provider-card-sub`. Keep its id and the radio id/value `__custom__`.
- `#explainer-provider-hint` gets `aria-live="polite"`; `#explainer-provider-error` gets
  `aria-live="assertive"`.
- In `openrouter-combobox.js`, remove the duplicate `role="combobox"` on the wrapper `<div>`
  (line 43). The `<input>` remains the sole `role="combobox"`. Do not touch the input's ARIA or
  the open/close `aria-expanded` updates.
- The `#openrouter-provider-only` checkbox + label lose all inline `style="…"` attributes; styling
  moves to a new CSS class `.provider-only-toggle` (label) in `style.css` reproducing the current
  look (flex row, gap 8px, `accent-color:var(--amber)`, label text `--font-ui` 13px `--text-secondary`).
- Remove the inline `style="margin-top:…"` attributes on `#openrouter-custom-panel` and its inner
  `.form-group`s / error/loading `<p>`s; move equivalent spacing to CSS (a `.openrouter-custom-panel`
  rule + reuse existing `.form-group` margins). Do not change ids.
- `syncExplainerProviderUI` still toggles `.selected` on `#openrouter-model-card-custom` correctly
  (it reads no inner spans, so this must still work). `npx vitest run tests/frontend/` stays green.

## Scope
Touch:
- `frontend/index.html` — lines 261-323 (OR model panel incl. custom card + custom panel) and
  the hint/error `<p>` at lines 344-347. Provider grid (238-260) and deepseek grid (325-343) only
  if their structure already matches (they do — verify, leave as-is unless inconsistent).
- `frontend/js/components/openrouter-combobox.js` — line 43 only.
- `frontend/style.css` — add `.provider-only-toggle` and `.openrouter-custom-panel` spacing rules
  using existing tokens. Do NOT restyle cards here (that is T3).

Do not touch:
- Any selection logic in `landing.js`, the radio `name`/`value`/`id` attributes, the combobox
  input ARIA, or the submit path.

## Constraints
(see global-constraints.md) Tokens-only CSS; no `el.style.display`; Spanish utility copy unchanged;
exactly one `role="combobox"` (on input).

## Interfaces
Produces (consumed by T3/T4/T5):
- Canonical card structure `.provider-card > input[radio] + .provider-card-main > (.provider-card-title + .provider-card-sub)` on ALL cards.
- `.provider-only-toggle` CSS class; `.openrouter-custom-panel` spacing rule.
- `#explainer-provider-hint[aria-live=polite]`, `#explainer-provider-error[aria-live=assertive]`.
Consumes: existing ids and the `createCombobox` API (unchanged).

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/index.html` | provider/model/custom markup | lines 238-347 | Current structure incl. the inconsistent custom card + inline styles |
| `frontend/js/landing.js` | `syncExplainerProviderUI` | lines 256-305 | Confirms JS toggles classes on card ids only (safe to restructure inner spans) |
| `frontend/js/components/openrouter-combobox.js` | wrapper vs input roles | lines 41-55, 197-210 | open/close already set input aria-expanded; only wrapper role 43 must go |
| `frontend/style.css` | `.provider-card`, tokens | lines 7-30, 651-730 | Existing card classes + token names |

## Existing Patterns To Reuse
- `.checkbox-label` pattern already exists in `style.css` for similar toggles — model
  `.provider-only-toggle` on it (read its rule before writing).
- Provider-card label/radio pattern (context-map "Existing Patterns").

## Tests
- `npx vitest run tests/frontend/` — must stay green (no logic change). If `renderLandingDom()`
  in `landingFlow.test.js` mirrors the custom card markup, update the factory to match the new
  structure (single factory, do not duplicate).
- Manual/visual: custom card still selectable; checkbox still toggles; combobox still opens.

## Task Review
Required: no
Why: final review is sufficient — structural/markup change verified by the existing green suite.

## Named Risks
- If `renderLandingDom()` hardcodes `.provider-card-content`/`.provider-card-desc` for the custom
  card, the factory must be updated in lockstep or T5/T4 tests break.

## Report Path
`plans/model-selector-ux/task-T2-report.md`
