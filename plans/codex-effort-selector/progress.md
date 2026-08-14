# Progress: Selector de thinking/effort — Codex (GPT-5.6 Luna)

Planning: engine=opencode | model=opencode-go/deepseek-v4-pro | effort=max
Baseline: 87b6a29

| Task | Status | Implementer | Owner | Brief | Report | Review | Notes |
|---|---|---|---|---|---|---|---|
| T01 | pending | task-implementer-bdd | - | task-T01-brief.md | task-T01-report.md | required | Backend: allowlist+wire+variantes+pipeline+persistencia |
| T02 | pending | task-implementer-bdd | - | task-T02-brief.md | task-T02-report.md | skipped-not-needed | Frontend: sub-panel effort, persist/restore, payload |

Final review: pending - plans/codex-effort-selector/final-review.md

## Decision ledger

- 2026-08-14 (planning): 2 tareas en paralelo (wave 0). T01 backend vs T02 frontend: archivos
  disjuntos; contrato cross-task congelado en global-constraints.md ANTES del dispatch.
- 2026-08-14 (planning): el fake app-server NO se edita — ya acepta params arbitrarios en
  `turn/start` y traza cada request a `FAKE_CODEX_TRACE_FILE`; la observación de effort en
  tests sale de la traza.
- 2026-08-14 (planning): `ReviewRequest` NO gana `codex_effort` — el effort de un proyecto es
  el persistido en `explainer_config`; proyectos viejos degradan a `medium` (default honesto).
- 2026-08-14 (planning): el pipeline resuelve SIEMPRE un nivel concreto (default `medium`) y
  lo envía explícito en cada `turn/start`; `call_codex_chat(effort=None)` omite el campo
  (contrato de llamadores directos intacto).
- 2026-08-14 (planning): `_resolve_explainer_model` no cambia; la validación de effort es
  inline en `api_process_project` vía `normalize_codex_effort` (solo provider codex).
- 2026-08-14 (planning): persistir `"codex_effort"` en `explainer_config` siempre (None si el
  provider no es codex, patrón de `openrouter_model`).
- 2026-08-14 (T01 remediation, RC-01 — changed-contract): se unifica la semántica con el
  contrato congelado (`global-constraints.md` §Allowlist y default y `plan.md` §1:
  `None/'' → medium`). `normalize_codex_effort` degrada `None` Y `""` (vacío) a `medium`;
  SOLO strings NO vacíos fuera de la allowlist → `ValueError` → 400 en
  `api_process_project`. La implementación inicial trataba `""` como 400 (decisión no
  registrada); se corrige código, tests y la redacción del brief (`task-T01-brief.md`:
  `""` fuera de la lista de 400) y de la verificación de `plan.md` para que brief y plan
  coincidan. Sin re-secuenciación: T02 (frontend) nunca emite `""` (restaura inválidos →
  medium) y su contrato de espejo ya era `None/'' → medium`.
- 2026-08-14 (T01 remediation, RC-02 — same-task): `call_codex_chat` valida localmente
  `effort` con `normalize_codex_effort` cuando no es None (defensa en profundidad para
  llamadores directos, incl. tests/live gate): un valor fuera de la allowlist es un error
  de programación del llamador (`ValueError` antes de tocar el server), nunca un 400 de
  API; `None` preserva el campo ausente en el wire. El pipeline ya valida en
  `api_process_project`.

**Approval:** instrucción directa del usuario (2026-08-14): "que en el selector de luna se pueda
configurar también el thinking basándonos en los niveles que luna acepta. UI/UX perfecta" —
aprobación en pie registrada; diseño derivado de la receta (niveles low/medium/high/xhigh/max,
default medium). Sin re-pregunta.

## Cierre
- T01 backend: APPROVE (RC-01/RC-02 remediados; 622 passed, 3 skipped).
- T02 frontend: DONE (347 passed vitest).
- Final review: APPROVE sin findings (622 backend + 347 frontend + smoke xhigh 4 passed + git diff --check OK).
- R-EFFORT-WIRE: **CERRADO 2026-08-14** — live gate real con CODEX_LIVE_EFFORT=xhigh: el binario
  real (codex 0.145.0) aceptó turn/start.effort y el turno streaming completo funcionó
  (texto='ok', usage real). Evidencia: /tmp/opencode/codex_live.log.
