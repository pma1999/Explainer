# Task T3: Visual redesign (CSS) — hierarchy, focus, motion, responsive, loading

## Goal
Restyle the whole provider/model/custom selector so the three-level nesting (provider -> model ->
custom) reads as one calm, coherent system within Scholarly Forge — strong hierarchy via spacing,
scale and type, single amber accent — and add the missing focus/motion/responsive/loading states.
Apply the `frontend` and `frontend-design` skills.

## Acceptance Criteria
- Provider grid, OpenRouter model sub-panel, custom panel, and DeepSeek sub-panel form a clear
  visual hierarchy: the nested model/custom panels read as *inside* the chosen provider (e.g. inset
  panel, restrained left accent or indentation, lighter surface) — not as a flat stack of equal cards.
  Reduce visual heaviness vs. current 4-equal-cards look.
- `.provider-card:focus-visible` (driven by the visually-hidden radio's `:focus-visible`, i.e.
  `.provider-card:has(input:focus-visible)` or `input:focus-visible + … ` per what works) shows a
  clearly visible amber focus ring. Keyboard arrow/space/enter selection still works (native radios).
- `.provider-card.selected` and `.provider-card.disabled` keep their semantics but are refined:
  selected = amber border + `--amber-dim` fill; disabled stays distinguishable yet de-emphasized
  (do not rely on opacity so low it becomes unreadable — T4 will layer needs-key on top).
- All new transitions/animations are wrapped so `@media (prefers-reduced-motion: reduce)` disables them.
- Responsive: under `max-width:680px` the provider grid, the 4-up OpenRouter model grid, and the
  custom panel stack cleanly without runaway height — model grid collapses to 1-col, custom panel
  contents (combobox + provider combobox + toggle) remain readable and bounded. Verify the combobox
  listbox `max-height` still applies on mobile.
- Loading affordance: a `.provider-card.is-loading` style (and/or a panel-level loading style) that
  visibly indicates the async model fetch is in progress when switching to OpenRouter custom. (Wiring
  the class toggle is T5; T3 only provides the style and must keep `#openrouter-custom-loading`
  styled coherently.)
- No new theme/accent; tokens only. `npx vitest run tests/frontend/` stays green (CSS-only changes
  should not affect logic tests).

## Scope
Touch:
- `frontend/style.css` — selector-related rules: `.provider-grid`, `.provider-card` (+ `.selected`,
  `.disabled`, focus, loading), `.openrouter-model-panel`/`.openrouter-model-grid`,
  `.openrouter-custom-panel`, combobox spacing within the panel, and the `<680px` media block.
  Reference current rules at lines 651-730, combobox 5173-5327, mobile rule ~2741.
- `frontend/index.html` — ONLY to add minimal styling hook classes if strictly needed (e.g. a
  wrapper class). Prefer styling existing structure from T2. Do not change ids or copy.

Do not touch:
- `landing.js` logic, the submit path, combobox component JS, backend.

## Constraints
(see global-constraints.md) Tokens-only; single amber accent; respect `prefers-reduced-motion`;
utility copy unchanged. Build on T2's normalized markup.

## Interfaces
Consumes: T2 canonical card structure + `.provider-only-toggle` / `.openrouter-custom-panel`.
Produces: `.provider-card:focus-visible` ring, `.provider-card.is-loading` style, refined
`.selected`/`.disabled`, responsive `<680px` rules — all reused by T4/T5.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/style.css` | `:root` tokens | lines 7-30 | The only palette/fonts allowed |
| `frontend/style.css` | `.provider-grid`,`.provider-card`,`.selected`,`.disabled` | lines 651-730 | Current card visuals to refine |
| `frontend/style.css` | combobox styles | lines 5173-5327 | Listbox max-height/animation already respect reduced-motion |
| `frontend/style.css` | provider-grid mobile rule | ~line 2741 | Existing 1-col breakpoint to extend |
| `frontend/index.html` | selector markup (post-T2) | lines 238-347 | Structure to style |

## Existing Patterns To Reuse
- Combobox already implements `prefers-reduced-motion` — mirror that media-query approach for cards.
- Reuse existing `.input-hint` / `.input-error` typographic scale for sub-panel text.

## Tests
- `npx vitest run tests/frontend/` stays green.
- `tests/e2e/app.spec.js` (Playwright) — keep the landing flow passing; optionally add a viewport
  check that the selector is usable at narrow width if cheap.
- Visual check at desktop and <680px: hierarchy clear, focus ring visible via keyboard tab,
  reduced-motion disables transitions.

## Task Review
Required: no
Why: final review is sufficient — visual change validated against the design bar at final gate.

## Named Risks
- Visually-hidden radios (`position:absolute;opacity:0`) make focus styling indirect — verify the
  `:focus-visible` ring actually appears on keyboard focus (use `:has()` or sibling selector; test in browser).
- Over-nesting can make mobile height explode; cap panel/listbox heights.

## Report Path
`plans/model-selector-ux/task-T3-report.md`
