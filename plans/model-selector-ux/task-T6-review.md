# Review: T6 — localStorage persistence

## Verdict
PASS

## Functional Verification
- `npx vitest run tests/frontend/` → 252/252 tests pass, 17 suites (confirmed live run)
- Targeted reads of `frontend/js/landing.js` lines 78-135 (`restoreModelSelector`), 762-795 (restore block in `initLanding`), 835-955 (`handleUpload`), 647-760 (`_landingListenersAttached` block)
- `git diff dcba671 -- frontend/js/landing.js tests/frontend/landing.test.js tests/frontend/landingFlow.test.js` reviewed in full

## Spec Compliance

### Met
- Single key `explainer.modelSelector.v1` via `SELECTOR_KEY` constant ✓
- `persistModelSelector()` wrapped in try/catch; write failures silently ignored ✓
- `restoreModelSelector()` outer and inner parse both in try/catch; corrupt/missing JSON returns null (no-op) ✓
- Non-object and array guards: `!saved || typeof saved !== 'object' || Array.isArray(saved)` ✓
- Every field validated before applying:
  - `explainerProvider` checked against `['gemini','openrouter','deepseek']`, else `'gemini'` ✓
  - `openrouterModel` validated via `isPresetOpenRouterModel`, else `OPENROUTER_MODEL_MIMO_PRO` ✓
  - `deepseekModel` validated via `isValidDeepSeekModel`, else `DEEPSEEK_MODEL_V4_PRO` ✓
  - `openrouterMode` checked against `['preset','custom']` ✓
  - `openrouterProviderOnly` coerced with `Boolean()` ✓
  - `openrouterProvider` checked for `typeof === 'string'`, else `''` ✓
- Key-availability fallback: `!state.hasOpenRouterKey → 'gemini'`; `!state.hasDeepSeekKey → 'gemini'` ✓
- Source-type fallback via `isExplainerProviderSupportedForSource` (both validators are module-level exports at lines 71-83, accessible from `restoreModelSelector`) ✓
- Restore block placed after `_landingListenersAttached` guard, before final `syncExplainerProviderUI()` (line 795) ✓
- Custom-mode restore: calls `setOpenRouterModel('__custom__')`, chains `.then()` off the returned promise, sets combobox value via `setValue(displayLabel)`, sets `currentCustomOpenRouterModel = pendingCustomModel`, calls `fetchEndpointsForModel`, restores provider combobox and provider-only checkbox ✓
- Teardown-race guard at BOTH levels: inside `setOpenRouterModel`'s inner `.then()` (`currentOpenRouterMode !== 'custom'` check) AND in the outer restore `.then()` ✓
- `persistModelSelector()` NOT called inside `handleUpload`'s post-submit reset (verified: the reset at lines 930-936 mutates vars but never calls `persistModelSelector`) ✓
- No `el.style.display`: all show/hide uses `show(el)` / `hide(el)` from dom.js ✓
- `state` treated as read-only: only `state.hasOpenRouterKey` / `state.hasDeepSeekKey` / `state.hasApiKey` read, never assigned ✓
- No new DOM event listeners outside `_landingListenersAttached` guard: `persistModelSelector()` added inside existing setter and handler bodies only; the `openRouterProviderOnlyCheckbox.addEventListener` at line 684 is inside the guard (guard opens at line 647) ✓
- No async gap introduced in `handleUpload` between `POST /api/projects` (line 902) and `POST /api/projects/{id}/process` (line 942): `handleUpload` unchanged ✓
- Submit payload shape unchanged ✓

### Extra scope in diff (not in T6 brief, not a violation)
- `formatModelPrice()` / `formatContextLength()` — utility exports, also tested
- `providerNeedsKey()` local function + `.needs-key` indicator on provider cards
- Custom model summary panel population in `onSelect`
- Meta badges (context + price) in combobox items
These are likely co-landed from T3/T4/T5. All pass tests and no constraint violations.

## Code Quality

- `restoreModelSelector` is clean and linear: parse → guard → validate each field → apply → return custom signal or null. No exception can escape.
- The custom-mode restore in `initLanding` correctly guards against both the null-promise path (`typeof _loadPromise.then === 'function'`) and the teardown race (`currentOpenRouterMode !== 'custom'` + DOM membership check).
- Minor: when key-availability fallback forces `provider = 'gemini'` but the saved data has `openrouterMode: 'custom'` and a valid `customOpenrouterModel`, `restoreModelSelector` still sets `currentOpenRouterMode = 'custom'` and returns a non-null signal. The `initLanding` restore block correctly neutralizes this with its own `currentExplainerProvider === 'openrouter'` guard, so the custom async path is skipped. `currentOpenRouterMode` is left as `'custom'` in memory but the UI is in Gemini mode; any subsequent provider interaction will overwrite it via `persistModelSelector`. This is a harmless orphaned state, not a defect.
- `currentOpenRouterProvider` is correctly tracked on combobox `onSelect` for persistence. Submit payload still reads from `_openrouterProviderCombobox.getValue()` (unchanged), and `setValue(pendingProvider)` on restore ensures the combobox input reflects the saved value so `getValue()` returns it correctly.

## Named Risk Checks

1. **Restore never throws / all fields validated before apply**: Verified by code read and 13 unit tests (corrupt JSON, missing key, invalid provider, key-unavailable, model validation, round-trips, boolean coercion). No path allows an unguarded field access.
2. **Key-availability fallback**: Verified — `restoreModelSelector` checks `state.hasOpenRouterKey` / `state.hasDeepSeekKey` before applying; unit tests for each; `landingFlow` integration tests confirm gemini fallback drives the UI radio correctly.
3. **Custom-mode restore async ordering / teardown-race guard**: Double-guarded (inner `setOpenRouterModel` `.then()` + outer restore `.then()`). Integration test `'teardown-race guard: switching away from custom before models load aborts restore'` exercises the timing path with a deferred promise. ✓
4. **No persist inside handleUpload reset**: `handleUpload` (lines 835-955) reads and mutates `currentOpenRouterMode`, `currentCustomOpenRouterModel`, `currentOpenRouterProviderOnly` during post-submit reset but never calls `persistModelSelector`. Verified by grep (all 8 call sites) and code read.
5. **Listener guard**: Verified `openRouterProviderOnlyCheckbox.addEventListener` is inside guard (line 684 vs guard at line 647). `onSelect` callbacks are not new DOM listeners.

## Required Changes
None.

## Evidence
- `npx vitest run tests/frontend/` output: 17 suites, 252/252 passed
- `git diff dcba671 -- frontend/js/landing.js` (47.8KB full diff) reviewed
- `landing.js` lines 71-83 (module-level validators), 139-135 (`persistModelSelector`/`restoreModelSelector`), 684-687 (checkbox listener), 762-795 (restore block), 835-955 (`handleUpload`)
- `isPresetOpenRouterModel` confirmed at line 81, `isExplainerProviderSupportedForSource` at line 71 — both module-level, accessible from exported `restoreModelSelector`

## Limitations
- `setValue` behavior on the combobox (does not call `onSelect`, only updates `input.value`) was verified by the implementer via extra read of `openrouter-combobox.js`. This reviewer did not re-read that file; the test `'restores custom openrouter mode — builds combobox and sets the saved model'` validates the observable effect (combobox input contains 'Qwen' after restore), which is sufficient evidence.
- Live browser integration (actual localStorage read/write across page reload) not tested — jsdom localStorage coverage is deemed sufficient for the validation/fallback scope.
