# Plan — Custom OpenRouter model + routing provider for the explainer

## Context / objective

Today the OpenRouter explainer can only run on **three hardcoded preset models** (`xiaomi/mimo-v2.5-pro`, `xiaomi/mimo-v2.5`, `deepseek/deepseek-v4-pro`), surfaced as three radio cards. We want to **keep those presets working exactly as today** but additionally let a user:

1. Pick **any** OpenRouter model from a live, searchable list (400+ models fetched from OpenRouter, shown with id + name + pricing + context length).
2. Optionally pin an **OpenRouter routing provider** for that custom model, with a toggle to disallow fallbacks ("use only this provider").

Scope is the **main explainer agent only**. Auxiliary agents (segmentador, page_classifier, recorrido, resources, formatter, completeness_validator) keep `OPENROUTER_MODEL_AUXILIARY` and are untouched.

The chosen model id continues to flow into the existing `openrouter_model` request field; routing provider flows through a **new** request field down to the already-provider-aware HTTP layer.

---

## Shared context map

**CodeGraph preflight:** `.codegraph/` is **LIVE** (per orchestrator). Prefer `codegraph_node`/`codegraph_context` for signatures; line numbers below are read-hints — **verify on open**.

### Backend — `main.py`
- `ExplainerProvider = Literal["gemini","openrouter","deepseek"]` — ~150. App-level provider; **distinct** from the OpenRouter *routing* provider.
- `OpenRouterExplainerModel = Literal[...3 ids...]` — ~151. Request allowlist type.
- `OPENROUTER_EXPLAINER_MODELS: frozenset` — ~157. Currently the **runtime rejection gate**.
- `ProcessProjectRequest(BaseModel)` — ~175. Fields: `explainer_provider`, `openrouter_model`, `target_language`, `deepseek_model`.
- `_resolve_explainer_model(explainer_provider, openrouter_model, deepseek_model)` — ~182. Validates model against the frozenset; **must be relaxed** to accept shape-valid custom ids.
- `_call_agent_with_optional_validation_context(fn, *args, validation_context, target_language)` — ~1168. **Key**: forwards only `validation_context` + `target_language` as kwargs (via `inspect.signature`); positional args pass through untouched. It will **not** auto-forward a new `provider_routing` kwarg — bind it with `functools.partial` instead.
- `_process_project(...)` async worker — ~1907. Re-resolves `explainer_model` (~1939); selects `text_provider_explainer_fn` / `text_provider_subpart_fn` (~3079-3084); threads `explainer_model` positionally into agent calls (~3126, 3140, 3177, 3195).
- `api_process_project` route `POST /api/projects/{project_id}/process` — ~3764. Extracts fields, validates via `_resolve_explainer_model`, dispatches `background_tasks.add_task(_process_project, ...)` (~3884).
- Settings endpoint pattern: `@app.get("/api/settings/api-key/status")` with `Depends(get_current_user_id)` — ~463.
- Key helpers (imported ~41-49): `get_user_api_key(user_id, provider=PROVIDER_OPENROUTER)`, `has_user_api_key`. OpenRouter key is BYOK from Supabase.

### Backend — agents `backend/agents/explainer_openrouter.py`
- `_OPENROUTER_PROVIDER_OVERRIDES = {"deepseek/deepseek-v4-pro": {"order": ["deepseek"], "allow_fallbacks": False}}` — ~50. Per-model default routing.
- `_call_openrouter_json_with_pdf_fallback(*, source_path, identificacion, mime_type, model, system_prompt, response_format, api_key, pdf_cache_entry, page_numbers)` — ~531. Computes `provider = _OPENROUTER_PROVIDER_OVERRIDES.get(model)` (~543) and passes `provider=provider` into `call_openrouter_chat` at the 3 call sites (~562, 585, 606).
- `run_explainer_or(source_path, identificacion, model, mime_type, api_key, pdf_cache_entry, page_numbers, target_language)` — ~644. Wraps `_call_openrouter_json_with_pdf_fallback`.
- `run_subpart_explainer_or(...)` — ~710. Same shape, subpart variant.
- `_run_explainer_or_for_retry(...)` / `_run_subpart_explainer_or_for_retry(...)` — retry closures (~840-890) that also call `_call_openrouter_json_with_pdf_fallback`.
- `run_explainer_or_validated(...)` — ~899 — and `run_subpart_explainer_or_validated(...)` — ~944 — public entry points (imported into `main.py` aliased as `run_explainer_or` / `run_subpart_explainer_or` at main.py ~82-83). They wrap the non-validated calls via `run_with_openrouter_explainer_validation`.

### Backend — HTTP layer `backend/openrouter_client.py` (NO change needed)
- `call_openrouter_chat(... provider: dict | None ...)` — ~1560 — already accepts `provider` and injects it into the request payload.
- `OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"` — ~27. Models list is the sibling `…/api/v1/models`. `requests` lib is the project's HTTP client (only `requests>=2.31.0` is in `requirements.txt` — **no httpx, no cachetools**).

### Frontend
- `frontend/index.html`: OpenRouter model sub-panel `#openrouter-model-panel` (~261-286) with three preset `.provider-card` radios under `#openrouter-model-group`. Language `<select class="form-input">` (~226) is the styling reference. Provider radios under `#explainer-provider-group` (~238).
- `frontend/js/landing.js`: module-local `currentExplainerProvider` (~13), `currentOpenRouterModel` (~22). Constants `OPENROUTER_MODEL_*` (~15-17). `isValidOpenRouterModel` (~66), `openRouterModelLabel` (~80), `setOpenRouterModel` (~261 — bails on invalid). `syncExplainerProviderUI()` (~218-254) — single DOM-sync function. `initLanding()` (~182-413), listeners in idempotent `if(!_landingListenersAttached)` block (~304-410). `handleUpload()` (~452-546) builds `processPayload` (~525-531) and POSTs to `/api/projects/{id}/process` (~533).
- `frontend/js/api.js`: `api(path, options)` — auth-aware fetch wrapper, returns parsed JSON, throws `Error(detail)` on failure.
- `frontend/style.css` "Scholarly Forge": `:root` tokens (~7-49) — `--bg-elevated #1f2937`, `--amber #f59e0b`, `--amber-dim`, `--border #2d3748`, `--text-primary #f0ece3`, `--font-ui Syne`, `--font-body Crimson Pro`, `--radius-md 10px`. Reusable: `.form-input` (~624, amber focus ring), `.form-label` (~607), `.form-group` (~601), `.provider-card` (~657, `.selected`/`.disabled`), `.provider-grid` (~651), `.openrouter-model-panel` (~716), `.input-hint`, `.btn-primary` (~203). **No combobox exists** in the design system — build one.

### OpenRouter API facts (verified via Context7 docs)
- **Provider routing** lives in the request body `provider` object:
  - Prefer a provider, allow fallbacks → `{"order": ["<slug>"]}`.
  - Pin a provider, no fallbacks → `{"order": ["<slug>"], "allow_fallbacks": false}`. This is the documented pattern that *"prevents OpenRouter from trying any providers not explicitly listed in the order array"* — it matches the existing `_OPENROUTER_PROVIDER_OVERRIDES` style, so we use **`order` + `allow_fallbacks:false`** (not `only`) for consistency.
  - No provider → omit `provider` entirely (default load-balancing).
- **Models list:** `GET https://openrouter.ai/api/v1/models` is **public (no auth)**. Response `data[]` items carry `id`, `name`, `context_length`, `pricing.{prompt,completion}` (USD **per token**, as strings).
- **Per-model endpoints:** `GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints` returns the model's available providers (under `data.endpoints[]`). The exact provider-slug field must be confirmed against the live payload during implementation; this powers the *enhanced* provider picker, with free-text slug as the guaranteed floor.

---

## Decisions already made (do not re-litigate)

1. **Request contract:** add two discrete fields to `ProcessProjectRequest` rather than a raw dict — cleaner, self-validating, mirrors existing discrete fields:
   - `openrouter_provider: str | None = None` (routing provider slug, e.g. `"deepseek"`)
   - `openrouter_provider_only: bool = False` (when a provider is set and this is true → no fallbacks)
   - `openrouter_model` type widens from the `Literal` to `str | None` (presets are still valid strings).
2. **Model gate:** `_resolve_explainer_model` stops requiring frozenset membership; instead validates **shape** for OpenRouter ids: non-empty, regex `^[\w.-]+/[\w.:-]+$`, length ≤ 128. Presets pass trivially. The frozenset stays as documentation of the presets (and may still gate nothing) — keep it for reference.
3. **Provider routing dict** is built **in `main.py`** (single source of truth) and threaded as one `dict | None` down to the agents:
   - provider set, `only=false` → `{"order": [slug]}`
   - provider set, `only=true` → `{"order": [slug], "allow_fallbacks": False}`
   - no provider → `None`
4. **Override precedence:** in `_call_openrouter_json_with_pdf_fallback`, an explicit `provider_routing` (when not `None`) **supersedes** `_OPENROUTER_PROVIDER_OVERRIDES`; otherwise the override map still applies. This preserves the existing deepseek-v4-pro preset behavior.
5. **Threading mechanism:** bind `provider_routing` into the OpenRouter explainer fns with `functools.partial` in the worker (since `_call_agent_with_optional_validation_context` only auto-forwards `validation_context`/`target_language`). DeepSeek fns are bound as today (no provider_routing).
6. **Models proxy:** new authenticated endpoints in `main.py` (gated by `Depends(get_current_user_id)`) that call OpenRouter **unauthenticated** (public endpoint), with a **hand-rolled module-level TTL cache** (~1h) protected by a `threading.Lock`, served via `asyncio.to_thread` around `requests`. On upstream failure: serve last-good cache if present (`stale: true`), else `503`/empty list with a clear message. **No new dependency.**
7. **Frontend custom affordance:** add a **4th `.provider-card` radio** ("Personalizado") as a sibling of the three presets inside `#openrouter-model-group`. The three presets stay byte-for-byte as today. Selecting "Personalizado" reveals a custom sub-panel (combobox + provider control + only-this toggle). Preset selection sends no provider fields; custom selection sends `openrouter_model` (combobox id) + the two provider fields.
8. **Combobox:** a bespoke, accessible WAI-ARIA combobox component in **vanilla JS** (new file `frontend/js/components/openrouter-combobox.js`), styled to Scholarly Forge (amber focus ring, `--bg-elevated`, Syne label). Reused for both the model picker and (when populated) the provider picker.

### Frontend design direction (combobox + custom panel)
Scholarly Forge is restrained dark-academic; the combobox must read as a natural sibling of `.form-input` / `.provider-card`, not a generic SaaS dropdown.
- **Trigger**: a `.form-input`-height field with an amber down-chevron; on focus the same amber ring (`box-shadow` with `--amber-dim`) used by `.form-input`. Placeholder in muted text: "Busca un modelo (id o nombre)…".
- **Listbox**: `--bg-elevated` panel, `1px solid --border`, `--radius-md`, subtle shadow; max-height ~320px, scrollable. Each option: model **name** in Syne (text-primary), **id** in mono/muted below, and a right-aligned meta line — `$X.XX / $Y.YY por Mtok · 128K ctx`. Selected/active option gets a left amber rule (3px) + faint `--amber-dim` wash. No card chrome — keep it a quiet list so the signature amber accent carries the hierarchy.
- **Pricing**: convert OpenRouter per-token USD → per-Mtok (`×1e6`), 2-3 sig figs; render "Gratis" when 0.
- **Motion**: open/close is an 80-120ms opacity+translateY; respect `prefers-reduced-motion` (no transform). One accent, minimal motion — per "remove one accessory".
- **Provider control**: when a model is chosen, attempt to populate a second combobox (or a `.form-input` `<select>`) from the endpoints API; if empty/failed, render a free-text `.form-input` ("Escribe un slug de proveedor, p. ej. deepseek"). Below it the only-this toggle: a labelled checkbox "Usar solo este proveedor (sin alternativas)".
- Copy in Spanish, sentence case, active voice (matches existing UI).

---

## Task breakdown

### T1 — Agent layer: thread `provider_routing` through the OpenRouter explainer
**File (touch):** `backend/agents/explainer_openrouter.py` only.
**Do-not-touch:** `backend/openrouter_client.py`, `main.py`, any DeepSeek/Gemini agent.

**Goal:** Add an optional `provider_routing: dict | None = None` parameter that flows from the public validated entry points down to the HTTP call, where it supersedes `_OPENROUTER_PROVIDER_OVERRIDES` when provided. Purely additive — default `None` reproduces today's behavior exactly.

**Changes:**
- `_call_openrouter_json_with_pdf_fallback(...)` (~531): add keyword-only `provider_routing: dict | None = None`. Replace `provider = _OPENROUTER_PROVIDER_OVERRIDES.get(model)` (~543) with `provider = provider_routing if provider_routing is not None else _OPENROUTER_PROVIDER_OVERRIDES.get(model)`. (The 3 `call_openrouter_chat(..., provider=provider)` sites then need no change.)
- `run_explainer_or(...)` (~644) and `run_subpart_explainer_or(...)` (~710): add `provider_routing: dict | None = None`; pass it into the `_call_openrouter_json_with_pdf_fallback(...)` lambda.
- Retry closures `_run_explainer_or_for_retry` / `_run_subpart_explainer_or_for_retry` (~840-890): accept and forward `provider_routing` into their `_call_openrouter_json_with_pdf_fallback` call.
- `run_explainer_or_validated(...)` (~899) and `run_subpart_explainer_or_validated(...)` (~944): add `provider_routing: dict | None = None`; forward into both the `initial_call` and `retry_call` lambdas (which call `run_explainer_or` / `_run_explainer_or_for_retry`).

**Acceptance criteria:**
- All existing calls with no `provider_routing` behave identically (deepseek-v4-pro still gets `{"order":["deepseek"],"allow_fallbacks":False}` via the override map).
- A unit test passing `provider_routing={"order":["novita"]}` for a model **with** an override (`deepseek/deepseek-v4-pro`) confirms the explicit routing wins (the payload's `provider` equals the explicit dict). Easiest seam: monkeypatch/spy `call_openrouter_chat` and assert the `provider=` kwarg.
- Passing `provider_routing=None` for that same model still yields the override dict.

**Integration contract:** `provider_routing` is the exact OpenRouter `provider` object (`{"order":[...], "allow_fallbacks"?:bool}`) — built upstream by T3. This task does not build or validate the dict; it only threads and prefers it.

---

### T2 — Backend: live models proxy endpoints with TTL cache + graceful degradation
**File (touch):** `main.py` only (new endpoints + cache helpers, additive).
**Do-not-touch:** existing routes, `ProcessProjectRequest`, `_resolve_explainer_model`, `_process_project`. (These are T3's scope — keep edits in a separate region of `main.py` to minimize overlap; T2 runs before T3.)

**Goal:** Two authenticated GET endpoints that proxy + cache OpenRouter's public model metadata so the frontend combobox can populate quickly and resiliently.

**Endpoints:**
1. `GET /api/openrouter/models` → normalized list:
   ```json
   { "models": [ { "id": "...", "name": "...", "context_length": 128000,
                   "prompt_price": 0.0000004, "completion_price": 0.0000012 } ],
     "stale": false, "fetched_at": "<iso8601>" }
   ```
   (Keep prices as raw USD-per-token numbers; the frontend converts to per-Mtok. Drop entries without an `id`.)
2. `GET /api/openrouter/models/endpoints?model=<author/slug>` → `{ "providers": ["deepseek", ...], "stale": false }`.
   - Use a **query param** for the model id (it contains a `/` and possibly `:`), validated by the same shape regex as T3 (reuse/duplicate the constant). Call `…/api/v1/models/{model}/endpoints`. Map the provider list from `data.endpoints[]` — **confirm the exact slug field against the live payload**; return `[]` on any uncertainty (frontend free-text floor covers it).

**Implementation notes:**
- Add `OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"` (sibling of `OPENROUTER_BASE_URL`).
- Hand-rolled TTL cache: module-level `dict` keyed by `("models",)` / `("endpoints", model)` storing `(value, fetched_at_monotonic)`, guarded by a `threading.Lock`; TTL ~3600s. Wrap the blocking `requests.get(timeout=…)` in `await asyncio.to_thread(...)`.
- Both endpoints gated by `Depends(get_current_user_id)` (consistency / not an open proxy); call OpenRouter **without** auth (public). Set a `HTTP-Referer`/`X-Title` header to be polite (optional).
- **Degradation:** on request exception or non-200, if a cached value exists return it with `stale: true`; else raise `HTTPException(503, "No se pudo obtener la lista de modelos de OpenRouter. Inténtalo de nuevo en un momento.")`.

**Acceptance criteria:**
- First call fetches + caches; a second call within TTL does **not** hit the network (assert via patched `requests.get` call count).
- Simulated upstream failure with a warm cache returns the cached list and `stale: true`; with a cold cache returns `503` and a Spanish message.
- Response shape matches the schema above; an item missing `id` is dropped.
- Endpoints require auth (401 without a valid token).

**Integration contract:** frontend (T5) consumes `models[]` (id/name/context_length/prompt_price/completion_price) and `providers[]`. Field names here are the contract.

---

### T3 — Backend: request contract, model-gate relaxation, provider-routing threading
**File (touch):** `main.py` only.
**Do-not-touch:** `backend/agents/explainer_openrouter.py` (T1 owns it; T3 only *calls* its new param), the T2 endpoint/cache region.

**Goal:** Accept the custom model + provider fields, validate them, build the routing dict, and thread it to the OpenRouter explainer functions in the worker.

**Changes:**
- `ProcessProjectRequest` (~175): widen `openrouter_model` to `str | None = None`; add `openrouter_provider: str | None = None` and `openrouter_provider_only: bool = False`.
- `_resolve_explainer_model` (~182): for the OpenRouter branch, replace the frozenset membership check with shape validation — strip, require non-empty, `re.fullmatch(r"[\w.-]+/[\w.:-]+", model)`, `len(model) <= 128`; raise `ValueError("Modelo OpenRouter inválido: …")` otherwise. Presets pass unchanged. (DeepSeek/Gemini branches untouched.) Define the regex as a module constant reused by T2's endpoints param validation.
- Add helper `_build_openrouter_provider_routing(provider: str | None, only: bool) -> dict | None`: lowercase+strip slug; if empty → `None`; validate slug shape `re.fullmatch(r"[\w.-]+", slug)` and length cap (else `None` or raise — prefer ignore-empty, raise-on-malformed via `ValueError`); return `{"order":[slug]}`, adding `"allow_fallbacks": False` when `only`.
- `api_process_project` (~3764): extract `openrouter_provider` / `openrouter_provider_only` from payload; build the routing dict (wrap `ValueError` → `HTTPException(400)` like the existing model-resolve block); pass `openrouter_provider_routing` into `background_tasks.add_task(_process_project, …)` (~3884). Add it to the log `extra` for observability.
- `_process_project` (~1907): add param `openrouter_provider_routing: dict | None = None`. At the OpenRouter/DeepSeek fn-selection (~3079-3084), when `use_openrouter_explainer`, bind the routing via `functools.partial`:
  ```python
  text_provider_explainer_fn = partial(run_explainer_or, provider_routing=openrouter_provider_routing)
  text_provider_subpart_fn = partial(run_subpart_explainer_or, provider_routing=openrouter_provider_routing)
  ```
  DeepSeek branch unchanged. (Positional `explainer_model`/api-key args at the call sites stay as-is; `_call_agent_with_optional_validation_context` still forwards only `validation_context`/`target_language`, and `inspect.signature` works on partials so those kwargs are still passed.)
- Import `functools.partial` (and `re` if not already imported at module scope).

**Acceptance criteria:**
- The 3 presets still resolve and run unchanged; a request with no provider fields produces `openrouter_provider_routing=None` and identical behavior to today.
- A custom valid id (e.g. `openai/gpt-5.4-nano`) resolves and runs.
- A malformed id (e.g. `"; rm -rf"`, or no slash) → `400`.
- `openrouter_provider="novita"`, `openrouter_provider_only=false` → routing `{"order":["novita"]}` reaches `call_openrouter_chat`'s `provider=` (end-to-end with T1; verify via patched HTTP layer).
- Same with `only=true` → `{"order":["novita"],"allow_fallbacks":False}`.
- Provider fields are ignored for gemini/deepseek providers (no crash).

**Integration contract:** depends on **T1** (`run_explainer_or` / `run_subpart_explainer_or` must accept `provider_routing`). Consumes T5's payload field names (`openrouter_provider`, `openrouter_provider_only`, `openrouter_model`).

---

### T4 — Frontend: accessible OpenRouter combobox component (new module + styles)
**Files (touch):** new `frontend/js/components/openrouter-combobox.js`; `frontend/style.css` (append a `Combobox` section).
**Do-not-touch:** `landing.js`, `index.html` (T5 wires it). Existing CSS rules.

**Goal:** A self-contained, reusable, WAI-ARIA combobox (editable text filter + listbox) with no framework, matching Scholarly Forge.

**API (suggested):**
```js
createCombobox(mountEl, {
  placeholder, items,            // items: [{ value, label, sublabel, meta }]
  onSelect(value, item),         // fired on commit
  emptyText, getItemLabel        // optional
}) -> { setItems(items), getValue(), setValue(value), focus(), destroy() }
```
**Behavior / a11y:**
- Markup: `role="combobox"` text input with `aria-expanded`, `aria-controls`, `aria-autocomplete="list"`; `role="listbox"` with `role="option"` children, `aria-selected`, and `aria-activedescendant` on the input.
- Keyboard: ArrowDown/Up move active option (open if closed), Enter commits active, Esc closes (keeps value), Home/End jump, typing filters (case-insensitive over label+value), Tab closes without changing selection. Mouse: click opens/commits; outside-click closes.
- Filtering is client-side over the provided items; render is virtualization-free but capped (e.g. show first ~100 matches with a "refina la búsqueda" footer when more) to stay snappy with 400+ models.
- Respect `prefers-reduced-motion`. Visible focus ring. No layout shift when opening (listbox is absolutely positioned).

**Styling (`style.css`):** trigger mirrors `.form-input` height/border/focus-ring; listbox uses `--bg-elevated`, `--border`, `--radius-md`, shadow; option name in `--font-ui`, id muted/mono, meta right-aligned; active/selected option gets left amber rule + `--amber-dim` wash. Use existing tokens only.

**Acceptance criteria:**
- Keyboard-only: open, filter, arrow to an option, Enter → `onSelect` fires with the right value; Esc closes without selecting.
- Screen-reader semantics present (roles + `aria-activedescendant` updates) — verifiable in the Playwright accessibility snapshot.
- With 400+ items, filtering stays responsive and the list is capped with the refine hint.
- No console errors; `destroy()` removes listeners/nodes.

**Integration contract:** consumed by T5. Pure component — no knowledge of OpenRouter or app state.

---

### T5 — Frontend: custom-model + provider UI wiring
**Files (touch):** `frontend/index.html` (custom sub-panel markup), `frontend/js/landing.js` (state, fetch, sync, listeners, payload), `frontend/style.css` (custom-panel layout only).
**Do-not-touch:** the three existing preset radio cards (keep verbatim), the combobox component internals (T4), `api.js`.

**Goal:** Add the "Personalizado" affordance that reveals the model combobox + provider control + only-this toggle, fetches models lazily, and sends the right payload — while presets keep working exactly as today.

**Changes:**
- `index.html`: inside `#openrouter-model-group` (~263), add a 4th `.provider-card` radio `#openrouter-model-card-custom` (value sentinel e.g. `__custom__`, `name="openrouter-model"`). After the group, add a hidden `#openrouter-custom-panel` containing: a mount node for the model combobox (`#openrouter-custom-model-combobox`) with a `.form-label`; a mount/area for the provider control (`#openrouter-provider-control`) with label "Proveedor preferido (opcional)"; the only-this checkbox `#openrouter-provider-only` with label; and an `.input-hint`/`.input-error` for custom-model state.
- `landing.js`:
  - New module-local state: `currentOpenRouterMode` (`'preset' | 'custom'`), `currentOpenRouterCustomModel` (string|null), `currentOpenRouterProvider` (string|null), `currentOpenRouterProviderOnly` (bool), plus a models cache `let _orModels = null`.
  - `setOpenRouterModel` (~261) / `isValidOpenRouterModel` (~66): preset path stays gated as today; the custom selection bypasses the preset validity gate (mode-aware).
  - `syncExplainerProviderUI()` (~218): toggle `#openrouter-custom-panel` visibility on `currentOpenRouterMode === 'custom'` (and only when provider===openrouter); reflect the 4th radio's `.selected`. Presets and custom are mutually exclusive radios — selecting custom must clear preset `.selected`, and vice-versa.
  - On entering custom mode (first time): lazily `await api('/api/openrouter/models')`, cache, `combobox.setItems(...)` mapping each model to `{ value:id, label:name, sublabel:id, meta: "<$prompt>/<$completion> por Mtok · <ctx> ctx" }` (convert per-token→per-Mtok). On fetch error: toast + show inline error + still allow a raw free-text id fallback (degraded). Show a loading state while fetching.
  - On model commit: set `currentOpenRouterCustomModel`; attempt `api('/api/openrouter/models/endpoints?model=' + encodeURIComponent(id))` to populate the provider control (combobox/select of `providers[]`); on empty/failure, render the free-text provider input. Wire provider change → `currentOpenRouterProvider`; only-this checkbox → `currentOpenRouterProviderOnly`.
  - Listeners added inside the idempotent `if(!_landingListenersAttached)` block (~304) — respect the existing idempotency guard (recent commit `41fd72b`). Instantiate the combobox **once** (guarded), not per render.
  - `handleUpload()` payload (~525-531): when `currentExplainerProvider==='openrouter'`:
    - preset mode → `processPayload.openrouter_model = currentOpenRouterModel` (today's behavior).
    - custom mode → require a non-empty custom id (block submit + inline error if missing); set `processPayload.openrouter_model = currentOpenRouterCustomModel`; if `currentOpenRouterProvider` set, add `processPayload.openrouter_provider = currentOpenRouterProvider` and `processPayload.openrouter_provider_only = currentOpenRouterProviderOnly`.
  - On form reset after successful upload, reset custom state to defaults (mode back to preset is acceptable; or persist — choose preset reset for predictability).
- `style.css`: layout for `#openrouter-custom-panel` (spacing, the toggle row) using existing tokens; reuse `.form-group`/`.form-label`/`.input-hint`. No new color tokens.

**Acceptance criteria:**
- Selecting a preset behaves byte-for-byte as today (custom panel hidden, payload has only `openrouter_model` = preset id, no provider fields).
- Selecting "Personalizado" reveals the panel, lazily loads models, and the combobox is searchable by id and name with pricing/context shown.
- Choosing a custom model + provider + only-this produces a payload `{ explainer_provider:"openrouter", openrouter_model:"<id>", openrouter_provider:"<slug>", openrouter_provider_only:true, target_language }`.
- Custom mode with no model chosen blocks submit with a Spanish inline error.
- Models-endpoint failure degrades to a usable free-text id input (no dead end).
- Keyboard/AT accessible (inherits T4); reduced-motion respected.

**Integration contract:** payload field names must equal T3's (`openrouter_model`, `openrouter_provider`, `openrouter_provider_only`); consumes T2's response field names; mounts T4's combobox.

---

## Execution order (waves)

```
Wave 1 (parallel — disjoint files)
 ├─ T1  backend/agents/explainer_openrouter.py      (agent threading)
 ├─ T2  main.py  (models proxy endpoints + cache)   ── must land before T3 (same file)
 └─ T4  frontend/js/components/openrouter-combobox.js + style.css (combobox)

Wave 2 (parallel — disjoint files; each depends on Wave 1)
 ├─ T3  main.py  (contract + worker threading)   depends: T1 (param), T2 (file ordering)
 └─ T5  index.html + landing.js + style.css      depends: T4 (combobox), contracts of T2 & T3

Wave 3
 └─ End-to-end verification (below)
```

**Dependency rationale**
- **T1 ∥ T2 ∥ T4**: three different files (`explainer_openrouter.py`, `main.py`, `combobox.js`+`style.css`) → safe in parallel. (T4's CSS is appended to `style.css`; T5 also edits `style.css` but runs in Wave 2, so no concurrent writer.)
- **T2 before T3**: both edit `main.py` — never run two implementers on the same file concurrently. T2 is additive (new endpoints) and self-contained, so it goes first; T3 then edits the request/worker regions.
- **T3 needs T1**: the worker's `partial(run_explainer_or, provider_routing=…)` requires T1's new parameter.
- **T3 ∥ T5** in Wave 2: backend `main.py` vs frontend files → disjoint. Both code to the contracts fixed in this plan, so they integrate at verification.
- **T5 needs T4** (combobox import) and the T2/T3 contracts (fixed here in writing).

---

## Verification

### Per-task (unit / component)
- **T1:** pytest spying `call_openrouter_chat`: (a) `provider_routing=None` + `deepseek/deepseek-v4-pro` → `provider == {"order":["deepseek"],"allow_fallbacks":False}`; (b) explicit `provider_routing={"order":["novita"]}` → that exact dict wins over the override; (c) a non-override model with `provider_routing=None` → `provider is None`.
- **T2:** pytest with `requests.get` patched: cache hit avoids 2nd network call within TTL; warm-cache + upstream error → `stale:true`; cold-cache + error → `503` (Spanish); normalization drops id-less items; `401` without auth.
- **T3:** pytest/TestClient: presets unchanged; valid custom id accepted; malformed id → `400`; routing dict shapes for `only` true/false; provider fields ignored for gemini/deepseek. End-to-end (with T1) assert the built dict reaches the HTTP layer.
- **T4:** Playwright keyboard-only drive + accessibility snapshot (roles, `aria-activedescendant`); 400+ items filter responsively with the refine cap; `destroy()` clean.

### End-to-end (Wave 3 — Playwright against a running app)
1. **Presets unchanged (regression):** OpenRouter → each of the 3 preset cards → upload → inspect the outgoing `/process` request body: `openrouter_model` = preset id, **no** `openrouter_provider*` fields. Processing starts.
2. **Custom model reaches payload:** OpenRouter → "Personalizado" → combobox loads (network shows `GET /api/openrouter/models`), search "gpt", pick one → submit → request body has `openrouter_model` = chosen id, no provider fields.
3. **Custom model + provider + only-this:** pick a model, choose a provider (from endpoints list if present, else free-text), tick "usar solo este proveedor" → submit → body has `openrouter_provider` + `openrouter_provider_only:true`. (Optionally trace server logs / patched HTTP to confirm the OpenRouter `provider` object = `{"order":[slug],"allow_fallbacks":false}`.)
4. **Model list caches & degrades:** second open of the combobox issues no new upstream fetch within TTL; with OpenRouter forced to fail and a warm cache, the list still renders (`stale:true`); with a cold cache, the UI shows the error + free-text fallback (no dead end).
5. **Accessibility/keyboard:** the combobox is fully operable by keyboard, exposes correct ARIA roles/states, and respects reduced motion.
6. **Auxiliary scope intact:** confirm (logs/config) that segmentador/classifier/recorrido/resources/validator still use `OPENROUTER_MODEL_AUXILIARY` — only the explainer model/provider changed.

**Quick manual smoke:** `python main.py` → open the landing form → exercise presets and the custom path; watch the Network tab for `/api/openrouter/models`, `/api/openrouter/models/endpoints`, and `/api/projects/{id}/process` payloads.
