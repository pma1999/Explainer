# Task T5: Custom OpenRouter picker — metadata badges, chosen-model summary, loading wiring

## Goal
In the custom OpenRouter combobox, show each option's context length + price as readable badges,
show a small summary of the chosen model below the picker, and wire a visible loading affordance
while the model list fetches. Reuse the combobox's existing `.combobox-option-meta` slot.

## Acceptance Criteria
- Pure formatters added to `landing.js` and EXPORTED for tests:
  - `formatModelPrice(perTokenUsd)` -> `Gratis` when value is exactly 0, else `$<N>/1M` where
    `<N>` = `perTokenUsd * 1e6` formatted to a sensible precision (e.g. 2 decimals, trim trailing).
  - `formatContextLength(n)` -> `<k>K ctx` (e.g. `128000` -> `128K ctx`); handle 0/undefined -> `''`.
- When building combobox items in `setOpenRouterModel('__custom__')` (lines 318-347), each item's
  `meta` is a readable badge string combining context + prompt price, e.g.
  `128K ctx · $0.50/1M` (prompt price; or show both prompt/completion compactly). The combobox
  already renders `item.meta` into `.combobox-option-meta` — keep `value`=`id`, `label`=`name`,
  `sublabel`=`id` as today; only enrich `meta`.
- On selection (`onSelect`), populate a new `#openrouter-custom-model-summary` element with a short
  human summary of the chosen model (name, id, context, price). Summary uses `show/hide`, not
  `style.display`. Styled in `style.css` with tokens (badge chips). Hidden when no model chosen.
- Loading affordance: while `loadOpenRouterModels()` is in flight, add the `.is-loading` class
  (from T3) to the `#openrouter-model-card-custom` card (and keep `#openrouter-custom-loading`
  visible via existing `show`), removing it when the promise settles (success or error).
- Teardown-race guard: in the `loadOpenRouterModels().then(...)` callback, before creating the new
  combobox, bail out if the user has left custom mode (`currentOpenRouterMode !== 'custom'`) or the
  mount element is detached — so a slow fetch can't build a combobox onto a stale/cleared mount.
- Badges keep the option row readable on mobile (coordinate with T3's `<680px` rules; do not let
  meta overflow the row).
- `npx vitest run tests/frontend/` green incl. new formatter tests and a metadata-mapping test.

## Scope
Touch:
- `frontend/js/landing.js` — `setOpenRouterModel` custom branch (items `.map`, lines 326-330 map +
  `onSelect` 331-341), `loadOpenRouterModels` (372-386) for loading-class toggle + guard, and two
  new exported pure formatters near the other pure helpers (e.g. by lines 97-110).
- `frontend/index.html` — add `#openrouter-custom-model-summary` element inside
  `#openrouter-custom-panel` (after the model combobox `.form-group`, ~line 299), default `.hidden`.
- `frontend/style.css` — `.openrouter-custom-model-summary` + badge/chip styles (tokens only).

Do not touch:
- The submit payload build (`handleUpload`) shape; provider combobox population logic
  (`fetchEndpointsForModel`) beyond what already runs; backend.

## Constraints
(see global-constraints.md) Reuse `createCombobox` (do not modify it beyond reading `.combobox-option-meta`
which already exists); `show/hide` only; tokens only; price format `$/1M`, `Gratis` for 0;
new listeners (if any) inside the `_landingListenersAttached` guard.

## Interfaces
Consumes: `GET /api/openrouter/models` `{models:[{id,name,context_length,prompt_price,completion_price}]}`
(text-only after T1); combobox `item.meta` -> `.combobox-option-meta` (component lines 124-130);
T3 `.is-loading` style. Produces: `formatModelPrice`, `formatContextLength` (exported);
`#openrouter-custom-model-summary` element.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/js/landing.js` | `setOpenRouterModel` custom branch | lines 312-348 | Where items are mapped + combobox created; add meta + guard |
| `frontend/js/landing.js` | `loadOpenRouterModels` | lines 372-386 | Loading state + cache; add `.is-loading` toggle |
| `frontend/js/components/openrouter-combobox.js` | option render | lines 104-130 | Confirms `item.meta` -> `.combobox-option-meta` already supported |
| `frontend/style.css` | `.combobox-option-meta` | lines 5173-5327 | Existing meta slot styling to extend for badges |
| `plans/model-selector-ux/integration-openrouter-models.md` | price/ctx notes | whole file | Per-token USD, `Gratis` for 0, format rules |

## Existing Patterns To Reuse
- `formatProviderItems` (landing.js:415) shows the item-shaping pattern (`value/label/sublabel/meta`).
- `_orModelsCache` caching already in `loadOpenRouterModels` — do not refetch.

## Tests
- `tests/frontend/landing.test.js`: unit-test `formatModelPrice` (0 -> `Gratis`; small float -> `$/1M`)
  and `formatContextLength`.
- `tests/frontend/landingFlow.test.js`: extend `renderLandingDom()` with `#openrouter-custom-model-summary`;
  assert custom-mode items carry a non-empty `meta` and that selecting a model fills the summary.
  Cover the teardown guard if feasible (switch away mid-fetch -> no combobox built on stale mount).
- `npx vitest run tests/frontend/` green.

## Task Review
Required: no
Why: final review sufficient — formatters and mapping are unit-tested; the risky teardown guard is
covered by an explicit test.

## Named Risks
- Teardown race: slow `loadOpenRouterModels().then()` running after the user left custom mode (see
  plan + context-map risk) — the guard in the `.then()` is mandatory.
- Price floats are tiny (per token); forgetting `*1e6` makes badges read `$0.00` — the formatter test guards this.

## Report Path
`plans/model-selector-ux/task-T5-report.md`
