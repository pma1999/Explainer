# Task T06: Variantes Codex familia — recorrido, resources, review y formatter

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Añadir las variantes Codex de la familia del explainer: `run_recorrido_codex`,
`run_resources_codex` (sin búsqueda web en v1), `run_review_codex` y
`format_explainer_content_codex`, todas con contrato `(data, CodexUsage)` (o `(dict, dict)` el
formatter) y validación como en sus variantes `_ds`.

## Acceptance Criteria
- `backend/agents/recorrido.py` gana `async def run_recorrido_codex(user_id, source_text,
  identificacion, model=CODEX_MODEL, target_language="es-ES") -> tuple[dict, CodexUsage]`, espejo
  de `run_recorrido_ds` (recorrido.py:563) usando `call_codex_chat` con
  `build_recorrido_openrouter_system_instruction` y la validación de payload existente del
  recorrido (misma que usa la variante `_ds`).
- `backend/agents/resources.py` gana `async def run_resources_codex(user_id, source_text,
  identificacion, model=CODEX_MODEL, target_language="es-ES") -> tuple[dict, CodexUsage]`, espejo
  de `run_resources_ds` (resources.py:648) pero **sin Tavily ni herramientas**: el prompt del
  sistema indica "recomienda desde tu conocimiento; sin búsqueda web". Reusa el validador de
  payload de resources existente.
- `backend/agents/review.py` gana `async def run_review_codex(user_id, explainer_content,
  part_title, target_language="es-ES", model=CODEX_MODEL) -> tuple[dict, CodexUsage]`, espejo de
  `run_review_ds` (review.py:468) con `build_review_system_instruction` y la validación/retries
  de review existentes.
- `backend/agents/formatter.py` gana `async def format_explainer_content_codex(user_id,
  explainer_data, target_language="es-ES") -> tuple[dict, dict]`, espejo de
  `format_explainer_content_ds` (formatter.py:693): formato por campos en paralelo vía
  `await call_codex_chat(...)`, mismo resumen de usage `_build_formatter_usage_summary` con coste
  0 y conteos reportados si existen.
- Logs sin prompts fuente completos ni credenciales (previews truncados, `user_id[:8]`).
- Tests `tests/backend/test_codex_agents_family.py` (asyncio; fake de T02 read-only, salidas vía
  `scripted_turn` con fixtures JSON propios): cada variante feliz con payload determinista,
  inválido → reintento → éxito/`CodexError`, `CodexRateLimitError` propagado, formatter con
  campos paralelos y `_empty_formatter_usage()` sin campos.

## Scope
Touch:
- `backend/agents/recorrido.py`, `backend/agents/resources.py`, `backend/agents/review.py`,
  `backend/agents/formatter.py` (solo añadir variantes + imports)
- `tests/backend/test_codex_agents_family.py` (nuevo) + fixtures JSON propios bajo
  `tests/backend/fixtures_codex/` (nunca editar `fake_codex_app_server.py`)

Do not touch:
- `backend/codex_client.py`, `codex_model_routing.py`, `codex_app_server.py`, `main.py`,
  `explainer_codex.py`/`segmentador.py`/`page_classifier.py` (T05), frontend, despliegue

## Constraints
- Solo los invariantes de `global-constraints.md` → "Agent variants" y "Fake app-server". Firmas
  exactas en `plan.md`. Posición `user_id` donde las `_ds` llevan `api_key`; variantes **async**
  esperadas directamente.
- `run_resources_codex` NO usa Tavily ni tools del app-server en v1 (decisión del plan).

## Interfaces
Consumes:
- T03: `call_codex_chat`, `CodexUsage`, `CodexError`, `CODEX_MODEL`.
- Builders/validadores internos de cada módulo (los mismos que usan las variantes `_ds`).

Produces (contrato para T07):
- `run_recorrido_codex`, `run_resources_codex`, `run_review_codex`,
  `format_explainer_content_codex` (firmas de `plan.md`).

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `backend/agents/recorrido.py` | `run_recorrido_ds` | 563-640 | Plantilla |
| `backend/agents/resources.py` | `run_resources_ds` | 648-760 | Plantilla (sin Tavily) |
| `backend/agents/review.py` | `run_review_ds` | 468-560 | Plantilla |
| `backend/agents/formatter.py` | `format_explainer_content_ds`, `_build_formatter_usage_summary`, `_empty_formatter_usage` | 588-740, grep | Plantilla y resumen de usage |
| `plans/chatgpt-codex-auth/global-constraints.md` | Agent variants | sección | Contratos |

## Existing Patterns To Reuse
- Las variantes `_ds` de cada módulo son la plantilla exacta; solo cambia el transporte
  (DeepSeek → `call_codex_chat`) y el primer parámetro (`api_key` → `user_id`).
- `_apply_parallel_formatter_results`/`_build_formatter_usage_summary` del formatter.

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_agents_family.py`
- Señal verde: payloads deterministas, reintentos, errores tipados; sin red real.

## Implementer
task-implementer-bdd

## Task Review
Required: no
Why: espejos mecánicos de variantes existentes cubiertos por tests unitarios; final review es
suficiente.

## Named Risks
- El formatter paraleliza muchas llamadas por parte (una por campo): respetar el semáforo por
  proceso (5) y el timeout; no lanzar `asyncio.gather` sin acotación mayor que la variante `_ds`.
- Resources sin búsqueda: documentar en el report que la frescura depende del conocimiento del
  modelo (riesgo R-RESOURCES del plan).

## Report Path
`plans/chatgpt-codex-auth/task-T06-report.md`
