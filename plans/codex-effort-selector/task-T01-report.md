# Task T01 Report

## Status
DONE

## Outcome
El backend del selector de effort de `gpt-5.6-luna` queda implementado de punta a punta:
allowlist y normalización en `backend/codex_model_routing.py` (`CODEX_EFFORT_LEVELS =
("low","medium","high","xhigh","max")`, `CODEX_DEFAULT_EFFORT = "medium"`,
`normalize_codex_effort`), `effort` en el wire de `turn/start` (clave exacta `"effort"`, solo
si no es None; `thread/start` sin cambios: nunca lleva `effort` ni `config.model_reasoning_effort`),
keyword `effort: str | None = None` al final de `call_codex_chat` y de las 10 variantes públicas
codex (explicador, subparte, validadas, validador, run_with, segmentador, clasificador, recorrido,
recursos, review, formatter) con forwarding obligatorio interno
(`_call_codex_json_with_pdf_fallback`, `_CodexExplainerConversation`,
`run_with_codex_explainer_validation` → `check_explainer_validation_codex`, y el gather del
formatter), campo `ProcessProjectRequest.codex_effort: str | None = None` validado SOLO para
provider codex (400 con el mensaje congelado; resto de providers → ignorado, persistido `null`),
threading de `codex_effort` en `_process_project` (default medium, último parámetro posicional) y
`_format_and_finalize_part` (keyword tras `use_codex`) hasta todos los call sites codex,
persistencia en `explainer_config.codex_effort`, y resolución defensiva en `api_part_review` /
`api_reformat_project` (→ medium + warning ante config ausente/corrupta; nunca 400).
`ReviewRequest` sin cambios. `tests/backend/fake_codex_app_server.py` NO se editó: el wire se
verifica parseando `FAKE_CODEX_TRACE_FILE`.

Suite completa en verde: `610 passed, 3 skipped` (3 skipped = marcador `integration`, requieren
credenciales reales; igual que en el baseline).

## Acceptance Criteria
- `call_codex_chat(effort="xhigh")` → `turn/start` con `params.effort == "xhigh"` en la traza;
  sin `effort` → ningún `turn/start` con clave `effort`; `thread/start` nunca lleva effort ni
  `config.model_reasoning_effort` -> pass
  (`TestEffortWire` en `test_codex_client.py`, 4 tests, traza real del fake).
- El turno correctivo del reintento JSON (mismo thread) conserva el mismo effort -> pass
  (`test_corrective_retry_turn_keeps_same_effort`: `["high", "high"]` en la traza).
- `/process` codex con `codex_effort="xhigh"` → 200, persiste `explainer_config.codex_effort ==
  "xhigh"` y threading a todas las fases -> pass (`TestEffortCodexProcess` + 
  `TestEffortCodexPipelineThreading`; el wire por fase se cubre a nivel de agente: cada variante
  pública invocada con `effort="low"` deja `"effort":"low"` en TODOS sus `turn/start` de la traza,
  `TestEffortForwarding` en `test_codex_agents_core.py` y `test_codex_agents_family.py`).
- Sin `codex_effort` (o `null`) → todo el pipeline usa `"medium"` y persiste `medium` -> pass
  (`test_codex_effort_absent_defaults_to_medium`, `test_codex_effort_null_defaults_to_medium`,
  `test_default_effort_medium_when_not_passed`).
- Valores no soportados (`none`, `ultra`, `auto`, `extra_high`, `minimal`, `""`) con provider
  codex → HTTP 400 con el mensaje congelado -> pass (parametrizado: `detail == "Nivel de
  razonamiento de Codex no soportado: '<valor>'. Usa uno de: low, medium, high, xhigh, max."`).
- Provider gemini/openrouter/deepseek con `codex_effort` presente → ignorado, persistido `null`,
  sin 400 -> pass (`test_non_codex_provider_ignores_codex_effort`, parametrizado 3 providers).
- `api_part_review` y `api_reformat_project` en proyectos codex usan el effort de
  `explainer_config`; proyecto viejo sin campo → `medium` sin error; config corrupto → `medium` +
  warning -> pass (`test_review_codex_uses_persisted_effort`, `test_review_codex_corrupt_config_effort_degrades_to_medium`,
  `test_reformat_codex_uses_persisted_effort`, `test_reformat_codex_corrupt_config_effort_degrades_to_medium`,
  y asserts de `effort == "medium"` en los tests preexistentes de review/reformat sin config).
- Suites existentes verdes: `python scripts/run_pytest.py` completo -> pass (610 passed,
  3 skipped; 0 failures).

## Files Changed
- `backend/codex_model_routing.py` - modified; `CODEX_EFFORT_LEVELS`, `CODEX_DEFAULT_EFFORT`,
  `normalize_codex_effort` (único validador de autoridad).
- `backend/codex_client.py` - modified; `_turn_params` con `effort` condicional, `call_codex_chat`
  con `effort: str | None = None` al final + docstring; docstring de módulo actualizado.
- `backend/agents/explainer_codex.py` - modified; `effort` en 6 variantes públicas + forwarding en
  `_call_codex_json_with_pdf_fallback`, `_CodexExplainerConversation`, `check_explainer_validation_codex`,
  `run_with_codex_explainer_validation`, y los 2 constructores de conversación de las validadas.
- `backend/agents/segmentador.py` - modified; `run_segmentador_codex` + `effort` (keyword final,
  tras `correction`) y forwarding al cliente.
- `backend/agents/page_classifier.py` - modified; `run_page_classifier_codex` + `effort`.
- `backend/agents/recorrido.py` - modified; `run_recorrido_codex` + `effort`.
- `backend/agents/resources.py` - modified; `run_resources_codex` + `effort`.
- `backend/agents/review.py` - modified; `run_review_codex` + `effort` (keyword final tras `model`)
  y forwarding en el lambda de reintentos.
- `backend/agents/formatter.py` - modified; `_format_text_codex` + `effort`, `format_explainer_content_codex`
  + `effort` y forwarding en el list comprehension del gather.
- `main.py` - modified; `ProcessProjectRequest.codex_effort`, validación 400 en
  `api_process_project` (solo codex), persistencia `explainer_config.codex_effort`,
  `_process_project` + `codex_effort` (último param posicional) con threading a clasificador,
  segmentador (×2), explainer/subpart (4 ramas), recorrido, resources y `_format_and_finalize_part`,
  `_format_and_finalize_part` + `codex_effort` keyword (tras `use_codex`) y forwarding al formatter,
  resolución defensiva en `api_part_review` (rama codex) y `api_reformat_project` (rama codex).
- `tests/backend/test_codex_client.py` - modified; `TestEffortWire` (4 tests de traza).
- `tests/backend/test_codex_agents_core.py` - modified; helpers de traza + `TestEffortForwarding`
  (6 tests: explainer, subpart, validated chain explainer+validator, validador, segmentador, clasificador).
- `tests/backend/test_codex_agents_family.py` - modified; helpers de traza + `TestEffortForwarding`
  (4 tests: recorrido, resources, review, formatter con 5 turnos paralelos).
- `tests/backend/test_codex_pipeline.py` - modified; fakes con `effort` + registro, assert de
  config con `codex_effort`, `TestEffortCodexProcess` (HTTP /process), `TestEffortCodexPipelineThreading`,
  y tests de effort en review/reformat (persistido/corrupto → medium).
- `tests/backend/test_api.py` - modified; los 4 stubs `_fake_process` de `TestProcessProject`
  ganan `codex_effort="medium"` como último parámetro posicional (dependencia del threading de
  `_process_project`; sin cambio de comportamiento de los tests).

No tocados (verificados por `git diff`): `frontend/**`, `tests/frontend/**` (modificados por T02
antes de esta sesión), `tests/backend/fake_codex_app_server.py` (read-only), `android/**`,
`backend/auth.py`, `backend/pricing.py`, `api_generate_mermaid`, fallback YouTube→Gemini,
`ReviewRequest`/`MermaidRequest`, código de gemini/openrouter/deepseek.

## Symbol Change Summary
| File | Symbol / contract | Change |
|---|---|---|
| `backend/codex_model_routing.py` | `CODEX_EFFORT_LEVELS = ("low","medium","high","xhigh","max")` | Nueva constante |
| `backend/codex_model_routing.py` | `CODEX_DEFAULT_EFFORT = "medium"` | Nueva constante |
| `backend/codex_model_routing.py` | `normalize_codex_effort(value: str \| None) -> str` | Nueva: None → medium; no-allowlist (incl. `""`) → `ValueError` con el mensaje congelado |
| `backend/codex_client.py` | `_turn_params(*, thread_id, text, model, effort=None)` | Añade `"effort"` solo si no es None |
| `backend/codex_client.py` | `call_codex_chat(..., timeout=..., effort: str \| None = None)` | Firma congelada + kw final; docstring documenta la adición |
| `backend/agents/explainer_codex.py` | `run_explainer_codex(..., target_language="es-ES", *, effort=None)` | Firma congelada + kw final + forwarding |
| `backend/agents/explainer_codex.py` | `run_subpart_explainer_codex(..., *, effort=None)` | Idem |
| `backend/agents/explainer_codex.py` | `run_explainer_codex_validated(..., target_language="es-ES", *, effort=None)` | Idem |
| `backend/agents/explainer_codex.py` | `run_subpart_explainer_codex_validated(..., *, effort=None)` | Idem |
| `backend/agents/explainer_codex.py` | `check_explainer_validation_codex(..., model=CODEX_MODEL_AUXILIARY, *, effort=None)` | Idem |
| `backend/agents/explainer_codex.py` | `run_with_codex_explainer_validation(*, ..., validation_context=None, effort=None)` | Idem; forwarding a `check_explainer_validation_codex` |
| `backend/agents/explainer_codex.py` | `_call_codex_json_with_pdf_fallback(*, ..., effort=None)` | Forwarding interno obligatorio |
| `backend/agents/explainer_codex.py` | `_CodexExplainerConversation.__init__(*, ..., operation_label, effort=None)` | Forwarding interno obligatorio |
| `backend/agents/segmentador.py` | `run_segmentador_codex(..., *, conversation=None, correction=None, effort=None)` | Firma congelada + kw final + forwarding |
| `backend/agents/page_classifier.py` | `run_page_classifier_codex(..., model=CODEX_MODEL, *, effort=None)` | Idem |
| `backend/agents/recorrido.py` | `run_recorrido_codex(..., target_language="es-ES", *, effort=None)` | Idem |
| `backend/agents/resources.py` | `run_resources_codex(..., *, effort=None)` | Idem |
| `backend/agents/review.py` | `run_review_codex(..., model=CODEX_MODEL, *, effort=None)` | Idem |
| `backend/agents/formatter.py` | `_format_text_codex(..., target_language="es-ES", *, effort=None)` | Idem |
| `backend/agents/formatter.py` | `format_explainer_content_codex(..., *, effort=None)` | Idem; forwarding en el comprehension del gather |
| `main.py` | `ProcessProjectRequest.codex_effort: str \| None = None` | Campo nuevo (resto intactos) |
| `main.py` | `api_process_project` | Validación `normalize_codex_effort` solo para codex (try/except ValueError → 400 congelado); `explainer_config.codex_effort` persistido; `background_tasks.add_task(..., codex_effort)` posicional |
| `main.py` | `_process_project(..., openrouter_provider_routing=None, codex_effort=CODEX_DEFAULT_EFFORT)` | Param final; threading `effort=codex_effort` a clasificador, segmentador ×2, 4 ramas explainer/subpart, recorrido, resources y task del formatter |
| `main.py` | `_format_and_finalize_part(..., use_codex=False, codex_effort=CODEX_DEFAULT_EFFORT)` | Param keyword tras `use_codex`; forwarding a `format_explainer_content_codex` |
| `main.py` | `api_part_review` (rama codex) | Resolución defensiva desde `explainer_config` (except → medium + warning); `effort=codex_effort` en `run_review_codex` |
| `main.py` | `api_reformat_project` (rama codex) | Resolución defensiva desde `explainer_config`; `effort=codex_effort` en `format_explainer_content_codex` |

## Tests
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q -k "Effort"`
  Result: pass — `4 passed` (RED previo: 3 failed por `TypeError: call_codex_chat() got an unexpected keyword argument 'effort'`; el 4º, ausencia de clave, ya pasaba como regresión).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_core.py tests/backend/test_codex_agents_family.py -q -k "Effort"`
  Result: pass — `10 passed` (RED previo: 10 failed por TypeError en el kw `effort`).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q`
  Result: pass — `43 passed` (incluye los fakes actualizados y los nuevos TestEffort*).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py tests/backend/test_codex_pipeline.py tests/backend/test_codex_agents_core.py tests/backend/test_codex_agents_family.py -q`
  Result: pass — `101 passed` (mínimo del brief).
- Command: `.venv-win/Scripts/python.exe scripts/run_pytest.py -q`
  Result: pass — `610 passed, 3 skipped` (3 skipped = marcador `integration`; 0 failures).
  Fallo intermedio detectado y corregido: 4 tests de `test_api.py::TestProcessProject` (stubs
  `_fake_process` con 7 posicionales) tras añadir el 8º arg; actualizados los 4 stubs con
  `codex_effort="medium"` → `8 passed`.

## TDD Evidence
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q -k "Effort"`
  → `3 failed, 1 passed`; fallos por `TypeError: call_codex_chat() got an unexpected keyword
  argument 'effort'` — el wire aún no aceptaba `effort`.
- RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_core.py tests/backend/test_codex_agents_family.py -q -k "Effort"`
  → `10 failed` por TypeError en el kw `effort` de las variantes.
- GREEN: mismos comandos tras implementar → `4 passed` y `10 passed` (traza real del fake con
  `"effort"` en todos los `turn/start`).
- GREEN pipeline: `43 passed`; suite completa `610 passed, 3 skipped`.

## Read Ledger
Planned reads:
- `plans/codex-effort-selector/task-T01-brief.md` (completo, 154 líneas)
- `plans/codex-effort-selector/global-constraints.md` (completo, 175 líneas)
- `plans/codex-effort-selector/plan.md` §Chosen approach 1-5 (líneas 45-164)
- `plans/codex-effort-selector/integration-effort.md` (completo, 83 líneas)
- `backend/codex_model_routing.py` (completo, 14 líneas)
- `backend/codex_client.py` 296-322 (`_thread_start_params`/`_turn_params`) y 539-672 (`call_codex_chat`)
- `backend/agents/explainer_codex.py` (completo, 591 líneas)
- `backend/agents/{segmentador,page_classifier,recorrido,resources,review,formatter}.py` (variantes codex, 12 defs)
- `main.py` 206-255, 2482-2589, 2673-2769, 3240-3309, 3390-3449, 3990-4279, 4320-4389, 4630-4989, 5055-5263
- `tests/backend/fake_codex_app_server.py` 50-178 y 300-396 (`FAKE_CODEX_TRACE_FILE`, `_trace_received`)
- `tests/backend/test_codex_client.py` (1-739), `test_codex_agents_core.py` (593), `test_codex_agents_family.py` (427), `test_codex_pipeline.py` (862)
- `tests/backend/conftest.py` (fixtures `client`/`auth_client`)

Extra reads:
- `tests/backend/test_codex_app_server.py` 545-583 - patrón de parseo de la traza del fake (JSONL, `json.loads` por línea); usado en los helpers `_turn_start_efforts`.
- `tests/backend/test_api.py` 278-494 - stubs `_fake_process` de `TestProcessProject` que rompían con el 8º arg posicional; motivo del fallo de la suite completa y del ajuste de 4 stubs.
- `main.py` 128-142 - imports de agentes y `codex_model_routing` (aliases `run_explainer_codex_validated as run_explainer_codex`), para firmar correctamente los call sites del pipeline.

Pack gaps:
- None.

## Decisions
- **`normalize_codex_effort("")` lanza `ValueError`** (no devuelve medium). El brief es
  internamente inconsistente: la firma congelada comenta "None/'' → medium", pero el Criterio de
  Aceptación y la sección Tests exigen (en dos sitios) `""` → HTTP 400 con el mensaje congelado.
  Solo `None` (campo ausente) degrada a medium. Consecuencia coherente: en review/reformat un
  config con `""` cae en el `except ValueError` → medium + warning (R-OLD-PROJECTS, nunca 400),
  y el único validador de autoridad sigue siendo `normalize_codex_effort` (sin lógica extra en
  main.py). El mensaje congelado vive en el `ValueError` de la función (una sola fuente) y
  `api_process_project` lo propaga con `HTTPException(400, detail=str(exc))`; el valor crudo
  aparece SOLO dentro del mensaje congelado (nunca en logs — los warning de review/reformat no
  incluyen el valor).
- **Evidencia del wire a nivel pipeline compuesta, no directa**: la traza real de `turn/start`
  con effort se verifica en el cliente y en cada variante de agente contra el fake real
  (`FAKE_CODEX_TRACE_FILE`); el test de pipeline usa agentes grabadores deterministas para probar
  el threading de `codex_effort` en TODOS los call sites de `_process_project`. Un E2E completo
  con agentes reales contra el fake sería no-determinista: el gather concurrente
  (explainer+recorrido+resources) intercala turnos que comparten un único fichero de salida
  scripted (el hook de reescritura por parse no puede serializarlo sin editar el fake, que es
  read-only). La cadena de evidencia conjunta cubre el criterio "todos los turn/start de todas las
  fases llevan effort en la traza" sin relajar ninguna fase.
- **`_turn_params` firma**: `effort` como kw con default None; la clave `"effort"` solo si no es
  None (el pipeline siempre pasa un nivel concreto; los llamadores directos pueden omitirlo).
  `_thread_start_params` intacto (receta §Gotchas 1-2: sin `effort` ni `config.model_reasoning_effort`).
- **`_process_project` recibe `codex_effort` posicional** desde el background task (contrato del
  constraint); default `CODEX_DEFAULT_EFFORT` para llamadas directas/tests.
- **Tests de `test_api.py`**: actualizar los 4 stubs `_fake_process` (añadir `codex_effort="medium"`)
  es una dependencia precisa del cambio de firma de `_process_project` (el brief no los lista,
  pero "Suites existentes verdes" lo exige); sin cambio de aserciones ni de comportamiento.

## Concerns / Follow-ups
- R-EFFORT-WIRE (del brief, UNVERIFIED en live): la forma del campo sigue estrictamente la receta
  verificada (`turn/start.effort`; sin `thread/start.effort`, sin `reasoning_effort`); la
  precedencia real thread-default vs turn-override con un app-server autenticado sigue sin
  verificarse en live (fuera del alcance de T01, sin red real).
- El fake app-server NO se editó; toda la observación del wire se hizo vía
  `FAKE_CODEX_TRACE_FILE`.
- `explainer_config` gana la clave `codex_effort` (None para providers no-codex); ningún campo
  existente cambió de nombre ni forma; `ReviewRequest`/`MermaidRequest` intactos.
- No hay logs de valores de effort: el 400 incluye el valor crudo solo dentro del mensaje
  congelado; los warning defensivos de review/reformat no lo incluyen.

## Remediation History

### Round 1 - plans/codex-effort-selector/task-T01-review.md
- Finding IDs: `RC-01`, `RC-02`
- Status: addressed
- Delta:
  - `backend/codex_model_routing.py` - `normalize_codex_effort`: `""` (vacío) degrada a
    `medium` igual que `None` (contrato congelado `None/'' → medium`); solo strings NO
    vacíos fuera de la allowlist → `ValueError`. Docstring actualizado.
  - `backend/codex_client.py` - `call_codex_chat` valida localmente con
    `normalize_codex_effort` cuando `effort is not None` (RC-02, defensa en profundidad
    para llamadores directos): `ValueError` de programación ANTES de tocar el server;
    `None` preserva el campo ausente en el wire. Docstring de módulo, de la función y
    sección `Raises` actualizados.
  - `tests/backend/test_codex_client.py` - `""` eliminado de la lista de 400; NUEVOS:
    `TestEffortWire::test_empty_effort_normalizes_to_medium_on_wire` (traza real del
    fake: `["medium"]`), `TestEffortValidation` (7 unit tests de `normalize_codex_effort`
    incl. `""` → medium y no-vacío fuera de allowlist → `ValueError`, y
    `test_call_codex_chat_rejects_unsupported_effort`).
  - `tests/backend/test_codex_pipeline.py` - `""` eliminado del parametrize de 400;
    NUEVO `test_codex_effort_empty_string_defaults_to_medium` (`""` → 200, persistido
    `medium`, threaded al pipeline).
  - `plans/codex-effort-selector/task-T01-brief.md` - redacción corregida: `""` fuera de
    la lista de valores → 400 (Criterio de Aceptación y sección Tests); ahora explicita
    `""` → 200/medium. La firma de Interfaces ya decía `None/'' → medium`.
  - `plans/codex-effort-selector/plan.md` - verificación (línea "valor no soportado"): se
    elimina "vacío" de la lista de 400; `""` pasa a "sin selección o `""` → medium",
    coherente con §1.
  - `plans/codex-effort-selector/progress.md` - decisión de unificación registrada en el
    decision ledger (RC-01: semántica única con el contrato; RC-02: validación local en
    el cliente).
- Tests:
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q -k "Effort"` → `3 failed, 13 passed` (`[''] == ['medium']` en el wire; `ValueError` en `""`; llamada directa con `ultra` llega al server sin `ValueError`).
  - RED: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_pipeline.py -q -k "codex_effort"` → `1 failed, 11 passed` (`assert 400 == 200` para `""`).
  - GREEN: `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_client.py -q -k "Effort"` → `16 passed`; `test_codex_pipeline.py -q -k "codex_effort"` → `12 passed`.
  - GREEN: `.venv-win/Scripts/python.exe scripts/run_pytest.py -q` → `622 passed, 3 skipped` (3 skipped = marcador `integration`; 0 failures).
- Concerns: la degradación de un config con `""` en review/reformat ya no pasa por el
  `except ValueError` (normaliza a medium directamente, sin warning) — semántica
  coherente con el contrato unificado (`""` ≡ ausente); el test de config corrupto sigue
  cubriendo el camino del warning con `"ultra"`. Sin cambios fuera del scope (backend
  codex + tests + artifacts del bundle).
