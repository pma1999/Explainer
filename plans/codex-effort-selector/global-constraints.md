# Global Constraints: Selector de thinking/effort — Codex (GPT-5.6 Luna)

Invariantes ejecutables para TODAS las tareas del bundle. No contiene reglas de proceso. Un
cambio de estos contratos exige volver a secuenciar dependientes y registrarlo en el decision
ledger de `progress.md`. Los invariantes de `plans/chatgpt-codex-auth/global-constraints.md`
siguen vigentes salvo adición explícita aquí.

## Allowlist y default (único contrato de valores)

- Niveles válidos, en orden canónico de UI: `low`, `medium`, `high`, `xhigh`, `max`. Default:
  `medium`. Prohibido exponer o aceptar en la API: `none`, `minimal`, `ultra`, `extra_high`,
  `auto`.
- Backend (único validador de autoridad): `backend/codex_model_routing.py` gana

  ```python
  CODEX_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
  CODEX_DEFAULT_EFFORT = "medium"

  def normalize_codex_effort(value: str | None) -> str:
      """None/'' → medium; valor no-allowlist → ValueError; nunca devuelve otro valor."""
  ```

- Frontend (espejo, sin importar backend): `frontend/js/landing.js` exporta
  `CODEX_EFFORT_LEVELS = ['low','medium','high','xhigh','max']` y
  `CODEX_DEFAULT_EFFORT = 'medium'`. La UI solo emite valores de esta lista.

## Wire contract (codex_client)

- `call_codex_chat` gana el keyword `effort: str | None = None` **al final** de su firma
  keyword-only (tras `timeout`); todos los demás parámetros y su orden quedan idénticos.
- `_turn_params(*, thread_id, text, model, effort=None)`: añade `"effort": effort` al dict de
  `turn/start` **solo si `effort` no es None**. `_thread_start_params` NO cambia: nunca se
  envía `config.model_reasoning_effort` ni ningún campo de effort en `thread/start`.
- El pipeline siempre resuelve un nivel concreto (default medium) y lo pasa explícito; los
  llamadores directos de `call_codex_chat` pueden pasar `None` (campo ausente en wire). La
  clave wire es exactamente `"effort"` (no `reasoning_effort`).
- El turno correctivo del reintento JSON (mismo thread) conserva el mismo `effort` del intento
  original. El `docstring` del cliente documenta la adición.

## Variantes de agentes codex (firmas congeladas)

Cada variante pública gana `effort: str | None = None` como **último parámetro keyword**; el
orden posicional congelado en `chatgpt-codex-auth/plan.md` §Cross-task interfaces NO cambia:

```python
# backend/agents/explainer_codex.py
async def run_explainer_codex(source_path, identificacion, model=CODEX_MODEL,
                              mime_type="application/pdf", user_id="",
                              pdf_cache_entry=None, page_numbers=None,
                              target_language="es-ES", *, effort=None) -> tuple[dict, CodexUsage]
async def run_subpart_explainer_codex(... igual ..., *, effort=None) -> tuple[dict, CodexUsage]
async def run_explainer_codex_validated(..., validation_context=None,
                                        target_language="es-ES", *, effort=None) -> tuple[dict, CodexUsage, list]
async def run_subpart_explainer_codex_validated(..., *, effort=None) -> tuple[dict, CodexUsage, list]
async def check_explainer_validation_codex(explanation, user_id,
                                           validation_context=None, model=CODEX_MODEL_AUXILIARY,
                                           *, effort=None) -> tuple[ExplainerValidationReport, CodexUsage | None]
async def run_with_codex_explainer_validation(*, initial_call, retry_call, user_id, label,
                                              validation_context=None, effort=None) -> tuple[dict, CodexUsage, list]

# backend/agents/segmentador.py
async def run_segmentador_codex(api_key, source_text, description, source_kind="pdf",
                                model=CODEX_MODEL, target_language="es-ES", *,
                                conversation=None, correction=None, effort=None) -> tuple[dict, CodexUsage, list]

# backend/agents/page_classifier.py
async def run_page_classifier_codex(api_key, source_text, total_pages,
                                    model=CODEX_MODEL, *, effort=None) -> tuple[frozenset, CodexUsage, dict]

# backend/agents/recorrido.py
async def run_recorrido_codex(user_id, source_text, identificacion, model=CODEX_MODEL,
                              target_language="es-ES", *, effort=None) -> tuple[dict, CodexUsage]

# backend/agents/resources.py
async def run_resources_codex(user_id, source_text, identificacion, model=CODEX_MODEL,
                              target_language="es-ES", *, effort=None) -> tuple[dict, CodexUsage]

# backend/agents/review.py
async def run_review_codex(user_id, explainer_content, part_title, target_language="es-ES",
                           model=CODEX_MODEL, *, effort=None) -> tuple[dict, CodexUsage]

# backend/agents/formatter.py
async def _format_text_codex(user_id, text, context="", target_language="es-ES",
                             *, effort=None) -> tuple[str, Any]
async def format_explainer_content_codex(user_id, explainer_data, target_language="es-ES",
                                         *, effort=None) -> tuple[dict, dict]
```

Forwarding obligatorio (sin saltarse ningún `call_codex_chat`): `_call_codex_json_with_pdf_fallback`
(gana `effort=None`), `_CodexExplainerConversation.__init__` (gana `effort=None`),
`run_with_codex_explainer_validation` → `check_explainer_validation_codex`, y
`format_explainer_content_codex` → `_format_text_codex` en el list comprehension del gather.

## API y persistencia (main.py)

- `ProcessProjectRequest` gana `codex_effort: str | None = None`. `_resolve_explainer_model`
  NO cambia. `ReviewRequest` y `MermaidRequest` NO cambian.
- En `api_process_project`, **solo cuando `explainer_provider == "codex"`**:
  `codex_effort = normalize_codex_effort(payload.codex_effort if payload else None)` dentro de
  try/except `ValueError` → `HTTPException(400)` con el mensaje congelado:

  ```text
  "Nivel de razonamiento de Codex no soportado: '{valor}'. Usa uno de: low, medium, high, xhigh, max."
  ```

  Para otros providers, `codex_effort` queda `None` (campo ignorado, nunca 400).
- `_process_project` gana `codex_effort: str = CODEX_DEFAULT_EFFORT` **al final** (tras
  `openrouter_provider_routing`); el `background_tasks.add_task` de `api_process_project` lo
  pasa posicionalmente. `_format_and_finalize_part` gana `codex_effort: str =
  CODEX_DEFAULT_EFFORT` (keyword, tras `use_codex`).
- Call sites codex que ganan `effort=codex_effort` (kw): formatter (dentro de
  `_format_and_finalize_part`), `run_page_classifier_codex`, `run_segmentador_codex` (ambos
  intentos), `run_subpart_explainer_codex`/`run_explainer_codex` (región de subparts y
  explains, todas las ramas codex), `run_recorrido_codex`, `run_resources_codex`.
  Ningún call site de gemini/openrouter/deepseek cambia.
- `explainer_config` persistido en `api_process_project` gana la clave
  `"codex_effort": codex_effort` (None si el provider no es codex).
- `api_part_review` (rama codex) y `api_reformat_project` (rama codex): resolver
  `codex_effort = normalize_codex_effort((project.get("explainer_config") or {}).get("codex_effort"))`
  dentro de try/except `ValueError` → fallback `CODEX_DEFAULT_EFFORT` + `logger.warning` (los
  proyectos viejos sin campo o con valor corrupto degradan a medium, nunca 400). Pasar
  `effort=codex_effort` a `run_review_codex` / `format_explainer_content_codex`.
- YouTube fallback, mermaid, auth, pricing y `getReviewProviderConfig` quedan intactos.

## Fake app-server (tests)

- `tests/backend/fake_codex_app_server.py` **no se edita**. Ya acepta params arbitrarios en
  `turn/start` (solo lee `threadId`) y traza cada request recibido (con sus params) a
  `FAKE_CODEX_TRACE_FILE` (JSONL). Los tests observan el wire de `effort` parseando la traza:
  `json.loads(line)` → filtrar `method == "turn/start"` → `params.get("effort")`.
  Si una observación necesaria resultara imposible, se reporta al orquestador (decisión
  explícita), no se edita el fixture.

## Frontend UX (copia y contratos congelados)

- Persistencia: clave existente `explainer.modelSelector.v1`; campo nuevo `codexEffort`
  (string de la allowlist). `persistModelSelector` la escribe siempre;
  `restoreModelSelector`: `CODEX_EFFORT_LEVELS.includes(saved.codexEffort) ?
  saved.codexEffort : CODEX_DEFAULT_EFFORT` (campo ausente/inválido/no-string → medium).
  Estado: `let currentCodexEffort = CODEX_DEFAULT_EFFORT`.
- Payload de `POST /api/projects/{id}/process`: `processPayload.codex_effort =
  currentCodexEffort` **solo cuando `currentExplainerProvider === 'codex'`**.
- DOM: dentro de `#codex-model-panel`, tras `#codex-model-group`, el bloque "Nivel de
  razonamiento (thinking)" con: `<div class="provider-grid openrouter-model-grid"
  id="codex-effort-group">` y 5 `<label class="provider-card">` con radios
  `name="codex-effort"`, ids `codex-effort-{low|medium|high|xhigh|max}` (medium `checked` en
  HTML), y tras el grupo un párrafo nota congelada. Reutiliza clases existentes; no se
  introducen nuevas clases salvo que sean imprescindibles y mínimas.
- Copia congelada por nivel (título — descripción; orden de la allowlist):

  | value | Título | Descripción |
  |---|---|---|
  | low | Rápido | Menos razonamiento y menor consumo de cuota. Ideal para textos sencillos. |
  | medium | Equilibrado (Recomendado) | Equilibrio entre velocidad y profundidad. Consume una cuota moderada. |
  | high | Profundo | Razonamiento más extenso. Mayor calidad y más consumo de cuota. |
  | xhigh | Muy profundo | Análisis muy intensivo para textos complejos. Consumo alto. |
  | max | Máximo | Máxima profundidad de razonamiento. El mayor consumo de cuota. |

  La marca "Recomendado" es parte del título de medium (no un elemento separado obligatorio).
- Nota del panel (congelada, tras el grupo):
  "El nivel se aplica a todas las fases: segmentación, explicación, recorrido, recursos,
  repaso y formateo."
- `syncExplainerProviderUI` refleja `currentCodexEffort` en los radios; listener `change`
  sobre `#codex-effort-group` (registrado bajo el guard `_landingListenersAttached`):
  `currentCodexEffort = value; persistModelSelector()`. El panel entero sigue el patrón
  `classList.toggle('hidden', currentExplainerProvider !== 'codex' || !codexSupported)`.

## Security / quality

- Nunca loguear valores de effort sin validar como contenido de usuario; el error 400 incluye
  el valor crudo SOLO dentro del mensaje congelado (sin stack ni detalles internos).
- `normalize_codex_effort` no acepta strings con espacios/casing distinto; el wire solo recibe
  valores exactos de la allowlist.
- Ninguna tarea toca: `android/`, flujos gemini/openrouter/deepseek, `backend/auth.py`,
  `api_generate_mermaid`, fallback YouTube→Gemini, ni `getReviewProviderConfig`.
