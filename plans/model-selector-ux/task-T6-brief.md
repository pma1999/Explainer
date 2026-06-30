# Task T6: State persistence — localStorage save/restore with validation + fallback

## Goal
Persist the user's selector configuration to `localStorage` and restore it on landing (re)entry,
validating every field and falling back to safe defaults so a missing key / unavailable provider /
corrupt data never breaks the UI.

## Acceptance Criteria
- One key only: `explainer.modelSelector.v1`. Schema (JSON):
  ```
  {
    "explainerProvider": "gemini"|"openrouter"|"deepseek",
    "openrouterMode": "preset"|"custom",
    "openrouterModel": "<preset id>",            // preset mode
    "customOpenrouterModel": "<author/slug>"|null,
    "openrouterProvider": "<slug>"|"",
    "openrouterProviderOnly": boolean,
    "deepseekModel": "deepseek-v4-pro"|"deepseek-v4-flash"
  }
  ```
- `persistModelSelector()` writes the current module state to the key. It is called after each
  selection mutation: `setExplainerProvider`, `setOpenRouterModel` (both preset and custom-commit),
  `setDeepSeekModel`, the provider-only checkbox change, and the custom model `onSelect` /
  provider-combobox commit. Do NOT call it inside `handleUpload`'s post-submit reset (persist the
  last explicit user selection, not the ephemeral reset). Wrap writes in try/catch (storage may throw).
- `restoreModelSelector()` reads + parses safely (try/catch; ignore corrupt/missing -> no-op) and
  validates BEFORE applying:
  - `explainerProvider` must be in `{gemini,openrouter,deepseek}` else default `gemini`.
  - Provider availability fallback: if restored provider is unsupported for the current source type
    (`isExplainerProviderSupportedForSource`) OR its PRIMARY key is missing
    (openrouter -> `state.hasOpenRouterKey`, deepseek -> `state.hasDeepSeekKey`; gemini -> `state.hasApiKey`),
    fall back to `gemini`. (Submit-time `validateExplainerProviderSelection` still enforces the full
    key set — restore only needs the primary key to avoid landing on an unusable provider.)
  - `openrouterModel` validated via `isPresetOpenRouterModel`/`isValidOpenRouterModel`; invalid ->
    preset default `OPENROUTER_MODEL_MIMO_PRO`.
  - `deepseekModel` validated via `isValidDeepSeekModel`; invalid -> `DEEPSEEK_MODEL_V4_PRO`.
  - `openrouterMode` in `{preset,custom}`; `openrouterProviderOnly` coerced to boolean.
- Restore APPLIES via the existing local setters (so `syncExplainerProviderUI` runs), then is
  followed by the existing `syncExplainerProviderUI()` at end of `initLanding`. Place the
  `restoreModelSelector()` call inside `initLanding` after the setters are defined and before the
  final `syncExplainerProviderUI()` (line 569).
- **Custom-mode restore (critical):** if restored `openrouterMode === 'custom'` with a valid
  `customOpenrouterModel`, restore must drive the custom path: call `setOpenRouterModel('__custom__')`
  (which lazily loads models + builds the combobox), and once loaded set the combobox value +
  `currentCustomOpenRouterModel` to the saved model and re-run `fetchEndpointsForModel`, plus restore
  the saved `openrouterProvider` into the provider combobox and the provider-only checkbox. Guard the
  async step like T5 (bail if user changed mode meanwhile).
- Restore is idempotent across SPA re-entries (module vars persist in-session; re-applying the same
  saved value is harmless).
- Tests cover: round-trip save/restore; corrupt JSON -> safe default; persisted unavailable provider
  (key missing) -> falls back to gemini; preset round-trip; deepseek round-trip; custom-mode restore
  path. `npx vitest run tests/frontend/` green.

## Scope
Touch:
- `frontend/js/landing.js` — add `persistModelSelector()` + `restoreModelSelector()`; insert
  `persistModelSelector()` calls into the existing setters and the provider-only/custom-select
  mutation points; add the `restoreModelSelector()` call in `initLanding` before line 569.
  Export `restoreModelSelector` (and any pure validator) for tests if needed.

Do not touch:
- The submit payload shape; the SSE call ordering in `handleUpload`; `state`; backend.

## Constraints
(see global-constraints.md) Single key `explainer.modelSelector.v1`; never throw on corrupt data;
validate before applying; `state` read-only; new logic must not add listeners outside the
`_landingListenersAttached` guard (persist calls go inside existing setter/handler bodies, which is fine).

## Interfaces
Consumes: setters `setExplainerProvider`/`setOpenRouterModel`/`setDeepSeekModel`, validators
`isPresetOpenRouterModel`/`isValidOpenRouterModel`/`isValidDeepSeekModel`/`isExplainerProviderSupportedForSource`,
`state.has*Key`, T5's custom combobox path. Produces: persistence helpers + the v1 schema.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `frontend/js/landing.js` | module state vars | lines 12-33 | Exact var names to persist (`currentExplainerProvider`,`currentOpenRouterModel`,`currentOpenRouterMode`,`currentCustomOpenRouterModel`,`currentOpenRouterProvider`,`currentOpenRouterProviderOnly`,`currentDeepSeekModel`) |
| `frontend/js/landing.js` | setters | lines 307-370 | Where to add persist calls; setters call `syncExplainerProviderUI` |
| `frontend/js/landing.js` | `initLanding` end | lines 455-569 | Listener guard + final sync; restore call site |
| `frontend/js/landing.js` | custom path | lines 312-348 | Custom-mode restore must reuse this (with T5 changes) |
| `frontend/js/landing.js` | validators | lines 88-110 | `isValidDeepSeekModel`, target-language validate pattern |

## Existing Patterns To Reuse
- The setter pattern (set var -> `syncExplainerProviderUI()`); add `persistModelSelector()` as the
  final line of each setter.
- Look for any existing `localStorage` usage in the frontend (e.g. `storage.js`) and match its
  guarded read/write idiom rather than inventing a new one.

## Tests
- `tests/frontend/landing.test.js`: pure validation of `restoreModelSelector` mapping/fallbacks with
  a mocked `localStorage` (jsdom provides one) — corrupt JSON, invalid provider, missing key fallback.
- `tests/frontend/landingFlow.test.js`: round-trip — set selection, assert `localStorage` value;
  re-init `renderLandingDom()` + `initLanding`, assert restored selection drives the UI; custom-mode
  restore builds the combobox and sets the custom model.
- `npx vitest run tests/frontend/` green.

## Task Review
Required: yes
Why: validation + fallback + the async custom-mode restore are risky and gate UX correctness; a
mistake silently lands users on an unusable provider or stale custom state.

## Named Risks
- Custom-mode restore async ordering (mirror T5's teardown guard) — most error-prone path.
- Persisting inside `handleUpload`'s post-submit reset would clobber the user's saved selection — avoid.
- `localStorage` can throw (private mode / quota) — all reads/writes in try/catch.

## Report Path
`plans/model-selector-ux/task-T6-report.md`
