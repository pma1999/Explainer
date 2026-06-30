# Review: final — Model / Provider Selector UX Redesign

## Verdict
PASS

## Functional Verification
- `npx vitest run tests/frontend/`: **252/252 passed** (17 suites, 1.93 s). Run confirmed live in this session.
- `python scripts/run_pytest.py tests/backend/test_api.py`: **29/29 passed** (1.78 s). Run confirmed live.
- T1 task review was previously completed and confirmed PASS (29/29 backend, 1.88 s).
- Test growth across tasks: 209 (post-T2/T3) → 214 (post-T4) → 229 (post-T5) → 252 (post-T6).

## Spec Compliance

### Cross-task integration (T2 markup consumed by T3 / T4 / T5)
- T2's canonical structure `label.provider-card > input[radio] + span.provider-card-main > (span.provider-card-title + span.provider-card-sub)` is correctly consumed by all later tasks. Verified by reading HTML diff and each task's CSS/JS selectors.
- T3 targets `.provider-card`, `.openrouter-model-panel`, `.openrouter-custom-panel` — all match T2 output.
- T4 appends `.provider-card-status` after `span.provider-card-main` inside each provider card — matches T2 structure; `syncExplainerProviderUI` reads cards by ID only, no inner-span reads that could break on structure change.
- T5 targets `#openrouter-model-card-custom` by ID, `#openrouter-custom-model-summary` new element, combobox mount `#openrouter-custom-model-combobox` — all correct.
- Dead CSS: pre-existing rules `.provider-card-content` and `.provider-card-desc` (style.css lines 5501-5512, present since baseline at lines 5316-5322) were not removed when T2 changed the HTML. They are orphaned (no HTML element matches them) but harmless. Not a required change.

### Frozen contracts
- `ProcessProjectRequest` shape (main.py lines 179-185): `explainer_provider`, `openrouter_model`, `target_language`, `deepseek_model`, `openrouter_provider`, `openrouter_provider_only` — unchanged. Confirmed by reading current code and verifying the diff does not touch that class.
- Frontend preset IDs (`OPENROUTER_MODEL_MIMO_PRO = 'xiaomi/mimo-v2.5-pro'`, `OPENROUTER_MODEL_MIMO = 'xiaomi/mimo-v2.5'`, `OPENROUTER_MODEL_DEEPSEEK_V4_PRO = 'deepseek/deepseek-v4-pro'`) equal backend `OPENROUTER_EXPLAINER_MODELS` (main.py lines 163-165) exactly. Neither side was changed.
- `GET /api/openrouter/models` response shape `{models, stale, fetched_at}` with model dict `{id, name, context_length, prompt_price, completion_price}` unchanged. T1 only narrowed the list contents; shape was confirmed by `test_response_model_shape_is_unchanged`.

### Accessibility floor
- Exactly one `role="combobox"`: on the `<input>` element (openrouter-combobox.js line 49). Wrapper div `role="combobox"` removed by T2 (openrouter-combobox.js diff confirmed). Wrapper retains `aria-expanded` / `aria-controls` mirror (per T2 brief intent).
- `#explainer-provider-hint` has `aria-live="polite"` (index.html line 348). Met.
- `#explainer-provider-error` has `aria-live="assertive"` (index.html line 351). Met.
- `.provider-card:has(input:focus-visible)` — amber 2px outline + 4px `--amber-dim` ring (style.css line 752). Visually hidden radios have `pointer-events:none` but NOT `tabindex=-1`; keyboard Tab and arrow navigation remain intact via native radio semantics.
- `prefers-reduced-motion` guards: all transitions moved to `@media (prefers-reduced-motion: no-preference)` at style.css lines 759-768; `card-pulse` guarded at line 786; `spin-loader` guarded at line 850. Base `.provider-card` has no `transition`. Met.

## Code Quality

### Positive findings
- Backend filter (`_fetch_openrouter_models`): both the server-side `params` and the in-comprehension guard are correct. The guard handles missing `architecture` key, absent `output_modalities`, and non-text lists. Exception boundary at line 4119 catches the edge case of `{"architecture": null}` safely.
- `formatModelPrice` / `formatContextLength`: pure, exported, well-tested (12 unit tests). `toPrecision(2)` + `parseFloat().toString()` correctly strips trailing zeros. `Gratis` for exactly-0 price. `''` for falsy context length.
- `persistModelSelector` + `restoreModelSelector`: try/catch on both read and write, JSON parse errors return null, all fields validated before applying, provider key fallback correct, deepseek/openrouter model validation against existing helpers.
- Teardown-race guards in T5 and T6 are both present and mirror each other correctly.
- `handleUpload` was not modified by any task — no async gap was introduced between `POST /api/projects` and `POST /api/projects/{id}/process`.
- No `el.style.display` usage found in landing.js. All show/hide via `show()`/`hide()` from dom.js.
- `state` is only read, not mutated, in all new code.

### Minor observations (not required changes)
- `formatModelPrice(null)` returns `$0/1M` instead of `Gratis`. Unreachable in practice: the backend always serializes prices as `float` (never null), and the summary-rendering path guards with `?? 0` at landing.js lines 518-519. The meta-badge path uses `m.prompt_price !== undefined` which passes null, but the API never sends null.
- `.openrouter-custom-model-summary` uses `border-radius: 8px` and `.model-summary-chip` uses `border-radius: 4px` — hardcoded rather than `--radius-sm`/`--radius-md`. This pattern already appears in 14+ pre-existing locations throughout style.css, so it is an existing inconsistency rather than a new violation.
- `.model-summary-chip` uses `SFMono-Regular, Consolas, Monaco, 'Liberation Mono', monospace` — not from `--font-*` tokens. The identical stack was already present at style.css line 5281 (`.combobox-option-meta`), so the new usage is consistent with the established codebase pattern.

## Named Risk Checks

**1. Async gap in handleUpload**
`handleUpload` (landing.js lines 835-954) was not modified by any task. The sequence `POST /api/projects` → (backup sync) → `POST .../process` is identical to baseline. No new awaits inserted. Confirmed by grepping the diff for `handleUpload` and `/api/projects` — no changes.

**2. Listener duplication guard**
All new `addEventListener` calls are inside the `if (!_landingListenersAttached)` block starting at landing.js line 647. Verified: `persistModelSelector()` at line 686 is inside that block (provider-only checkbox listener). Persist calls at lines 457, 531, 554, 561 are inside setter functions; persist call at line 358 is inside the provider combobox `onSelect` (wired during `initLanding` setup, not a re-attached listener). The `_customRestore` block at line 764 runs once per `initLanding` invocation and calls `setOpenRouterModel` (not a listener). Compliant.

**3. T5 combobox teardown-race guard**
Two guards in the `.then()` at landing.js lines 471-472:
1. `if (currentOpenRouterMode !== 'custom') return;` — bails if user left custom mode while fetch was in flight.
2. `if (!mountEl || !document.body.contains(mountEl)) return;` — bails if mount is detached.
`.is-loading` is removed before the guard check so it is always cleaned up regardless of bail. Test coverage confirmed by `'teardown guard: switching to preset while models fetch is in flight aborts combobox creation'`.

**4. T6 custom-mode restore race guard**
Landing.js lines 769-773 mirror T5 exactly: `if (currentOpenRouterMode !== 'custom') return;` and mount check. `currentCustomOpenRouterModel` is set explicitly to `pendingCustomModel` (the raw ID) at line 779, not via `onSelect`, correctly decoupling display label from the submit value. Test coverage confirmed by `'teardown-race guard: switching away from custom before models load aborts restore'`.

**5. Price rendering can't produce $0.00**
`formatModelPrice(0)` → `'Gratis'` (early return, line 112). Backend sets `float(..., 0)` default so prices are always non-null floats. Summary-rendering `??` guards at lines 518-519 coerce null to 0 → `'Gratis'`. Meta badge uses `!== undefined` guard and omits empty strings via `.filter(Boolean)`. Confirmed.

**6. Preset constant drift**
Frontend: `xiaomi/mimo-v2.5-pro`, `xiaomi/mimo-v2.5`, `deepseek/deepseek-v4-pro` (landing.js lines 16-18). Backend: `OPENROUTER_EXPLAINER_MODELS` frozenset (main.py lines 163-165). No task changed either side. Identical.

**7. Theme discipline**
All new CSS uses only existing `:root` tokens. Single `--amber` accent. No new theme, no marketing copy, no new accent color. Spanish utility labels throughout. Minor border-radius/font observations noted above but pre-established in codebase.

## Required Changes
None.

## Evidence
- `git diff dcba671641c4f0677ce85da6b7a2bc6d9ef54a18 -- main.py frontend/index.html frontend/js/landing.js frontend/js/components/openrouter-combobox.js frontend/style.css` — all hunks reviewed.
- main.py lines 179-185 (ProcessProjectRequest), 161-165 (OPENROUTER_EXPLAINER_MODELS), 4100-4120 (_fetch_openrouter_models): read directly.
- landing.js lines 647-796 (listener guard + restore block), 462-554 (setOpenRouterModel with guards), 902-946 (handleUpload unchanged): read directly.
- openrouter-combobox.js lines 40-55: wrapper role removed, input retains sole `role="combobox"`.
- index.html lines 242-351: aria-live attributes, status slots, canonical markup.
- style.css: focus ring, motion guards, new component styles — all verified in diff.
- Test runs: 252/252 frontend (vitest), 29/29 backend (pytest) — both confirmed live.

## Limitations
- Visual/keyboard behavior not tested in a real browser; `:has()` focus ring and `:focus-visible` verified by reading CSS rules, not by manual keyboard traversal.
- Stale-cache OpenRouter responses written before T1 deployment may contain non-text models for up to one cache TTL after deploy. Not a code defect; noted in T1 review.
- Custom-mode restore display label (`setValue(displayName)`) sets the combobox input to the human name, but the underlying module variable `currentCustomOpenRouterModel` holds the raw ID used in the submit payload. This is correct but untested via a round-trip through `handleUpload` in the integration tests.
