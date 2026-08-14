# Task T01: Effort Codex — backend (allowlist, wire, variantes, pipeline, persistencia)

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Añadir el nivel de razonamiento (effort) de `gpt-5.6-luna` al backend: allowlist y
normalización, campo `effort` en el wire de `turn/start`, keyword `effort` en `call_codex_chat`
y en todas las variantes de agentes codex, campo opcional `codex_effort` en
`ProcessProjectRequest` con 400 ante valores no soportados, threading hasta todas las fases
codex, persistencia en `explainer_config`, y resolución en review/reformat — con tests que
prueban el wire vía la traza del fake app-server.

## Acceptance Criteria
- `call_codex_chat(effort="xhigh")` produce un request `turn/start` cuyo `params` contiene
  `"effort": "xhigh"` (observado en `FAKE_CODEX_TRACE_FILE`), y `call_codex_chat(...)` sin
  `effort` produce un `turn/start` SIN clave `effort`. `thread/start` nunca lleva effort.
- El turno correctivo del reintento JSON (mismo thread) conserva el mismo `effort`.
- `POST /api/projects/{id}/process` con `explainer_provider="codex"` y `codex_effort="xhigh"`
  responde 200, persiste `explainer_config.codex_effort == "xhigh"` y TODOS los `turn/start`
  de todas las fases codex llevan `"effort":"xhigh"` en la traza.
- Sin `codex_effort` (o `null`) → todo el pipeline usa `"medium"` y persiste `medium`.
- `codex_effort` con valor no soportado (`"none"`, `"ultra"`, `"auto"`, `"extra_high"`,
  `"minimal"`) en provider codex → HTTP 400 con el mensaje congelado (ver Constraints).
  `""` (vacío) NO es un 400: se unifica con el contrato congelado (`None/'' → medium`).
- Provider gemini/openrouter/deepseek con `codex_effort` presente → campo ignorado,
  `explainer_config.codex_effort` persistido como `null`, sin 400.
- `api_part_review` y `api_reformat_project` en proyectos codex usan el effort de
  `explainer_config`; un proyecto codex viejo (sin `codex_effort` en el config) usa `medium`
  sin error.
- Suites existentes verdes: `python scripts/run_pytest.py` completo.

## Scope
Touch:
- `backend/codex_model_routing.py` — `CODEX_EFFORT_LEVELS`, `CODEX_DEFAULT_EFFORT`,
  `normalize_codex_effort`.
- `backend/codex_client.py` — `call_codex_chat` (+docstring) y `_turn_params`.
- `backend/agents/explainer_codex.py` — 6 variantes/helpers listados en Constraints.
- `backend/agents/segmentador.py`, `backend/agents/page_classifier.py`,
  `backend/agents/recorrido.py`, `backend/agents/resources.py`,
  `backend/agents/review.py`, `backend/agents/formatter.py` — variantes codex.
- `main.py` — `ProcessProjectRequest` (206), `api_process_project` (4805), persistencia
  `explainer_config` (4948), `_process_project` (2673), `_format_and_finalize_part` (2482),
  call sites codex (2521, 3262, 3407/3415, 4009/4036/4084/4119 y lista contigua, 4197/4203,
  4707, 5189), `api_part_review` (5061), `api_reformat_project` (~4640).
- Tests: `tests/backend/test_codex_client.py`, `tests/backend/test_codex_pipeline.py` (o
  `tests/backend/test_codex_effort.py` nuevo), `tests/backend/test_codex_agents_core.py`,
  `tests/backend/test_codex_agents_family.py`.

Do not touch:
- `tests/backend/fake_codex_app_server.py` (read-only; observación vía
  `FAKE_CODEX_TRACE_FILE`).
- `frontend/**`, `tests/frontend/**`, `android/**`, `backend/auth.py`,
  `backend/pricing.py`, `api_generate_mermaid`, fallback YouTube→Gemini,
  `getReviewProviderConfig` (frontend), `ReviewRequest`/`MermaidRequest`, y cualquier código
  de gemini/openrouter/deepseek.

## Constraints
Solo los invariantes de `plans/codex-effort-selector/global-constraints.md` que vinculan esta
tarea: secciones "Allowlist y default", "Wire contract", "Variantes de agentes codex",
"API y persistencia (main.py)" y "Security / quality". Además, todo invariante de
`plans/chatgpt-codex-auth/global-constraints.md` (§Agent variants, §Codex client and errors)
que esta tarea no modifica explícitamente sigue vigente.

## Interfaces
Consumes:
- `backend/codex_app_server.py`: `codex_manager`, `CodexRequestError`, `CodexSpawnError`
  (sin cambios).
- `backend/agents/explainer_openrouter.py`: `OPENROUTER_EXPLAINER_TEMPERATURE`,
  `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES` (sin cambios).

Produces (congelados; el frontend los espeja):
```python
# backend/codex_model_routing.py
CODEX_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CODEX_DEFAULT_EFFORT = "medium"
def normalize_codex_effort(value: str | None) -> str   # None/'' → medium; no-allowlist → ValueError

# backend/codex_client.py
async def call_codex_chat(*, user_id, messages, system_prompt, model=CODEX_MODEL,
                          response_format="json_object", temperature=..., timeout=...,
                          effort: str | None = None) -> tuple[Any, CodexUsage]

# main.py
class ProcessProjectRequest(BaseModel):
    ...  # campos existentes intactos
    codex_effort: str | None = None
```
Mensaje 400 congelado: `"Nivel de razonamiento de Codex no soportado: '{valor}'. Usa uno de: low, medium, high, xhigh, max."`

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `plans/codex-effort-selector/global-constraints.md` | secciones "Allowlist y default", "Wire contract", "Variantes de agentes codex", "API y persistencia" | completo (2 páginas) | Contrato ejecutable de esta tarea |
| `plans/codex-effort-selector/integration-effort.md` | niveles Luna, `turn/start.effort`, thread sin effort, allowlist client-side | 16-37, 54-65 | Wire verificado que emite el cliente |
| `backend/codex_model_routing.py` | `CODEX_MODEL` y constantes actuales | completo (corto) | Dónde viven las constantes nuevas |
| `backend/codex_client.py` | `call_codex_chat` (539), `_turn_params` (311), `_thread_start_params` (301) | 296-322, 539-640 | Punto único del wire |
| `backend/agents/explainer_codex.py` | `_call_codex_json_with_pdf_fallback` (104), `_CodexExplainerConversation.__init__` (251), `check_explainer_validation_codex` (365), `run_with_codex_explainer_validation` (432), variantes públicas (138/199/519/563) | 104-135, 251-330, 360-470, 515-600 | Forwarding interno obligatorio |
| `backend/agents/{segmentador,page_classifier,recorrido,resources,review,formatter}.py` | variantes codex 1404/479/624/784/562/787 y `_format_text_codex` 590 | read-hints en context-map.md | Firma keyword final `effort` |
| `main.py` | `ProcessProjectRequest` (206), `api_process_project` (4805), persist (4948), `_process_project` (2673), `_format_and_finalize_part` (2482), call sites codex, `api_part_review` (5061), `api_reformat_project` (~4640) | 206-255, 2482-2535, 2673-2710, 3250-3280, 3395-3430, 3995-4125, 4190-4210, 4640-4720, 4805-4965, 5099-5200 | Threading y persistencia |
| `tests/backend/fake_codex_app_server.py` | `FAKE_CODEX_TRACE_FILE` (82), `_trace_received` (116, llamado en 377) | 58-120, 360-395 | Mecanismo de observación del wire (no editar) |
| `tests/backend/test_codex_client.py` | patrón de env + `scripted_turn` + traza | 1-115, 95-115 | Patrón de test a extender |

## Existing Patterns To Reuse
- Traza del fake: `monkeypatch.setenv("FAKE_CODEX_TRACE_FILE", tmp_path/"trace.jsonl")` +
  `FAKE_CODEX_SCENARIO=scripted_turn` + `FAKE_CODEX_TURN_OUTPUT_FILE`; parsear cada línea con
  `json.loads`, filtrar `method == "turn/start"`, leer `params.get("effort")`.
- Validación de request: patrón `deepseek_model` en `api_process_project` (try/except
  `ValueError` → `HTTPException(400)`).
- Persistencia: `update_project(project_id, user_id, {"explainer_config": {...}})` en
  `api_process_project` (4948); lectura defensiva `explainer_config.get(...) or ...` en review
  (5100-5137).
- Fixture auth: `tests/backend/conftest.py` `auth_client` (override `get_current_user_id` →
  `"user-123"`); pipeline codex contra fake (patrón de `test_codex_pipeline.py`).
- Formatter en pipeline: `_format_and_finalize_part` es task separada — pasar
  `codex_effort=codex_effort` en su call site (4352).

## Tests
Nuevos/ajustados (ejecutar siempre `python scripts/run_pytest.py` al final; mínimo
`python scripts/run_pytest.py tests/backend/test_codex_client.py tests/backend/test_codex_pipeline.py tests/backend/test_codex_agents_core.py tests/backend/test_codex_agents_family.py`):
- `test_codex_client.py`: (a) `call_codex_chat(effort="xhigh")` con `scripted_turn` → traza
  contiene `turn/start` con `params.effort == "xhigh"`; (b) sin `effort` → ningún
  `turn/start` de la traza tiene la clave `effort`; (c) retry conversacional (fichero salida
  inválido `.1` válido) → ambos `turn/start` llevan el mismo `effort`; (d) `thread/start`
  nunca lleva `effort` ni `config.model_reasoning_effort`.
  Red: fallan al añadirse (el wire aún no envía effort). Green: tras implementar.
- `test_codex_agents_core.py` / `test_codex_agents_family.py`: cada variante pública
  invocada con `effort="low"` produce `turn/start` con `"effort":"low"` en la traza (usa las
  fixtures existentes de cada familia; añade el kw y el assert de traza).
- `test_codex_pipeline.py` (o nuevo `test_codex_effort.py`): flujo `/process` codex con
  `codex_effort="xhigh"` → 200, `explainer_config.codex_effort=="xhigh"`, traza con xhigh en
  todas las fases; sin campo → `"medium"`; valores inválidos (`none`, `ultra`,
  `auto`) → 400 con el mensaje congelado; `""` → 200 y `"medium"` (como `None`); provider gemini con `codex_effort="max"` → 200 y
  `explainer_config.codex_effort is None`; review y reformat: proyecto codex con
  `explainer_config.codex_effort="xhigh"` → traza de review/reformat con xhigh; config sin
  `codex_effort` → medium (sin 400).
- Regresión: suite backend completa verde.

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: frontera API (400 + campo nuevo), wire-format del cliente y threading transversal que el
frontend (T02) espeja; un cambio aquí re-secuenciaría T02.

## Named Risks
- R-EFFORT-WIRE (UNVERIFIED en live): limitarse a la forma del campo verificada en la receta;
  no inventar campos (`thread/start.effort`, `reasoning_effort`).
- R-OLD-PROJECTS: degradación defensiva a medium en review/reformat (never 400 desde config
  persistida).

## Report Path
`plans/codex-effort-selector/task-T01-report.md`
