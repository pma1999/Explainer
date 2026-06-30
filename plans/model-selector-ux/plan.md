# Plan: Model / Provider Selector UX Redesign

Bundle: `plans/model-selector-ux/`
Source map: `plans/model-selector-ux/context-map.md`
Integration recipe: `plans/model-selector-ux/integration-openrouter-models.md`

## Objective
Redesign the AI model/provider selector on the landing upload card into one coherent,
accessible, persistent system within the existing "Scholarly Forge" theme. Three-level
nesting (provider -> model -> custom) must read clearly; selected / disabled / needs-key /
loading states must be obvious before submit; the custom OpenRouter picker must surface
text-only models with readable context+price metadata; and selection must survive
navigation/reload via `localStorage`. No new theme, no new accent, no marketing chrome.

User-facing outcome: a user opening the upload card sees their last selection restored,
immediately understands which providers are usable (and which need an API key), can pick a
custom OpenRouter model with price/context badges, and gets keyboard + screen-reader
support throughout.

## Chosen Approach & Key Decisions
- **Reuse, do not rebuild.** Keep `createCombobox` (model + provider pickers), `show/hide/toast/$`
  from `dom.js`, the radio-backed `.provider-card` label pattern, the `_orModelsCache` /
  `_orEndpointsCache` pattern, and the `_landingListenersAttached` idempotency guard. The
  submit contract (`ProcessProjectRequest`) is frozen — no payload shape change.
- **Foundation first, visuals second.** Normalize all card inner markup to one structure and
  fix the worst a11y gaps (combobox role duplication, missing live regions, inline styles)
  before the CSS redesign, so CSS has one stable target structure.
- **Backend change is isolated** to `_fetch_openrouter_models` (+ test) per the integration
  recipe; it narrows the listing to text-output models. Metadata fields the UI needs
  (`context_length`, `prompt_price`, `completion_price`) are already returned.
- **Persistence is additive and validated.** One namespaced key `explainer.modelSelector.v1`;
  restore validates against valid constants + primary-provider-key availability and falls
  back to `gemini`/preset defaults; never throws on corrupt JSON.
- **Price format decision (settled, no product question):** badges show `$/1M tokens`
  (multiply per-token price by 1e6, 2 significant decimals) and render `Gratis` when price is 0.
  Context length shown as `NNK ctx` (round to nearest 1K). This matches the integration recipe.
- **Preset cards stay label-only** — the user asked for metadata only in the *custom* picker;
  preset/provider cards keep utility copy, no pricing chrome.

## Tasks & Waves
Files index.html / landing.js / style.css are shared by almost all UI tasks, so frontend
work is mostly sequential. Only the backend filter (disjoint files) parallelizes.

| Wave | Tasks | Parallel? | Why safe / why sequential |
|---|---|---|---|
| 1 | T1 (backend filter), T2 (markup+a11y foundation) | parallel | Disjoint file sets: T1 = `main.py` + `tests/backend/test_api.py`; T2 = `index.html` + `openrouter-combobox.js` + one new CSS class. No shared symbol or contract. |
| 2 | T3 (visual redesign CSS) | sequential | Depends on T2's normalized markup; owns `style.css` selector styles. |
| 3 | T4 (inline API-key status) | sequential | Adds key-status logic in `syncExplainerProviderUI` + per-card slot + `.needs-key` CSS; needs T2 markup + T3 visual base. |
| 4 | T5 (custom picker metadata + loading) | sequential | Touches `setOpenRouterModel` path in landing.js + style.css + a summary element; needs T1 contract + T3 CSS base. |
| 5 | T6 (state persistence) | sequential | landing.js only; runs last so restore wraps the final UI/setters (incl. custom-mode restore through T5's picker). |

Sequencing rationale: T4, T5, T6 all edit `landing.js` and `style.css`; running them in
order avoids contract/merge conflicts and lets each build on a stable base.

## Cross-Task Interfaces
- **T2 produces** the canonical card structure every later task targets:
  `label.provider-card[ > input[radio] ] > span.provider-card-main > (span.provider-card-title + span.provider-card-sub)`
  — applied to ALL provider and model cards including "Personalizado". Also produces:
  `#explainer-provider-hint[aria-live=polite]`, `#explainer-provider-error[aria-live=assertive]`,
  combobox input as the sole `role="combobox"` host, and `.provider-only-toggle` CSS class
  replacing the inline-styled checkbox label.
- **T3 produces** the visual state classes the UI relies on: existing `.selected` / `.disabled`
  semantics preserved; adds `:focus-visible` ring on `.provider-card`, `prefers-reduced-motion`
  guards, `<680px` responsive rules, and a `.provider-card.is-loading` / loading affordance style.
- **T4 produces** a per-card needs-key indicator: a `.provider-card-status` slot element (one per
  provider card and per model card that can lack a key) toggled by `syncExplainerProviderUI`
  based on `state.has*Key`, with a `.provider-card.needs-key` visual state (styled in T4 using
  T3's tokens). Disabled-but-needs-key cards remain readable (not pure opacity 0.45).
- **T5 consumes** `GET /api/openrouter/models` `{models:[{id,name,context_length,prompt_price,completion_price}]}`
  and produces combobox items with a formatted `meta` badge string, plus a
  `#openrouter-custom-model-summary` element rendered on selection. Adds pure formatters
  `formatModelPrice(perTokenUsd)` and `formatContextLength(n)` (exported for tests).
- **T6 consumes** all setters (`setExplainerProvider`, `setOpenRouterModel`, `setDeepSeekModel`)
  and the custom-mode mutation points; produces `persistModelSelector()` +
  `restoreModelSelector()` and the `explainer.modelSelector.v1` schema (defined in its brief).

## Verification Overview
- Frontend unit: `npx vitest run tests/frontend/` — extend the SINGLE `renderLandingDom()`
  factory in `tests/frontend/landingFlow.test.js` for new elements; add pure-fn tests in
  `tests/frontend/landing.test.js` (formatters, persistence validation, restore fallback).
- Backend: `python scripts/run_pytest.py tests/backend/test_api.py` — new test asserts
  non-text-output models are filtered out.
- E2E (where reasonable): `tests/e2e/app.spec.js` covers the landing flow; keep it green.

## Risks / Watch-outs
- **SSE coupling:** never insert an async gap between `POST /api/projects` and
  `POST /api/projects/{id}/process` in `handleUpload` (landing.js:716). No task should touch that ordering.
- **Listener duplication:** every new DOM listener must live inside the `if (!_landingListenersAttached)`
  block (landing.js:455) or it double-fires on SPA re-entry.
- **Combobox teardown race (T5):** `setOpenRouterModel` destroys/recreates `_openrouterCombobox`;
  a slow `loadOpenRouterModels().then()` can run against a stale mount after `destroy()`. Guard
  the `.then()` (check mode is still custom / mount still attached) and cover in tests.
- **Custom-mode restore (T6):** restoring `openrouterMode:"custom"` must drive the async model
  load AND re-apply the saved custom model + provider into the combobox/summary — the trickiest
  path; required in T6 acceptance + review.
- **Preset constant drift:** frontend preset IDs must stay equal to backend `OPENROUTER_EXPLAINER_MODELS`
  (main.py:161). No task changes the preset set; if one does, update both sides.
- **Provider `getValue()` is raw text** (landing.js:694) — uncommitted typed text is sent as
  `openrouter_provider`. Do not change this behavior silently; T5 may surface it but the
  submit contract stays as-is.

## Review Gates
- **T1 (backend filter):** task review = yes (shared contract for all model-list callers; verifies the defensive guard).
- **T6 (persistence/restore):** task review = yes (validation + custom-mode restore are risky and gate UX correctness).
- T2, T3, T4, T5: final review sufficient.
