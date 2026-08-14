# Task T05: Variantes Codex núcleo — explainer (+validado), segmentador y page_classifier

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Crear `backend/agents/explainer_codex.py` (explainer completo/subparte con validación de
completitud vía Codex) y añadir `run_segmentador_codex`/`run_page_classifier_codex` a sus
módulos, todas con el contrato `(data, CodexUsage)` y validación `*_validated` como en las
variantes DeepSeek.

## Acceptance Criteria
- `backend/agents/explainer_codex.py` con las firmas congeladas de `plan.md` →
  Cross-task interfaces: `run_explainer_codex`, `run_subpart_explainer_codex`,
  `run_explainer_codex_validated`, `run_subpart_explainer_codex_validated`,
  `run_with_codex_explainer_validation` — todas **corrutinas `async`**. El parámetro `user_id`
  ocupa la posición de `api_key` de las variantes `_ds`; `validator_user_id` la de
  `validator_api_key`.
- Reutiliza los helpers existentes sin duplicar lógica de prompts/validación:
  `_build_inline_source_message`, `build_openrouter_explainer_system_prompt`,
  `build_openrouter_subpart_explainer_system_prompt`, `_validate_full_explainer_payload`,
  `_validate_subpart_explainer_payload` (de `explainer_openrouter.py`/`explainer_deepseek.py`) y
  `ExplainerValidationContext`/`format_explainer_retry_context` de `completeness_validator.py`.
- El reintento conversacional replica `_DeepSeekExplainerConversation` sobre `await
  call_codex_chat(...)`: system + primer user message byte-idénticos; cada regeneración añade el
  turno anterior + el feedback; el validador de completitud se ejecuta vía Codex (sin key de
  DeepSeek).
- `backend/agents/segmentador.py` gana `async def run_segmentador_codex(api_key, source_text,
  description, source_kind="pdf", model=CODEX_MODEL, target_language="es-ES", *, conversation=None,
  correction=None) -> tuple[dict, CodexUsage, list]`, espejo posicional de `run_segmentador_ds`
  (segmentador.py:1319) sobre `call_codex_chat` con los mismos `_openrouter_*` builders; la
  conversación de corrección por cobertura se mantiene byte-idéntica en el prefijo.
- `backend/agents/page_classifier.py` gana `async def run_page_classifier_codex(api_key,
  source_text, total_pages, model=CODEX_MODEL) -> tuple[frozenset, CodexUsage, dict]`, espejo de
  `run_page_classifier_ds` (page_classifier.py:422).
- Logs sin prompts fuente completos ni credenciales (previews truncados, `user_id[:8]`).
- Tests `tests/backend/test_codex_agents_core.py` (asyncio; fake de T02 read-only, salidas
  deterministas vía `scripted_turn` con fixtures JSON propios): cada variante devuelve
  `(data, CodexUsage)` con payloads válidos; payload inválido → reintento y luego `CodexError`;
  validación de completitud con reintento vía `run_with_codex_explainer_validation`; segmentador
  con retry de conversación; classifier feliz y con error.

## Scope
Touch:
- `backend/agents/explainer_codex.py` (nuevo)
- `backend/agents/segmentador.py` (solo añadir `run_segmentador_codex` + import)
- `backend/agents/page_classifier.py` (solo añadir `run_page_classifier_codex` + import)
- `tests/backend/test_codex_agents_core.py` (nuevo) + fixtures JSON propios bajo
  `tests/backend/fixtures_codex/` (nunca editar `fake_codex_app_server.py`)

Do not touch:
- `backend/codex_client.py`, `codex_model_routing.py`, `codex_app_server.py`, `main.py`,
  `recorrido.py`, `resources.py`, `review.py`, `formatter.py` (son de T06), frontend, despliegue

## Constraints
- Solo los invariantes de `global-constraints.md` → "Agent variants" y "Fake app-server". Firmas
  exactas en `plan.md`. No renombrar ni cambiar el orden de parámetros respecto a las `_ds`; las
  variantes son **corrutinas async** (se esperan directo, nunca vía `asyncio.to_thread`).
- Ninguna variante usa `deepseek_client` ni requiere key de DeepSeek; todo pasa por
  `call_codex_chat`.

## Interfaces
Consumes:
- T03: `call_codex_chat`, `CodexUsage`, `CodexError`, `CODEX_MODEL`.
- `backend/agents/explainer_openrouter.py`: builders de prompts y validadores de payload
  (imports existentes en `explainer_deepseek.py:15-24`).
- `backend/agents/completeness_validator.py`: `ExplainerValidationContext`,
  `ExplainerValidationReport`, `format_explainer_retry_context`.

Produces (contrato para T07):
- Las cinco funciones de `plan.md` → Cross-task interfaces.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `backend/agents/explainer_deepseek.py` | `run_explainer_ds`, `_DeepSeekExplainerConversation`, `_call_deepseek_with_validation_retries` | 89-119, 153-268, 280-462 | Plantilla exacta a espejar |
| `backend/agents/segmentador.py` | `run_segmentador_ds` | 1319-1420 | Firma y flujo de retry |
| `backend/agents/page_classifier.py` | `run_page_classifier_ds` | 422-500 | Firma y prompt |
| `backend/agents/completeness_validator.py` | `run_with_deepseek_explainer_validation` | grep | Lógica de reintento de completitud |
| `plans/chatgpt-codex-auth/global-constraints.md` | Agent variants | sección | Contratos |

## Existing Patterns To Reuse
- `explainer_deepseek.py` completo (fuente de `_build_inline_source_message`, retries, logging).
- `run_with_deepseek_explainer_validation` como plantilla del runner codex.

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_agents_core.py`
- Señal verde: payloads deterministas, reintentos, errores tipados; sin red real.

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: contrato del explainer y de los agentes de segmentación que el pipeline (T07) consume
posicionalmente; un desvío de firma rompe la ola 4.

## Named Risks
- El validador de completitud vía Codex duplica un turno por validación: contar con
  `quota_requests` acumulando más de 1 por llamada validada (comportamiento esperado y honesto).
- No copiar docstrings/constantes `DEEPSEEK_*` por accidente al espejar.

## Report Path
`plans/chatgpt-codex-auth/task-T05-report.md`
