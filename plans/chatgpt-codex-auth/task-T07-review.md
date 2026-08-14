# Review: task/T07

## Verdict
APPROVE

## Functional Verification
- Ejecutado `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q`: **25 passed**.
- Ejecutado `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`: **564 passed, 3 skipped** (10 warnings deprecación de Supabase).
- Revisados el brief, report, constraints de wiring/errores, plan §7/interfaces, diff aislado disponible y los 25 tests de `test_codex_pipeline.py`.

## Spec Compliance
- Cumplidos literal/constante/modelo fijo, ausencia de campos nuevos en `ProcessProjectRequest`, fallback YouTube→Gemini, regla de key Gemini, gates Codex/Mistral, ramas async directas con `user_id`, review/reformat, errores tipados, pricing 0, y preservación de Mermaid.
- Los tests cubren proyecto Codex, fallback YouTube, matriz 4×3 de keys, pre-checks, review/reformat, cuota acumulada y `part_failed` por rate limit.
- El alcance funcional observado coincide con T07; no se detectó regresión en la suite backend.

## Code Quality
- La implementación sigue los contratos posicionales y mantiene el threading existente para los proveedores no Codex.
- RC-01 verificado como resuelto: el formatter conserva las peticiones de cuota de todos sus turnos y ambos callers las agregan una sola vez sin coste USD.

## Named Risk Checks
- Literal y resolución: `ExplainerProvider` contiene `codex`; `_resolve_explainer_model` devuelve `CODEX_MODEL` sin atender parámetros extra.
- Pipeline/keys: `_process_project` resetea `use_codex_explainer` al fallback YouTube y la fórmula de `requires_gemini_key` es `gemini|openrouter|youtube`; Codex no carga Gemini/DeepSeek/OpenRouter/Tavily.
- Async/identidad: las ramas Codex inspeccionadas usan `await`/`gather` directo y pasan `user_id` en la posición de key; las variantes validadas reciben `validator_user_id=user_id`.
- Errores: review mapea rate limit a 429 y auth a 400; el fallo de parte conserva mensaje UX y no stack. Verificado por tests y por `_format_and_finalize_part`.
- Coste: pricing `gpt-5.6-luna` es 0.0 y `_update_usage`/review respetan `cost_source="chatgpt_quota"`; RC-01 queda resuelto sin coste USD adicional.
- Mermaid: no observé hunk de cambio funcional en `api_generate_mermaid` dentro del diff revisado.

## Required Changes
- `RC-01` | Scope: **same-task** | Owner hint: T07 / `format_explainer_content_codex`, `_process_project`, `api_reformat_project` | `backend/agents/formatter.py:827-835`, `main.py:4387-4416`, `main.py:4745-4786` | Problem original: el resumen del formatter descartaba `quota_requests`, subcontando el uso Codex. | Required change: conservar/exponer las peticiones de todos los turnos, agregarlas una sola vez en procesamiento y reformat, sin coste USD, y cubrirlo con tests multi-turno. | Status: **resolved**

## Remediation History

### Round 1
- Implementer report/diff: `plans/chatgpt-codex-auth/task-T07-report.md`, Remediation Round 1; cambios en `backend/agents/formatter.py`, `main.py` y `tests/backend/test_codex_pipeline.py`.
- IDs checked: `RC-01`.
- Result: **resolved**. El formatter suma `quota_requests` de los usages exitosos (incluidos turnos paralelos); `_process_project` y `api_reformat_project` suman `total_fmt_quota` una sola vez y mantienen coste USD 0. Los tests nuevos verifican 2 turnos y acumulación final 6.

## Evidence
- `plans/chatgpt-codex-auth/task-T07-brief.md`, criterios 1–8.
- `plans/chatgpt-codex-auth/global-constraints.md`, §Codex client and errors y §Pipeline wiring (líneas 168–201).
- `plans/chatgpt-codex-auth/plan.md`, §7 y Cross-task interfaces.
- `main.py:2641-2670`, `main.py:2965-3004`, `main.py:4690-4771`.
- `backend/agents/formatter.py:827-835`: el resumen Codex expone `quota_requests` como suma de todos los usages.
- `main.py:4387-4416`, `main.py:4745-4786`: agregación única de cuota del formatter; la rama no-Codex solo se activa con coste positivo y no crea la clave por cuota a 0.
- `tests/backend/test_codex_pipeline.py:731-759`, `:703-728`, `:472`: test multi-turno del formatter y aserciones de procesamiento/reformat con cuota final 6.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q`: **25 passed**.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q`: **564 passed, 3 skipped**.

## Limitations
- No se ejecutó un flujo live contra el binario Codex real ni un E2E PDF; ambos quedan fuera de la verificación local declarada y ya están documentados como riesgos del bundle.
