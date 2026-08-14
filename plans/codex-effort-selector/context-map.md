# Context Map: Selector de thinking/effort para el proveedor Codex (Luna)

## Objective

Permitir al planner localizar, sin rediscovery, todos los puntos que toca añadir un selector
global de nivel de razonamiento (effort) para `gpt-5.6-luna` en el proveedor Codex: allowlist y
default, cliente y wire-format de `turn/start`, variantes de agentes codex, wiring del pipeline,
persistencia `explainer_config`, endpoints on-demand (review/reformat), fixture fake del
app-server, y la card del selector en el frontend. Este mapa es continuación de
`plans/chatgpt-codex-auth/context-map.md` (bundle previo, commit `87b6a29`, feature ya
implementada y commiteada).

## Codegraph Status

**Absent** (heredado del bundle previo). Se usó `read`/`grep` como fallback. Los números de
línea son read-hints verificados en esta sesión contra el working tree en `87b6a29`.

## Relevant Areas

| Area | File | Symbol(s) | Read-hint | Why it matters |
|---|---|---|---|---|
| Receta effort | `plans/codex-effort-selector/integration-effort.md` | niveles exactos Luna `low/medium/high/xhigh/max`, default `medium`; `turn/start.effort`; `thread/start` SIN effort top-level; protocolo abierto (allowlist client-side obligatoria) | 1-83 | Contrato verificado que manda sobre niveles, wire y validación |
| Constantes model | `backend/codex_model_routing.py` | `CODEX_MODEL`, `CODEX_MODEL_AUXILIARY`, `CODEX_EXPLAINER_MODELS` | leer al implementar (corto) | Hogar natural de `CODEX_EFFORT_LEVELS`, `CODEX_DEFAULT_EFFORT` y `normalize_codex_effort` |
| Cliente codex | `backend/codex_client.py` | `call_codex_chat` (539, keyword-only), `_turn_params` (311), `_thread_start_params` (301), `CodexUsage` (139) | 301-321, 539-640 | `effort` se añade a `_turn_params`; `thread/start` NO cambia (el cliente crea un thread por llamada) |
| Variantes explainer | `backend/agents/explainer_codex.py` | `run_explainer_codex` (138), `run_subpart_explainer_codex` (199), `_call_codex_json_with_pdf_fallback` (104), `_CodexExplainerConversation` (251), `check_explainer_validation_codex` (365), `run_with_codex_explainer_validation` (432), `run_explainer_codex_validated` (519), `run_subpart_explainer_codex_validated` (563) | 104-135, 251-330, 365-460, 519-600 | 4 puntos `call_codex_chat` + 2 helpers internos que deben forwardear `effort` |
| Variante segmentador | `backend/agents/segmentador.py` | `run_segmentador_codex` (1404, con `*` antes de `conversation`/`correction`) | 1404-1460 | `effort` se añade tras los kw-only existentes |
| Variante classifier | `backend/agents/page_classifier.py` | `run_page_classifier_codex` (479) | 479-505 | firma `(api_key, source_text, total_pages, model)` |
| Variantes familia | `backend/agents/recorrido.py` (`run_recorrido_codex` 624), `backend/agents/resources.py` (`run_resources_codex` 784), `backend/agents/review.py` (`run_review_codex` 562), `backend/agents/formatter.py` (`_format_text_codex` 590, `format_explainer_content_codex` 787) | firmas `(user_id, ..., model=CODEX_MODEL, target_language=...)` | recorrido 624-648, resources 784-811, review 562-588, formatter 590-620, 787-812 | añadir `effort` como keyword final; formatter necesita pasárselo a `_format_text_codex` |
| Request/validación | `main.py` | `ProcessProjectRequest` (206), `_resolve_explainer_model` (227, NO cambia), `api_process_project` (4805), persistencia `explainer_config` (4948), `_process_project` (2673), `_format_and_finalize_part` (2482) | 206-255, 4805-4965, 2673-2710, 2482-2535 | campo nuevo `codex_effort`; normalización con 400; threading hasta el background task |
| Call sites codex | `main.py` | formatter 2521, classifier 3262, segmentador 3407/3415, subpart/explainer 4009/4036/4084/4119 (región 3995-4125), recorrido/resources 4197/4203, reformat 4707, review 5189 | 2505-2535, 3250-3280, 3395-3430, 3995-4125, 4190-4210, 4640-4710, 5061-5200 | cada sitio gana `effort=codex_effort` |
| Review | `main.py` `api_part_review` | resolución de `explainer_config` (5100-5137), rama codex (5137-5140), gate de vínculo, llamada `review_agent(user_id, explainer, part_title, lang, model)` (5189) | 5099-5200 | effort se resuelve de `explainer_config` (fallback defensivo medium) y se pasa como kw |
| Reformat | `main.py` `api_reformat_project` | rama codex `format_explainer_content_codex(user_id, explainer, reformat_target_language)` (4707); `use_codex` de `project_usage` (4659) | 4640-4720 | mismo patrón de resolución de effort |
| Fake app-server | `tests/backend/fake_codex_app_server.py` | `TRACE_FILE` (82), `_trace_received` (116), llamado en `handle` para TODO request recibido (377), `_handle_scripted_turn` (249) | 58-120, 198-250, 360-395 | **NO se edita**: acepta params arbitrarios y ya traza cada request a `FAKE_CODEX_TRACE_FILE` (JSONL) — la observación de `effort` en tests sale de la traza |
| Card del selector | `frontend/index.html` | card `#provider-card-codex` (268-275), panel `#codex-model-panel` (361-377), grupo modelo informativo `#codex-model-group` (363-370) | 255-380 | el sub-panel de effort se añade DENTRO de `#codex-model-panel`, con el mismo lenguaje visual `.provider-grid`/`.provider-card` |
| Selector JS | `frontend/js/landing.js` | `SELECTOR_KEY` (37), `persistModelSelector` (245), `restoreModelSelector` (268), `validateExplainerProviderSelection` (349), `getReviewProviderConfig` (116, NO cambia), `syncExplainerProviderUI` (~604-640), listeners bajo `_landingListenersAttached` (~875-885), `handleUpload` processPayload (1184-1216) | 1-45, 240-470, 600-650, 860-890, 1175-1230 | constantes de effort, estado `currentCodexEffort`, persist/restore con fallback, payload `codex_effort`, radios y listeners |
| Tests frontend | `tests/frontend/landing.test.js` | tests de round-trip codex (606-660) — incluye el test "never writes new codex fields" (640) que **debe actualizarse** para incluir `codexEffort` | 600-665 | contrato de persistencia del selector |
| Tests frontend | `tests/frontend/landingFlow.test.js` | factory `renderLandingDom` | grep `codex` al implementar | tests DOM del panel de effort (default checked, persist al click) |
| Tests backend | `tests/backend/test_codex_client.py`, `test_codex_pipeline.py`, `test_codex_agents_core.py`, `test_codex_agents_family.py` | patrón: `monkeypatch.setenv("FAKE_CODEX_SCENARIO", ...)` + `FAKE_CODEX_TRACE_FILE` | test_codex_client.py 1-115, 500-660 | dónde añadir pruebas de wire (effort presente/ausente) y de pipeline (persistencia, 400, default) |

## Existing Patterns To Reuse

- **Patrón de constantes por proveedor**: `backend/deepseek_model_routing.py` (`DEEPSEEK_MODEL_V4_PRO`, `max_reasoning_effort`) — `codex_model_routing.py` gana `CODEX_EFFORT_LEVELS`/`CODEX_DEFAULT_EFFORT`/`normalize_codex_effort`.
- **Campo opcional validado en request**: `deepseek_model: DeepSeekExplainerModel | None` en `ProcessProjectRequest` + validación en `api_process_project` vía `_resolve_explainer_model` → 400. Para effort: validación inline con `normalize_codex_effort` → 400 con mensaje congelado (solo cuando provider es codex).
- **Persistencia `explainer_config`** (main.py 4948): añadir la clave `codex_effort` al dict persistido (None para otros providers, como `openrouter_model`).
- **Degradación defensiva de config persistida**: patrón `explainer_config.get("model") or CODEX_MODEL` en review (5137) — para effort: `normalize_codex_effort(...)` en try/except → default + warning.
- **Fake app-server observado vía traza**: `FAKE_CODEX_TRACE_FILE` (JSONL, un mensaje por línea, requests completos con params) — patrón ya usado en tests existentes para verificar el wire-format sin tocar el fake.
- **Frontend**: `persistModelSelector`/`restoreModelSelector` con validación campo a campo (patrón `isValidDeepSeekModel` → aquí `CODEX_EFFORT_LEVELS.includes`); sub-paneles por proveedor con `classList.toggle('hidden', ...)` en `syncExplainerProviderUI`; listeners idempotentes bajo `_landingListenersAttached`.

## Tests And Verification Entry Points

- Backend: `python scripts/run_pytest.py` (testpaths `tests/backend`, runner propio; fixtures `client`/`auth_client`). Archivos de esfuerzo: `test_codex_client.py`, `test_codex_pipeline.py`, `test_codex_agents_core.py`, `test_codex_agents_family.py` (+ `test_api.py` si se toca request schema).
- Frontend: `npx vitest run` (jsdom). Archivos: `landing.test.js`, `landingFlow.test.js`.
- No hay cobertura E2E (playwright) del selector de proveedor hoy; no se añade.

## Named Risks (de este bundle)

- **R-EFFORT-WIRE — `turn/start.effort` UNVERIFIED en live**: la receta verificó la forma del campo en source, no contra un binario vivo. Mitigación: allowlist client-side estricta + default medium + fake/traza pineando el wire; el gate live del bundle anterior sigue pendiente.
- **R-OLD-PROJECTS — proyectos procesados antes de la feature**: `explainer_config` sin `codex_effort` → review/reformat usan medium (default honesto). No se añade campo a `ReviewRequest`; decisión documentada en plan.md.
- **R-COPY — copia UX por nivel**: el texto español de los 5 niveles queda congelado en global-constraints (velocidad/calidad/cuota); cambios posteriores son de producto.
