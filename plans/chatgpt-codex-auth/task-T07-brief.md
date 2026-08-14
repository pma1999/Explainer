# Task T07: Wiring del pipeline — proveedor codex de principio a fin en main.py

## Agent Boundary
Execute this brief directly. Do not load `opencode-orchestrator` or spawn subagents; the parent
orquestador owns coordination.

## Goal
Cablear el proveedor `codex` en `main.py` (literal, resolución de modelo, pre-checks, selección
de agentes por fase, threading, review/reformat, uso de cuota) y en `backend/pricing.py`, sin
alterar el comportamiento de gemini/openrouter/deepseek.

## Acceptance Criteria
- `ExplainerProvider = Literal["gemini","openrouter","deepseek","codex"]` y
  `EXPLAINER_PROVIDER_CODEX: ExplainerProvider = "codex"` (main.py 154-160);
  `_resolve_explainer_model` devuelve `CODEX_MODEL` para codex sin parámetros extra (200-225).
- En `_process_project` (2138+): `use_codex_explainer`; `use_text_provider_explainer =
  or|deepseek|codex`; el fallback YouTube→Gemini (2235-2248) incluye el reset de
  `use_codex_explainer`; `classifier_model`/`segmentation_model`/`auxiliary_agents_model`/
  `validator_model`/`formatter_model` → `CODEX_MODEL` para codex (2180-2207, 2362-2389);
  `requires_gemini_key = explainer_provider in (GEMINI, OPENROUTER) or source_type == "youtube"`
  (2252); sin carga de keys deepseek/openrouter/tavily para codex (2250-2339).
- Invocaciones de fase: segmentador y page_classifier (2662-2802) ganan rama codex
  (`run_segmentador_codex`/`run_page_classifier_codex` con `user_id` en la posición de key,
  corrutinas `await`eadas directamente); explainer/subparte (3324-3479) usan
  `run_explainer_codex[_validated]`/`run_subpart_explainer_codex[_validated]` con
  `text_provider_api_key = user_id` y `validator_user_id = user_id`, invocadas como corrutinas
  async en los `parallel_explainer`/`asyncio.gather` (sustituyendo el wrapper
  `asyncio.to_thread(_call_agent_with_optional_validation_context, ...)` solo en la rama codex,
  con los mismos argumentos posicionales); recorrido/resources (3480-3522) usan
  `run_recorrido_codex(user_id, ...)` y `run_resources_codex(user_id, ...)` con `await`.
- `api_process_project` (4074+): pre-checks codex — vínculo `linked` requerido (si no, 400
  "Vincula tu cuenta ChatGPT en Ajustes para usar Codex (GPT-5.6 Luna)."); `pdf` → key Mistral
  requerida (mensaje análogo a DeepSeek); regla `requires_gemini_key` de
  `global-constraints.md` (4140-4181); `explainer_config` persiste
  `{"provider":"codex","model":"gpt-5.6-luna"}` (4199-4208) sin campos nuevos en
  `ProcessProjectRequest`.
- `api_part_review` (4315-4469): rama `provider == EXPLAINER_PROVIDER_CODEX` con modelo de
  `explainer_config` o `CODEX_MODEL`, `provider_label="Codex"`, gate de vínculo `linked`,
  `review_agent = run_review_codex` con `user_id` en la posición de key (en la rama codex se
  invoca `await review_agent(user_id, ...)` directamente, no vía `asyncio.to_thread`);
  `CodexRateLimitError` → 429 con el mensaje UX congelado; `CodexAuthError` → 400 "Tu cuenta
  ChatGPT ya no está vinculada…"; otros `CodexError` → 502 con mensaje honesto (patrón de los
  except existentes).
- `api_reformat_project` (3923-4071): rama codex → `format_explainer_content_codex(user_id,
  explainer, lang)`; `formatter_usage` con coste 0 y conteos si existen; acumulación en
  `project_usage` sin coste USD.
- `api_generate_mermaid` (4228-4312): **sin cambios** (key DeepSeek de plataforma; decisión
  documentada en el report).
- Usage: `cumulative_usage` inicializa `"codex_quota_requests": 0` (2362-2389); `_update_usage`
  (2393-2430) acumula `getattr(usage_meta, "quota_requests", 0)` y usa
  `getattr(usage_meta, "cost_source", None)` (coste 0 para `chatgpt_quota`, cost_source honesto
  en el log); `_accumulate_review_usage` (2112-2135) admite `CodexUsage` sin romper los demás.
- `backend/pricing.py`: entrada `"gpt-5.6-luna"` con los cuatro precios a `0.0` (fallback de
  `calculate_cost`, nunca coste positivo).
- Errores de agente codex caen en los try/except por parte existentes → `part_failed` + SSE con
  el mensaje UX tipado (sin stack). El flujo `_format_and_finalize_part`/`_failed_part_ids`
  permanece intacto.
- Tests: actualizar `tests/backend/test_main_helpers*.py` (resolución codex) y crear
  `tests/backend/test_codex_pipeline.py` (fake de T02 + `auth_client`): proyecto completo con
  proveedor codex (estados y partes correctos), fallback YouTube, pre-check sin vínculo → 400,
  PDF sin Mistral → 400, review/reformat por rama codex, `codex_quota_requests` acumulado,
  `CodexRateLimitError` en una parte → `part_failed` con mensaje de cuota.

## Scope
Touch:
- `main.py` (solo regiones listadas; imports de variantes codex y routing en 71-72 y cabecera)
- `backend/pricing.py` (entrada gpt-5.6-luna)
- `tests/backend/test_codex_pipeline.py` (nuevo), `tests/backend/test_main_helpers*.py`
  (ampliación aditiva)

Do not touch:
- `backend/codex_client.py`, `codex_app_server.py`, agentes (T05/T06), `supabase_data.py`,
  migraciones, frontend, Dockerfile/koyeb.yaml/DEPLOY.md

## Constraints
- Solo los invariantes de `global-constraints.md` → "Pipeline wiring". Mensajes de error UX
  congelados (cuota/vínculo/saturación) exactamente como en esa sección.
- Ningún cambio de firma en `ProcessProjectRequest`; nada de comportamiento de los otros tres
  proveedores cambia (revisar diffs de las ramas `elif` existentes).

## Interfaces
Consumes:
- T01: `get_user_provider_connection` (pre-checks/gates), `PROVIDER_CODEX`.
- T03: `CODEX_MODEL`, `call_codex_chat` (indirecto vía agentes).
- T05/T06: todas las variantes codex congeladas.
- `backend/pricing.py` actual.

Produces:
- Pipeline completo `explainer_provider="codex"` + ramas review/reformat + uso de cuota.

## Context Pack
| File | Symbol / contract | Read-hint | Why |
|---|---|---|---|
| `main.py` | Literal/constantes, `_resolve_explainer_model` | 154-225 | Punto de entrada del cambio |
| `main.py` | `_process_project`: flags, modelos, fallback, keys, usage | 2138-2437 | Núcleo del wiring |
| `main.py` | segmentador/classifier | 2650-2810 | Invocaciones por proveedor |
| `main.py` | threading explainer + recorrido/resources | 3324-3522 | Selección posicional |
| `main.py` | `_accumulate_review_usage`, `api_reformat_project`, `api_process_project`, `api_part_review`, `api_generate_mermaid` | 2112-2135, 3923-4071, 4074-4225, 4315-4469, 4228-4312 | On-demand + pre-checks |
| `plans/chatgpt-codex-auth/global-constraints.md` | Pipeline wiring | sección | Reglas exactas |

## Existing Patterns To Reuse
- Las ramas `use_deepseek_explainer` como plantilla de cada punto de selección; `functools.partial`
  y threading posicional intactos.

## Tests
- `python scripts/run_pytest.py tests/backend/test_codex_pipeline.py tests/backend/test_main_helpers.py tests/backend/test_main_helpers_v2.py`
- Señal verde: pipeline codex end-to-end contra el fake; suites existentes sin regresiones.

## Implementer
task-implementer-bdd

## Task Review
Required: yes
Why: integración crítica de todo el flujo de procesamiento; regresiones aquí afectan también a
los proveedores existentes.

## Named Risks
- La regla `requires_gemini_key` nueva es sutil (gemini/openrouter o youtube): verificar con
  tests los 4 proveedores × 3 fuentes.
- `_accumulate_review_usage` usa `calculate_cost(model)`: con la entrada pricing a 0 el coste es
  0; confirmar que ningún camino asigna coste positivo a codex.

## Report Path
`plans/chatgpt-codex-auth/task-T07-report.md`
