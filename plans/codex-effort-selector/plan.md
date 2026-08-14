# Plan: Selector de thinking/effort para Codex (GPT-5.6 Luna)

## Objective and user outcome

Permitir que, en la card "ChatGPT (Codex)" del selector de proveedor, el usuario configure el
nivel de razonamiento (thinking) de Luna con **exactamente** los niveles que `gpt-5.6-luna`
acepta — `low`, `medium`, `high`, `xhigh`, `max` (default `medium`) — y que ese nivel se aplique
de forma consistente a **todas** las fases Codex de un proyecto (segmentador, classifier,
explainer+validador, recorrido, resources, review y formatter), incluidas las operaciones
on-demand posteriores (review/reformat), que re-leen el effort persistido del proyecto. El
proveedor se presenta como "Luna" coloquialmente en la UI.

Resultado observable: el usuario elige un nivel en el sub-panel de la card Codex, ve una
descripción en español por nivel (velocidad/calidad/consumo de cuota) con el default marcado
como recomendado y una nota de que el nivel afecta a todas las fases; al procesar, el backend
envía `effort` en cada `turn/start` y persiste la elección para review/reformat. Nunca se
exponen niveles que Luna no admite (`none`, `minimal`, `ultra`, `extra_high`, `auto`).

## Source of truth and settled scope

- Contrato verificado del wire: `plans/codex-effort-selector/integration-effort.md` (se
  conservan sus etiquetas **VERIFIED**/**per-docs**/**UNVERIFIED**). Puntos que mandan:
  niveles exactos `low/medium/high/xhigh/max`, default `medium`; `turn/start` acepta `effort`;
  `thread/start` NO tiene `effort` top-level (y el default de thread vía
  `config.model_reasoning_effort` es innecesario porque nuestro cliente crea un thread por
  llamada); el protocolo acepta strings arbitrarias → allowlist client-side obligatoria;
  `model/list` es la autoridad runtime.
- Mapa del repo: `plans/codex-effort-selector/context-map.md`; base:
  `plans/chatgpt-codex-auth/context-map.md`.
- Invariantes del bundle previo que NO se rompen: `plans/chatgpt-codex-auth/global-constraints.md`
  (firmas posicionales congeladas de las variantes codex, errores tipados `Codex*`, `CodexUsage`,
  wire STREAMING FR-01, fixture fake read-only para tareas paralelas) y su `plan.md` §Cross-task
  interfaces y §7 (métrica de uso).
- Producto ya fijado (no reabrir): niveles SOLO `low/medium/high/xhigh/max`; default `medium`;
  sin `none`/`auto`; un único selector global en la card de Codex (persistencia
  `explainer.modelSelector.v1`, campo nuevo `codexEffort`) aplicado a todas las fases codex;
  persistencia en `explainer_config` (`{"provider":"codex","model":"gpt-5.6-luna",
  "codex_effort":...}`) para review/reformat; UI como sub-panel incremental del lenguaje visual
  existente (sin skill de frontend); el proveedor se llama "Luna" coloquialmente.

Fuera de alcance: `android/`, proveedores existentes (gemini/openrouter/deepseek intactos),
mermaid (sigue con key DeepSeek de plataforma), fallback YouTube→Gemini, auth, `getReviewProviderConfig`
(sin campo nuevo en `ReviewRequest`), y cualquier selector de modelo Codex.

## Chosen approach

### 1. Allowlist y default (una fuente por runtime)

- Backend, `backend/codex_model_routing.py`: `CODEX_EFFORT_LEVELS = ("low","medium","high",
  "xhigh","max")`, `CODEX_DEFAULT_EFFORT = "medium"`, y
  `normalize_codex_effort(value: str | None) -> str` (None/'' → medium; no-allowlist →
  `ValueError`). Es el único validador backend.
- Frontend, `frontend/js/landing.js`: `export const CODEX_EFFORT_LEVELS = [...]` y
  `CODEX_DEFAULT_EFFORT = 'medium'` (espejo, sin importar backend). La UI solo ofrece radios de
  la allowlist; el backend es la autoridad de validación.

### 2. Wire: `effort` en `turn/start`, nunca en `thread/start`

`call_codex_chat` gana `effort: str | None = None` (keyword, al final de la firma keyword-only,
tras `timeout`); `_turn_params` incluye `"effort"` **solo si no es None**. `_thread_start_params`
no cambia (decisión de la receta + producto: thread por llamada → override por turno es
suficiente). El pipeline **siempre** resuelve un nivel concreto (default medium) y lo pasa
explícito: en producción todo turno codex lleva `effort` en el wire. Los llamadores directos de
`call_codex_chat` pueden omitirlo (None → campo ausente), preservando el contrato actual.

### 3. Variantes de agentes: keyword `effort` al final (orden posicional intacto)

Todas las variantes públicas codex ganan `effort: str | None = None` como **último parámetro
keyword** — el orden posicional congelado en `chatgpt-codex-auth` no cambia y los call sites de
`main.py` siguen llamando posicionalmente. Forwarding interno (4 helpers):
`_call_codex_json_with_pdf_fallback`, `_CodexExplainerConversation.__init__`,
`check_explainer_validation_codex`, `run_with_codex_explainer_validation` (explainer_codex.py) y
`_format_text_codex` (formatter.py). Firmas exactas en global-constraints.md.

### 4. Request, persistencia y threading en main.py

- `ProcessProjectRequest` gana `codex_effort: str | None = None`. En `api_process_project`, si
  `explainer_provider == "codex"`: `normalize_codex_effort(payload.codex_effort)` en try/except
  `ValueError` → **400** con el mensaje congelado. Para otros providers el campo se ignora
  (queda `None`). `_resolve_explainer_model` NO cambia (su contrato es resolución de modelo).
- `_process_project` gana `codex_effort: str = CODEX_DEFAULT_EFFORT` al final (tras
  `openrouter_provider_routing`); el background task de `api_process_project` lo pasa. Cada call
  site codex gana `effort=codex_effort`: segmentador (×2), classifier, explainer/subpart
  (región 3995-4125), recorrido, resources, y `_format_and_finalize_part` (que gana
  `codex_effort: str = CODEX_DEFAULT_EFFORT` keyword y lo pasa al formatter codex).
- `explainer_config` persistido gana `"codex_effort": codex_effort` (None si el provider no es
  codex, patrón de `openrouter_model`).
- `api_part_review` (rama codex) y `api_reformat_project` (rama codex): resuelven
  `codex_effort` desde `explainer_config` de forma **defensiva** (try/except → medium + warning;
  los proyectos viejos sin campo → medium). Se pasa como kw a `run_review_codex` /
  `format_explainer_content_codex`. `ReviewRequest` NO gana campos (decisión: el effort del
  proyecto es el persistido; sin campo → default honesto medium).

### 5. Fake app-server: sin edición (observación vía traza existente)

El fake ya acepta params arbitrarios en `turn/start` (solo lee `threadId`) y traza **cada
request recibido** a `FAKE_CODEX_TRACE_FILE` (JSONL, params completos). Los tests verifican el
wire leyendo la traza. Cero cambios en el fixture (preserva su estatus read-only entre tareas).

### 6. Frontend: sub-panel de effort en la card Codex

Dentro de `#codex-model-panel` se añade el bloque "Nivel de razonamiento" con un grupo de 5
radios (`#codex-effort-group`, ids `codex-effort-{low|medium|high|xhigh|max}`) reutilizando las
clases existentes `.provider-grid`/`.provider-card`; cada nivel con título y descripción
española congelada (velocidad/calidad/cuota), medium marcado "Recomendado" (checked por
defecto en HTML), y una nota "se aplica a todas las fases". Estado
`currentCodexEffort` + persist/restore con fallback (campo ausente/inválido → medium) en
`explainer.modelSelector.v1` (clave `codexEffort`), payload `/process` con `codex_effort`
(solo provider codex), sync en `syncExplainerProviderUI` y listeners idempotentes. Copia UX
congelada en global-constraints.md.

## Task graph and waves

```text
T01 (backend) ──┐
                ├── final review (tras ambos)
T02 (frontend) ─┘
```

| Wave | Tasks | Mode | Gate / reason |
|---|---|---|---|
| 0 | T01, T02 | **parallel** | Archivos disjuntos (`backend/**`+`tests/backend/**` vs `frontend/**`+`tests/frontend/**`). El único contrato compartido es el cross-task congelado en `global-constraints.md` ANTES del dispatch: nombre de campo `codex_effort`/`codexEffort`, allowlist, default, mensaje de 400 y copia UX |
| 1 | — | final review | El revisor corre las suites completas sobre el árbol integrado y valida el contrato cross-task |

### Parallel-safety reasoning

- T01 es propietario exclusivo de `backend/**` y `tests/backend/**`; T02 de `frontend/**` y
  `tests/frontend/**`; `frontend/index.html`. Sin solapamiento de archivos.
- El fixture `tests/backend/fake_codex_app_server.py` **no se edita en ninguna tarea** (la
  observación de effort sale de `FAKE_CODEX_TRACE_FILE`); se mantiene su convención read-only.
- Los contratos compartidos (allowlist, nombres de campo, default, copia) están congelados en
  `global-constraints.md` antes de despachar: cada tarea puede implementarse y probarse contra
  su espejo local del contrato sin esperar a la otra.
- La única superficie que tocan ambos semánticamente es la forma JSON
  `{"codex_effort": "low|medium|high|xhigh|max"}`; el revisor final cruza ambos lados con un
  test de integración si hay evidencia insuficiente.

## Task inventory

| ID | Outcome | Brief | Review |
|---|---|---|---|
| T01 | Backend: allowlist+normalización, `effort` en cliente y variantes, request+validación 400, threading, persistencia `explainer_config`, review/reformat, tests | `task-T01-brief.md` | required: contrato wire/API consumido por frontend y pipeline |
| T02 | Frontend: sub-panel de effort en la card Codex, persist/restore con fallback, payload, copia UX, tests vitest | `task-T02-brief.md` | final review sufficient |

## Review Gates

Revisión obligatoria: T01 (frontera API + wire-format + threading transversal; cualquier cambio
aquí re-secuenciaría T02). T02 cierra con final review. Cambios a un contrato congelado exigen
re-secuenciar y registrarse en el decision ledger de `progress.md`, nunca editarse en silencio.

## Verification strategy

### Claim

Un usuario autenticado con la cuenta ChatGPT vinculada elige `xhigh` en la card de Codex,
procesa un proyecto contra el fake app-server y **cada** `turn/start` de todas las fases codex
lleva `"effort":"xhigh"`; `explainer_config` persiste `codex_effort:"xhigh"` y review/reformat
del mismo proyecto lo re-usan; un valor no soportado (`none`, `ultra`, `auto`) produce
400 con mensaje claro; sin selección o con `""` (vacío, indistinguible de ausente), todo
el pipeline usa `medium`; el selector recuerda la
elección entre sesiones y degrada a `medium` si el storage tiene un valor corrupto o ausente.

### Automated evidence path

```text
python scripts/run_pytest.py        # backend completo (T01: obligatorio; suite de codex + resto)
npx vitest run                      # frontend completo (T02: obligatorio)
npm run test:all                    # opcional en final review (backend + frontend + smoke)
```

Cobertura exigida por tarea (ver briefs):

- T01: `call_codex_chat(effort="xhigh")` → traza con `"effort":"xhigh"` en `turn/start`;
  sin effort → traza sin clave `effort`; turno correctivo conserva el effort; cada variante
  pública acepta `effort=` y lo forwardea (traza); `/process` con provider codex:
  `codex_effort="xhigh"` → 200 + `explainer_config.codex_effort=="xhigh"` + traza con xhigh;
  `codex_effort` inválido → 400 mensaje congelado; ausente → medium persistido y en traza;
  provider gemini + `codex_effort` → ignorado (persistido null); review y reformat resuelven
  effort de `explainer_config` (incl. proyecto viejo sin campo → medium); suites existentes
  verdes (regresión del contrato posicional).
- T02: `persistModelSelector` escribe `codexEffort`; restore con campo ausente → medium, con
  valor válido → ese valor, con valor inválido → medium; test existente "no extra codex
  fields" actualizado; DOM (`renderLandingDom`): medium checked por defecto, click en otro
  nivel persiste, payload de `/process` incluye `codex_effort` solo para codex; nota
  "todas las fases" visible en el panel; suites frontend verdes.

### Evidence interpretation

- El fake + traza demuestran el wire-format que el backend emite; la compatibilidad real de
  `turn/start.effort` con el binario sigue pendiente del live gate del bundle anterior
  (riesgo R-EFFORT-WIRE).
- La validación del backend es la única autoridad; los tests de frontend prueban que la UI
  nunca puede emitir un valor fuera de la allowlist.

## Named risks

1. **R-EFFORT-WIRE — `turn/start.effort` UNVERIFIED en live** (receta §Verification Status):
   forma verificada en source, no contra binario vivo. Mitigación: allowlist estricta, default
   medium, traza que pinea el wire, y el live gate existente (`test_codex_live_login.py`) como
   validación pre-release.
2. **R-OLD-PROJECTS — proyectos previos a la feature**: `explainer_config` sin `codex_effort` →
   review/reformat usan `medium` (default honesto, degradación defensiva con warning). No se
   añade `codex_effort` a `ReviewRequest`: el effort de un proyecto es el persistido; el body
   fallback de review solo resuelve provider/modelo de proyectos aún más viejos.
3. **R-DEFAULT-DRIFT — `model/list` runtime podría diferir del catálogo pineado**: la receta
   fija la allowlist de Luna en source; si un release la cambia, el síntoma es un 400 honesto
   o un nivel degradado en el servidor, nunca un envío silencioso de un valor inventado.
4. **R-COPY — copia UX congelada**: cambiar los textos por nivel es una decisión de producto;
   están congelados en global-constraints para que index.html y tests no divergen.
