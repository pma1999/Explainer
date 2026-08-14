# Task T07 Report

## Status
DONE

## Outcome
El proveedor `codex` queda cableado de principio a fin en `main.py`: literal y
resolución de modelo (`gpt-5.6-luna`), selección de agentes por fase con
`user_id` en la posición de `api_key` y corrutinas async await-eadas directo
(segmentador, page_classifier, explainer/subparte validados, recorrido,
resources, formatter, review), pre-checks de `api_process_project` (vínculo
`linked` + Mistral para PDF + regla `requires_gemini_key`), ramas codex de
review/reformat, acumulación de `codex_quota_requests` con coste USD 0
(`_update_usage`, `_accumulate_review_usage`, pricing `gpt-5.6-luna` a 0.0),
fallback YouTube→Gemini con reset de `use_codex_explainer`, y errores de
agente codex que caen en el flujo por parte existente → `part_failed` + SSE
con el mensaje UX tipado sin stack. `api_generate_mermaid` sin cambios
(decisión documentada). Comportamiento de gemini/openrouter/deepseek intacto
(suite completa verde).

## Acceptance Criteria
- Literal `["gemini","openrouter","deepseek","codex"]` + `EXPLAINER_PROVIDER_CODEX`; `_resolve_explainer_model("codex", ...)` → `CODEX_MODEL` sin parámetros extra -> pass (`test_codex_resolves_fixed_model`, `test_codex_ignores_extra_model_params`, `test_literal_accepts_codex`)
- `_process_project`: `use_codex_explainer`; `use_text_provider_explainer = or|deepseek|codex`; fallback YouTube→Gemini resetea `use_codex_explainer`; modelos classifier/segmentation/auxiliary/validator/formatter → `CODEX_MODEL`; `requires_gemini_key = or|(no ds y no codex)|youtube`; sin carga de keys ds/or/tavily para codex (solo Mistral para PDF) -> pass (`test_full_codex_pipeline_states_parts_and_usage`, `test_youtube_falls_back_to_gemini_and_never_calls_codex_agents`)
- Invocaciones de fase: segmentador/classifier con rama codex await-eada directo; explainer/subparte vía `run_explainer_codex_validated`/`run_subpart_explainer_codex_validated` con `user_id`/`validator_user_id` (corrutinas en `parallel_explainer`/gather sustituyendo solo en la rama codex el wrapper `to_thread`); recorrido/resources `run_recorrido_codex(user_id, ...)`/`run_resources_codex(user_id, ...)` con `await` -> pass (argumentos posicionales verificados en `test_full_codex_pipeline_states_parts_and_usage`)
- `api_process_project`: sin vínculo → 400 "Vincula tu cuenta ChatGPT en Ajustes para usar Codex (GPT-5.6 Luna)."; PDF sin Mistral → 400 "…OCR nativo en PDFs con Codex."; `requires_gemini_key` según la regla; `explainer_config` persiste `{"provider":"codex","model":"gpt-5.6-luna",...}` sin campos nuevos -> pass (`test_codex_without_link_returns_400`, `test_codex_pdf_without_mistral_returns_400`, `test_codex_linked_web_starts_and_persists_explainer_config`, `test_requires_gemini_key_matrix` 4×3)
- `api_part_review`: rama codex con modelo de `explainer_config` o `CODEX_MODEL`, `provider_label="Codex"`, gate `linked`, `review_agent = run_review_codex` await-eado directo con `user_id`; `CodexRateLimitError` → 429 con su mensaje; `CodexAuthError` → 400 con el mensaje de re-vincular; otros `CodexError` → 502 -> pass (4 tests de `TestPartReviewCodexBranch`)
- `api_reformat_project`: rama codex → `format_explainer_content_codex(user_id, explainer, lang)`; `formatter_usage` coste 0 con conteos; acumulación en `project_usage` sin coste USD -> pass (`test_reformat_codex_branch_uses_user_id_and_accumulates_zero_cost`)
- `api_generate_mermaid`: sin cambios -> pass (sin diff en el endpoint; decisión en Decisions)
- Usage: `cumulative_usage` con `"codex_quota_requests": 0`; `_update_usage` acumula `getattr(usage_meta, "quota_requests", 0)` y usa `cost_source` (`chatgpt_quota` → coste 0); `_accumulate_review_usage` admite `CodexUsage` -> pass (quota==4 en pipeline E2E, quota==1 en review, total_cost 0.0)
- `backend/pricing.py`: `"gpt-5.6-luna"` con los cuatro precios a `0.0` -> pass
- Errores de agente codex → try/except por parte existentes → `part_failed` + SSE con mensaje UX tipado sin stack; `_format_and_finalize_part`/`_failed_part_ids` intactos -> pass (`test_codex_rate_limit_in_part_emits_part_failed_with_quota_message`)
- Tests: `test_main_helpers_v2.py` ampliado (resolución codex) + `test_codex_pipeline.py` nuevo (fake T02 + auth_client-like) -> pass (comando del brief: 83 passed)

## Files Changed
- `main.py` - modificado; wiring del proveedor codex (imports de variantes codex + `CODEX_MODEL` + errores tipados, Literal/constante, `_resolve_explainer_model`, `CODEX_LINK_REQUIRED_ERROR_MESSAGE`, `_process_project` completo, `_format_and_finalize_part`, `_accumulate_review_usage`, `api_process_project`, `api_part_review`, `api_reformat_project`). Nota: el fichero contenía ya los cambios no commiteados de T01-T06/T08/T09; solo toqué las regiones del brief.
- `backend/pricing.py` - modificado; entrada `"gpt-5.6-luna"` con precios 0.0.
- `tests/backend/test_codex_pipeline.py` - creado; 24 tests: pre-checks (incluida matriz requires_gemini_key 4×3), pipeline E2E codex (estados/partes/usage/posicionales), fallback YouTube→Gemini, `part_failed` por `CodexRateLimitError`, review/reformat por rama codex, smoke de agentes codex reales contra el fake app-server de T02.
- `tests/backend/test_main_helpers_v2.py` - modificado (aditivo); clase `TestCodexResolution` (3 tests).

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| main.py | `ExplainerProvider` Literal | +`"codex"` |
| main.py | `EXPLAINER_PROVIDER_CODEX` | nueva constante `"codex"` |
| main.py | `_resolve_explainer_model` | rama codex → `CODEX_MODEL` |
| main.py | `CODEX_LINK_REQUIRED_ERROR_MESSAGE` | nueva constante (mensaje congelado del vínculo) |
| main.py | `_process_project` | flags `use_codex_explainer`; modelos por fase → `CODEX_MODEL`; fallback YouTube resetea codex; `requires_gemini_key` nueva fórmula; carga de key Mistral para codex+pdf; `cumulative_usage["codex_quota_requests"]`; `_update_usage` con `cost_source`/`quota_requests`; ramas codex en classifier/segmentador/explainer/subparte (corrutinas directas)/recorrido/resources; error tipado del explainer en el dict de fallo; `use_codex` en el formatter task |
| main.py | `_format_and_finalize_part` | parámetro `use_codex: bool = False` + rama `format_explainer_content_codex(user_id, ...)`; flujo de fallo/éxito intacto |
| main.py | `_accumulate_review_usage` | acumula `quota_requests` (0 para no-codex) |
| main.py | `api_process_project` | `requires_gemini_key = provider in (GEMINI, OPENROUTER) or youtube`; pre-checks codex: vínculo `linked` → 400, Mistral para PDF → 400 |
| main.py | `api_part_review` | rama `provider == codex` (modelo de config o `CODEX_MODEL`, gate de vínculo, `run_review_codex` await directo); `CodexRateLimitError`→429, `CodexAuthError`→400, `CodexError`→502 |
| main.py | `api_reformat_project` | `use_codex`; formatter codex con `user_id`; acumulación de usage también con coste 0 |
| backend/pricing.py | `PRICING["gpt-5.6-luna"]` | entrada nueva, 4 precios a 0.0 |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py tests/backend/test_main_helpers.py tests/backend/test_main_helpers_v2.py`
  Result: pass — 83 passed (comando exacto del brief)
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py -q` (suite backend completa)
  Result: pass — 563 passed, 3 skipped, 0 failed

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_main_helpers_v2.py tests/backend/test_codex_pipeline.py -q` → `AttributeError: module 'main' has no attribute 'CODEX_MODEL'` y 22 fallos del pipeline: 422 (provider `"codex"` fuera del Literal), `AttributeError` al parchear `main.run_*_codex` (nombres inexistentes), 400 con mensaje Gemini en vez del mensaje de vínculo, "Proveedor de explainer no soportado: codex".
- GREEN: mismo comando tras implementar → 57 passed; luego el comando del brief → 83 passed; suite completa → 563 passed.

## Read Ledger
Planned reads:
- `plans/chatgpt-codex-auth/task-T07-brief.md` — autoridad de la tarea
- `plans/chatgpt-codex-auth/global-constraints.md` (§Pipeline wiring, §Codex client and errors, §Link endpoints) — reglas exactas
- `plans/chatgpt-codex-auth/context-map.md` — orientación del bundle
- `main.py` regiones del brief (154-241, 2138-2437, 2650-2810, 3324-3522, 2112-2135, 3923-4071, 4074-4225, 4315-4469, 4228-4312) — verificado; los números eran read-hints (fichero con cambios T01-T06 ya aplicados)
- `plans/chatgpt-codex-auth/plan.md` (Cross-task interfaces, evidence path) — firmas congeladas y expectativas de T07

Extra reads:
- `backend/agents/*_codex.py` (firmas posicionales de las 9 variantes) — para mapear los argumentos de las llamadas del pipeline
- `backend/codex_client.py` (jerarquía `CodexError`, `CodexUsage`, mensajes congelados) — manejo de errores review y usage
- `backend/supabase_data.py` (`get_user_provider_connection`, `PROVIDER_CODEX`) — gates de vínculo
- `backend/codex_app_server.py` (resolvers de env perezosos, `codex_manager`) — seguridad del import eager de agentes en main.py
- `backend/pricing.py` (`calculate_cost`) — entrada 0.0 y riesgo R3 del brief
- `tests/backend/fake_codex_app_server.py` + `fixtures_codex/` — escenarios disponibles (límite: un único `FAKE_CODEX_TURN_OUTPUT_FILE` por proceso)
- `tests/backend/conftest.py` (`auth_client` → "user-123", no válido para el gestor codex) — motivo del fixture local UUID en test_codex_pipeline.py
- `tests/backend/test_codex_agents_core.py` / `test_codex_agents_family.py` — patrón de env del singleton y `_script_turns`
- `tests/backend/test_part_status_honesty.py` — harness de `_process_project` con agentes mockeados
- `tests/backend/test_codex_env_lazy.py` — estabilización del env compartido de la suite (hazard de `CODEX_HOME_ROOT` en colección)
- `tests/backend/test_codex_link_endpoints.py` — patrón de fixture auth con UUID
- `backend/agents/formatter.py` (`_build_formatter_usage_summary`) — shape del `formatter_usage` codex (input/output/total/cost)

Pack gaps:
- Ninguno. (El fake app-server solo puede servir un payload de turno por proceso; el E2E de pipeline usa agentes codex mockeados y el smoke test ejercita agentes reales contra el fake, que es lo que el fixture permite — sin editar el fake read-only.)

## Decisions
- **Errores por parte de codex**: se reutiliza el mecanismo existente (`asyncio.gather(return_exceptions=True)` + `_format_and_finalize_part`); solo en la rama codex, cuando la llamada única del explainer falla, el dict de fallo lleva `str(la excepción tipada)` (mensaje UX congelado, sin stack) en lugar del genérico "All explainer calls failed" (que se conserva para gemini/openrouter/deepseek). `_format_and_finalize_part`/`_failed_part_ids` quedan intactos.
- **api_generate_mermaid sin cambios** (criterio del brief): usa la key DeepSeek de plataforma; el esquema visual no consume cuota ChatGPT en v1. Decisión documentada, no aplicada en silencio.
- **api_reformat_project sin gate de vínculo**: global-constraints solo exige gates en `/process` y review; un vínculo muerto hace que el error tipado del formatter caiga en el `gather(return_exceptions=True)` existente (parte saltada + warning), sin bloquear el reformat.
- **PDF + codex**: el pipeline carga la key Mistral (solo para OCR; sin keys ds/or/tavily) y el pre-check de la API la exige con mensaje análogo al de DeepSeek. La rama classifier codex exige OCR Mistral (mismo patrón que DS).
- **Uso**: `_update_usage` honra `cost_source="chatgpt_quota"` (coste 0 + fuente honesta en el log) y acumula `quota_requests` para cualquier usage_meta (0 para no-codex). `_accumulate_review_usage` acumula `quota_requests` igual (0 para no-codex; la entrada de pricing a 0.0 cubre el fallback `calculate_cost`).
- **Hazard de env de la suite (pre-existente)**: los ficheros de test codex asignan `CODEX_HOME_ROOT` a nivel de módulo en colección; el último en colección pisa el home que `test_codex_app_server.py` asevera contra su propia constante (reproducible con T02+T06 solos, sin T07). Apliqué en `test_codex_pipeline.py` el patrón de estabilización de `test_codex_env_lazy.py` (re-afirmar `_TEST_HOME_ROOT` de T02 si está en `sys.modules`) para no romper T02 en la suite completa.
- **Fixture auth**: `auth_client` de conftest devuelve "user-123", que el gestor codex rechaza (UUID estricto); el fichero de tests define un fixture local `codex_auth_client` con UUID, mismo patrón que `test_codex_link_endpoints.py`.

## Concerns / Follow-ups
- El E2E del pipeline codex se prueba sobre fuente web (evita OCR Mistral real); la rama PDF (classifier + OCR canónico) queda cableada y cubierta por el pre-check de Mistral y por los tests de T05/T06 de los agentes, pero sin E2E de pipeline PDF. Si el orquestador quiere cobertura E2E PDF, requeriría un fake de Mistral OCR (fuera del alcance de T07 y del fake read-only).
- El hazard de `CODEX_HOME_ROOT` entre ficheros de test codex (T02 vs T05/T06/T07) es estructural: cualquier fichero de test codex nuevo coleccionado después de `test_codex_app_server.py` debe re-aplicar la estabilización. No es un defecto de T07 (se reproduce sin T07), pero merece nota en la review del bundle.
- `api_reformat_project` sin gate de vínculo: si el vínculo caducó, el reformat responde ok con partes no formateadas (comportamiento honesto por partes, consistente con los errores de agente existentes). Alternativa (gate 400) no estaba en el contrato.

## Remediation History
None for the initial implementation.

## Remediation Round 1
Review: `plans/chatgpt-codex-auth/task-T07-review.md` — finding `RC-01` (same-task).

### Status
addressed

### Delta
- `backend/agents/formatter.py` (`format_explainer_content_codex`): el resumen
  `formatter_usage` ahora expone `quota_requests` = suma de
  `getattr(usage, "quota_requests", 0)` sobre los usages exitosos de cada campo
  (1 por turno Codex; los turnos paralelos quedan contados). Sin coste USD
  añadido (`calculate_cost` de `gpt-5.6-luna` sigue a 0.0). Los resúmenes de
  gemini/openrouter/deepseek no cambian de forma (la clave solo se añade en la
  variante codex; los callers leen con `.get(..., 0)`).
- `main.py` `_process_project` (agregación del formatter, ~4387-4422): nueva
  `total_fmt_quota` acumulada desde `formatter_usage.quota_requests` de cada
  parte; la condición pasa a `total_fmt_cost > 0 or total_fmt_quota > 0` y
  dentro se suma UNA sola vez `codex_quota_requests` a `cumulative_usage`
  (tras esperar a todos los formatters; sin doble conteo), persistiendo y
  emitiendo `usage_update`; `formatter_quota_requests` añadido al log extra.
- `main.py` `api_reformat_project` (agregación del formatter, ~4745-4786):
  `total_fmt_quota` acumulada igual; dentro del bloque `total_fmt_cost > 0 or
  use_codex` se suma una sola vez a `project_usage["codex_quota_requests"]`
  solo si `total_fmt_quota > 0` (no introduce la clave a 0 en proyectos
  no-codex). Coste USD intacto.
- `tests/backend/test_codex_pipeline.py`: nuevo `TestFormatterCodexQuotaSummary`
  (formatter con 2 turnos en paralelo → `quota_requests == 2`, coste 0); el
  fake del pipeline E2E devuelve `quota_requests: 2` y la aserción pasa de
  `== 4` a `== 6` (4 agentes + 2 turnos del formatter); el test de reformat
  devuelve `quota_requests: 2` y asevera `== 6` (4 previa + 2 nuevas).

### Tests
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q`
  → `3 failed, 22 passed` — `KeyError: 'quota_requests'` en el resumen del
  formatter; `codex_quota_requests == 4` en vez de 6 en el pipeline E2E y en
  el reformat (peticiones nuevas no acumuladas).
- GREEN: mismo comando → `25 passed in 1.21s`.
- Regresión: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`
  → `564 passed, 3 skipped` (563 previos + 1 test nuevo), 0 failed.

### Concerns
None. El conteo de turnos fallidos no es posible desde el resumen (el fallo de
campo conserva el texto original y no produce `CodexUsage`); el contrato de
`_format_text_codex` ya advierte del fallo en el log y el conteo honesto cubre
las peticiones que realmente reportan uso, que es lo que exige el finding.
