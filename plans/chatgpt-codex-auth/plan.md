# Plan: Proveedor Codex — "ChatGPT" con vinculación OAuth (device code) y cuota del plan

## Objective and user outcome

Añadir, sin quitar ni degradar los proveedores actuales (gemini, openrouter, deepseek), un cuarto
proveedor de explainer: el usuario vincula su cuenta de ChatGPT mediante device-code OAuth (nunca
una API key) y el backend ejecuta el CLI `codex app-server` como subproceso usando la cuota Codex
incluida en su plan de ChatGPT, con el modelo `gpt-5.6-luna`. Alcance exclusivamente web; la app
Android es de solo lectura y queda intacta.

El resultado permite que una persona:

1. en Ajustes, inicie el vínculo, vea URL + código de dispositivo, los complete en chatgpt.com y
   observe el estado en vivo (pendiente / vinculada / error) con cancelación y desvinculación;
2. seleccione "ChatGPT (Codex)" como motor del explainer sin pegar claves, con validación honesta
   por tipo de fuente;
3. procese PDF, web y YouTube con reglas claras (YouTube cae a Gemini automáticamente, igual que
   hoy; PDF requiere la key de Mistral para OCR, igual que DeepSeek directo);
4. use review y reformat con el mismo proveedor Codex, y siga generando esquemas Mermaid por la
   vía existente (key DeepSeek de plataforma, sin cambios);
5. vea un uso honesto de su cuota (número de peticiones a ChatGPT, sin coste USD inventado) y
   mensajes de error accionables cuando la cuota se agota, el vínculo caduca o el servicio está
   saturado;
6. sobreviva a los cold starts de Koyeb: el vínculo se conserva cifrado en Supabase y los
   subprocesos se recrean bajo demanda, sin pedir al usuario que vuelva a vincular.

## Source of truth and settled scope

- Mapa del repo: `plans/chatgpt-codex-auth/context-map.md` (riesgos R1-R7, unknowns U1-U4).
- Contrato de integración verificado: `plans/chatgpt-codex-auth/integration-codex-appserver.md`;
  se conservan sus etiquetas **VERIFIED**, **per-docs** y **UNVERIFIED**.
- Invariantes ejecutables por todas las tareas: `plans/chatgpt-codex-auth/global-constraints.md`.
- Producto ya fijado (no reabrir): alcance web-only, proveedor adicional, device-code OAuth sin
  callback, modelo `gpt-5.6-luna`, cuota ChatGPT sin coste USD.

Fuera de alcance: cambios en `android/`, en los proveedores actuales (no se elimina ni cambia
ningún flujo existente), transporte WebSocket/experimental del app-server, herramientas
(web-search) del app-server en v1, y cualquier API-key login de ChatGPT (vía de facturación
distinta, prohibida por la receta).

## Chosen approach

### 1. Runtime del contenedor: binario standalone sin Node

El Dockerfile descarga el paquete de plataforma **`@openai/codex-linux-x64@0.147.0`** (dist-tag
VERIFIED en la receta) como tarball desde `registry.npmjs.org` con `curl`, verifica su **sha256
pineado** y extrae el binario nativo a `/usr/local/bin/codex`. Los binarios son builds musl
standalone: no requieren Node ni Rust en runtime (`python:3.11-slim` se mantiene como base). Se
añade `curl ca-certificates` a `apt-get install`. `koyeb.yaml` no cambia funcionalmente
(nano/512MB/scale-to-zero se mantienen); se documenta el presupuesto de memoria. T08 es dueño.

### 2. Un app-server long-lived por tenant, spawn perezoso, evicción por inactividad

**Decisión:** un proceso `codex app-server --stdio` por `user_id`, creado bajo demanda en el
primer uso y terminado por inactividad (TTL) o shutdown; nunca un proceso compartido entre
cuentas (la receta lo prohíbe por fuga de credenciales/threads) y nunca un spawn por request
(el coste de arranque ~1-2 s por llamada se pagaría decenas de veces por proyecto).

- `CODEX_HOME = /tmp/codex/<user_id>` con permisos **0700**; el `user_id` (UUID del JWT) se
  valida con regex antes de construir el path. `auth.json` se restaura desde Supabase **antes**
  del spawn y se re-sincroniza (cifrado) al evacuar/apagar.
- Transporte: JSONL newline-delimited por stdin/stdout (`--stdio`), una reader-task por proceso
  que resuelve respuestas por `id` y despacha notificaciones; stderr va a un fichero acotado en
  `CODEX_HOME`, nunca a los logs de la app.
- Concurrencia (512 MB): semáforo global `CODEX_MAX_PROCESSES=3` procesos; espera con timeout
  (`CODEX_SPAWN_WAIT_SECONDS=60`) y error tipado `CodexBusyError` honesto si no hay hueco.
  Por proceso, semáforo de 5 peticiones concurrentes (= `MAX_CONCURRENT_PARTS`). Evicción
  LRU-idle (`CODEX_IDLE_TTL_SECONDS=600`).

### 3. Persistencia del vínculo: tabla nueva `user_provider_connections`

**Decisión:** tabla nueva, **no** reutilizar `user_api_keys`.

**Por qué:** las credenciales de ChatGPT son un blob JSON opaco (`auth.json` del app-server, que
contiene el refresh token y se regenera automáticamente) con una máquina de estados
(`none/pending/linked/failed`), un `login_id` de device-code pendiente y metadatos de plan. Meter
eso en `encrypted_api_key` (string) rompería la semántica de `get_user_api_key_status` y el
contrato BYOK; una tabla propia permite además validar el estado del vínculo sin tocar el flujo
de keys. El blob se cifra con el patrón existente de `backend/crypto.py`
(`encrypt_user_api_key`/`decrypt_user_api_key`, Fernet con clave derivada por usuario). Migración
`supabase/migrations/20260814120000_user_provider_connections.sql` con RLS por fila (el backend
accede con service_role, igual que el resto).

Esto resuelve R4 y el scale-to-zero (R2): el contenedor puede morir sin perder el vínculo; un
cold start re-crea `CODEX_HOME` y restaura `auth.json` descifrado. Si la restauración fallara o
el token no refrescase, el estado honesto es "vínculo no disponible; vuelve a vincular", nunca
un fallo silencioso.

### 4. Vinculación device-code en la UI web

- `POST /api/settings/codex-link/start` → `account/login/start` tipo `chatgptDeviceCode` en el
  app-server del tenant → la UI muestra `verificationUrl` + `userCode` (con copiar/abrir);
  `loginId` se guarda en la fila pendiente.
- El app-server emite `account/login/completed` de forma asíncrona; el handler del manager
  persiste `auth.json` cifrado (status `linked`) y captura `planType` vía `account/read`
  (best-effort, normalizado sin allowlist de planes).
- `GET /api/settings/codex-link/status` (la UI pollea hasta ~10 min), `POST
  .../codex-link/cancel` (`account/login/cancel`), `DELETE /api/settings/codex-link`
  (`account/logout` + borrado de fila + evicción del proceso; idempotente).
- Cold start a mitad del vínculo: el proceso nuevo no tiene login en vuelo; tras un grace se
  marca `failed` con mensaje honesto y la UI ofrece reintentar.

### 5. Cliente Codex y contrato de agentes

`backend/codex_client.py` envuelve el app-server con el mismo contrato semántico que
`backend/deepseek_client.py`, pero **asíncrono** (el manager vive en el event loop): `async
call_codex_chat(*, user_id, messages, system_prompt, model, response_format, temperature, ...)`
hace `await codex_manager.acquire(user_id)` y `await app.request(...)`, abre `thread/start` +
`turn/start` con override de modelo y espera la **notificación `turn/completed`** (el turno es
streaming: la response de `turn/start` solo acepta el turno; el texto final llega en
`item/completed` del agentMessage y el usage en `thread/tokenUsage/updated` — reconciliado con
source `08e482e2`/`rust-v0.147.0-alpha.9`, receta §Turn lifecycle verification); con
`response_format="json_object"` parsea y reintenta conversacionalmente (misma política de
reintentos de payload que DeepSeek). Las variantes de agentes Codex son corrutinas `async` que se
esperan **directamente** en el pipeline (no vía `asyncio.to_thread`), manteniendo el orden
posicional de parámetros de las `_ds`. Produce
`CodexUsage` con atributos estilo Gemini + `cost_usd=0.0`, `cost_source="chatgpt_quota"` y
`quota_requests=1`. Errores tipados: `CodexError`, `CodexRateLimitError` (UsageLimitExceeded →
mensaje UX "has agotado la cuota por ahora"), `CodexAuthError`, `CodexBusyError`,
`CodexTimeoutError`. Sin tools en v1.

`backend/codex_model_routing.py` fija `CODEX_MODEL = "gpt-5.6-luna"` como modelo único para
todas las fases (la receta: no inferir disponibilidad por nombre de marketing; `model/list` es
autoridad en runtime y el override se envía por turno; no se ofrece selector de modelo).

### 6. Cobertura por fases — decisiones de degradación honesta

| Fase | Decisión | Justificación |
|---|---|---|
| Segmentador, page_classifier | **Codex** (`run_segmentador_codex`, `run_page_classifier_codex`) | Proveedor autocontenido: no exige key de Gemini, a diferencia de OpenRouter |
| Explainer (completo/subparte, validados) | **Codex** (espejo exacto de `explainer_deepseek.py`, validador de completitud también vía Codex) | Contrato `(data, usage)` idéntico; retry conversacional preserva el prefijo |
| Recorrido, resources, review, formatter | **Codex** (`run_recorrido_codex`, `run_resources_codex` sin búsqueda web en v1, `run_review_codex`, `format_explainer_content_codex`) | Mismo esquema que variantes `_ds`; resources trabaja con conocimiento del modelo (riesgo documentado) |
| YouTube | **Cae a Gemini automáticamente** (patrón existente 2235-2248) | Igual que openrouter/deepseek; requiere key de Gemini |
| PDF | **OCR de Mistral** (mismo camino que DeepSeek directo: key de Mistral + caché OCR) | Reutiliza el pipeline ya probado; sin él no hay OCR en v1 |
| Mermaid | **Sin cambios**: sigue usando la key DeepSeek hardcodeada de plataforma | No factura cuota del usuario; degradarlo añadiría fricción sin beneficio |
| Review / Reformat | **Extendidos a Codex** (ramas nuevas en `api_part_review` / `api_reformat_project`) | Leen `explainer_config`; el usuario espera coherencia de proveedor |
| Android | **Intacto** | La app es de solo lectura |

Regla de keys resultante: `requires_gemini_key = explainer_provider in (gemini, openrouter) or
source_type == "youtube"`. Codex solo exige: vínculo `linked` (+ key Mistral para PDF). Es el
primer proveedor plenamente autocontenido.

### 7. Métrica de uso honesta (R3)

La cuota de ChatGPT no produce coste USD ni necesariamente conteos de tokens expuestos por el
app-server. Decisión: `CodexUsage` expone conteos de tokens **solo si el turno los reporta**
(parse defensivo; ceros en caso contrario), `cost_usd=0.0` y `quota_requests=1` por turno.
`_update_usage` acepta `cost_source` (nuevo atributo; `"chatgpt_quota"`) y acumula
`codex_quota_requests` en `cumulative_usage`; `PRICING` gana la entrada `gpt-5.6-luna` a 0.0
como fallback de cálculo. La UI de uso muestra "Cuota ChatGPT: N peticiones" cuando procede y
ningún coste USD inventado.

### 8. Threading en el pipeline (sin tocar firmas ajenas)

Los agentes Codex reciben el `user_id` en la posición donde los agentes textuales reciben
`api_key` (`text_provider_api_key = user_id`), conservando el orden posicional de argumentos.
La única diferencia mecánica es que las variantes Codex son corrutinas que se `await`ean
directamente en los `asyncio.gather`/tareas del pipeline, en lugar del wrapper
`asyncio.to_thread(_call_agent_with_optional_validation_context, ...)` que usan las `_ds`. El
`ExplainerProvider` literal gana `"codex"` y `_resolve_explainer_model` devuelve `CODEX_MODEL`
fijo.

### 9. Frontend: card + panel + flujo de vínculo

Nueva `.provider-card` "ChatGPT (Codex)" (sub: "GPT-5.6 Luna — incluida en tu plan ChatGPT"),
sub-panel con el modelo fijo en modo informativo (sin radios), estado del vínculo inline
(punto de estado + botón "Vincular cuenta ChatGPT" / "Vinculada · plan X" / "Desvincular").
Ajustes gana la sección Codex con el flujo device-code completo (URL + código copiable, botón
cancelar, polling 3 s hasta 10 min, estados pending/linked/failed/expired con copia honesta).
`validProviders` incluye `codex`; persistencia `explainer.modelSelector.v1` intacta (sin campos
nuevos: el modelo es fijo); restauración con fallback por falta de vínculo; validación por tipo
de fuente y keys. No aplica la skill de frontend: es una extensión incremental del lenguaje
visual existente (cards/provider-grid ya desplegados), no una superficie nueva.

## Cross-task interfaces

Los nombres siguientes son contratos congelados (detalle exacto en `global-constraints.md`):

```python
# backend/supabase_data.py (T01)
PROVIDER_CODEX = "codex"
def get_user_provider_connection(user_id: str) -> dict | None
def upsert_user_provider_connection(user_id, *, status, encrypted_credentials=None,
                                    login_id=None, plan_type=None, last_error=None) -> None
def delete_user_provider_connection(user_id: str) -> bool
# get_user_api_key_status gana: has_codex_link, codex_status, codex_plan_type, codex_updated_at

# backend/codex_app_server.py (T02)
class CodexAppServerError(Exception): ...
class CodexSpawnError(CodexAppServerError): ...
class CodexRequestError(CodexAppServerError): ...   # .code/.message/.data
class CodexAppServer:
    async def request(method, params=None, timeout=...) -> Any
class CodexAppServerManager:
    async def acquire(user_id) -> CodexAppServer
    async def evict(user_id) -> None
    async def shutdown() -> None
    def add_notification_handler(method, handler) -> None   # handler(user_id, params) -> Awaitable
codex_manager = CodexAppServerManager()

# backend/codex_client.py (T03) — cliente ASÍNCRONO (se espera directo, no en to_thread)
class CodexError(Exception): ...
class CodexRateLimitError(CodexError): ...
class CodexAuthError(CodexError): ...
class CodexBusyError(CodexError): ...
class CodexTimeoutError(CodexError): ...
class CodexUsage:  # prompt_token_count, candidates_token_count, thoughts_token_count,
                   # total_token_count, tool_use_prompt_token_count, cost_usd=0.0,
                   # cost_source="chatgpt_quota", quota_requests=1
async def call_codex_chat(*, user_id, messages, system_prompt, model=CODEX_MODEL,
                          response_format="json_object", temperature=..., timeout=...) -> tuple[Any, CodexUsage]

# backend/codex_model_routing.py (T03)
CODEX_MODEL = "gpt-5.6-luna"
CODEX_MODEL_AUXILIARY = CODEX_MODEL
CODEX_EXPLAINER_MODELS = frozenset({CODEX_MODEL})
```

Endpoints (T04):

```text
POST   /api/settings/codex-link/start   → {ok, verification_url, user_code, login_id, expires_in}
GET    /api/settings/codex-link/status  → {ok, codex_status: none|pending|linked|failed,
                                           codex_plan_type, last_error}
POST   /api/settings/codex-link/cancel  → {ok}
DELETE /api/settings/codex-link         → {ok}   (logout + borrado + evicción, idempotente)
```

Variantes de agentes (T05/T06) — **corrutinas async**, espejo posicional de las `_ds`:

```python
async def run_explainer_codex(source_path, identificacion, model=CODEX_MODEL,
                              mime_type="application/pdf", user_id="", pdf_cache_entry=None,
                              page_numbers=None, target_language="es-ES") -> tuple[dict, CodexUsage]
async def run_subpart_explainer_codex(...) -> tuple[dict, CodexUsage]
async def run_explainer_codex_validated(source_path, identificacion, model=CODEX_MODEL,
                                        mime_type="application/pdf", user_id="",
                                        validator_user_id="", pdf_cache_entry=None,
                                        page_numbers=None, validation_context=None,
                                        target_language="es-ES") -> tuple[dict, CodexUsage, list]
async def run_subpart_explainer_codex_validated(...) -> tuple[dict, CodexUsage, list]
async def run_with_codex_explainer_validation(...) -> tuple[dict, CodexUsage, list]
async def run_segmentador_codex(api_key, source_text, description, source_kind="pdf",
                                model=CODEX_MODEL, target_language="es-ES", *,
                                conversation=None, correction=None) -> tuple[dict, CodexUsage, list]
async def run_page_classifier_codex(api_key, source_text, total_pages,
                                    model=CODEX_MODEL) -> tuple[frozenset, CodexUsage, dict]
async def run_recorrido_codex(user_id, source_text, identificacion, model=CODEX_MODEL,
                              target_language="es-ES") -> tuple[dict, CodexUsage]
async def run_resources_codex(user_id, source_text, identificacion, model=CODEX_MODEL,
                              target_language="es-ES") -> tuple[dict, CodexUsage]
async def run_review_codex(user_id, explainer_content, part_title, target_language="es-ES",
                           model=CODEX_MODEL) -> tuple[dict, CodexUsage]
async def format_explainer_content_codex(user_id, explainer_data, target_language="es-ES") -> tuple[dict, dict]
```

T07 invoca estas corrutinas con `await`/`asyncio.gather` directo en los puntos del pipeline donde
las `_ds` se envuelven en `asyncio.to_thread`; el orden posicional de argumentos es idéntico.

## Task graph and waves

```text
T01 -> T02, T04
T02 -> T03, T04
T03 -> T05, T06
T05 -> T07
T06 -> T07
T04 -> T09
T01 -> T07, T09
T07 -> T10
T09 -> T10
```

| Wave | Tasks | Mode | Gate / reason |
|---|---|---|---|
| 0 | T01 | sequential | La tabla + funciones de almacenamiento son el contrato de datos de todos los demás |
| 1 | T02, T08 | parallel | Gestor de procesos (`backend/`) vs despliegue (`Dockerfile`/`koyeb.yaml`/`DEPLOY.md`): archivos disjuntos, sin contrato compartido mutable |
| 2 | T03, T04 | parallel | Cliente+routing vs endpoints de vínculo; ambos consumen la API congelada del manager (T02) y el fixture fake (T02); archivos disjuntos |
| 3 | T05, T06 | parallel | Variantes de agentes núcleo vs familia: archivos de agente disjuntos, contrato de `codex_client` congelado |
| 4 | T07, T09 | parallel | Wiring de pipeline (main.py/backend) vs frontend: archivos disjuntos; los contratos de endpoints y el literal `"codex"` ya están fijados |
| 5 | T10 | sequential | Verificación integrada completa + final review solo tras cerrar todas las piezas |

### Parallel-safety reasoning

- T01 es propietario de la migración, las constantes `PROVIDER_CODEX` y las funciones de
  almacenamiento antes de que nadie las consuma; ninguna tarea paralela puede editar
  `supabase_data.py` ni la migración.
- T02 es propietario de `backend/codex_app_server.py` y del fixture
  `tests/backend/fake_codex_app_server.py`. El fixture es **read-only** para el resto de tareas
  (los escenarios base cubren toda la superficie del protocolo; un escenario faltante se reporta
  al orquestador, no se edita en paralelo). El manager no muta durante las olas 2-4.
- T03 y T04 comparten la API congelada del manager pero ningún archivo: T03 crea
  `codex_client.py`/`codex_model_routing.py`; T04 edita solo `main.py` (región settings/lifespan)
  y sus tests.
- T05 y T06 tocan archivos de agente disjuntos (`explainer_codex.py` nuevo + `segmentador.py` +
  `page_classifier.py` vs `recorrido.py` + `resources.py` + `review.py` + `formatter.py`) y
  consumen `call_codex_chat`/`CodexUsage` sin modificarlos.
- T07 edita `main.py` (pipeline/on-demand/usage) y `pricing.py`; T09 edita `frontend/**`. Sin
  solapamiento de archivos; los contratos de endpoints (T04), el literal `"codex"` y los campos
  de status (T01) están congelados antes de la ola 4.
- T08 no comparte nada: imagen y docs de despliegue; puede correr en la ola 1.
- T10 es deliberadamente secuencial: ejecuta las suites completas sobre el árbol integrado y
  produce la evidencia final.

## Task inventory

| ID | Outcome | Brief | Review |
|---|---|---|---|
| T01 | Migración `user_provider_connections` + almacenamiento cifrado + campos de status | `task-T01-brief.md` | required: schema/seguridad |
| T02 | `CodexAppServerManager`: proceso por tenant, JSONL, aislamiento 0700, evicción, restauración de auth.json + fixture fake app-server | `task-T02-brief.md` | required: ciclo de credenciales/aislamiento |
| T03 | `codex_client.py` + `codex_model_routing.py`: cliente tipado, `CodexUsage`, retries conversacionales | `task-T03-brief.md` | required: contrato compartido por todos los agentes |
| T04 | Endpoints de vínculo device-code + shutdown hook + estado honesto de cold start | `task-T04-brief.md` | required: frontera OAuth |
| T05 | Variantes Codex: explainer (+validado), segmentador, page_classifier | `task-T05-brief.md` | required: contrato del explainer compartido por el pipeline |
| T06 | Variantes Codex: recorrido, resources, review, formatter | `task-T06-brief.md` | final review sufficient |
| T07 | Wiring del pipeline: literal, resolución, pre-checks, threading, review/reformat, usage | `task-T07-brief.md` | required: integración crítica |
| T08 | Dockerfile (binario pineado sin Node), koyeb.yaml, DEPLOY.md | `task-T08-brief.md` | final review sufficient |
| T09 | Frontend: card + panel + flujo de vínculo + validación + uso | `task-T09-brief.md` | final review sufficient |
| T10 | Verificación integrada end-to-end + evidencia final | `task-T10-brief.md` | final review sufficient (produce final-review.md) |

## Review Gates

Revisión obligatoria por tarea en: T01 (esquema/RLS/seguridad), T02 (ciclo de vida de
credenciales y aislamiento multi-tenant), T03 (contrato de cliente consumido por todos los
agentes), T04 (frontera OAuth/device-code), T05 (contrato del explainer que el pipeline
consume), T07 (integración crítica del pipeline). El resto cierra con final review. Una tarea
que necesite relajar un contrato congelado debe volver a secuenciarse, no editar el contrato en
silencio; los cambios autorizados se registran en el decision ledger de `progress.md`.

## Verification strategy

### Claim

Con un app-server falso que habla el JSON-RPC pineado, un usuario autenticado puede vincular su
cuenta (device-code), procesar un proyecto con `explainer_provider="codex"` de principio a fin
(segmentador → classifier → explainer → recorrido → resources → formatter), regenerar review,
reformatear, y recibir fallos de parte honestos cuando la cuota se agota o el proceso muere; el
vínculo sobrevive a un "cold start" simulado (evicción + re-spawn) sin que el usuario repita el
flujo OAuth. El contenedor construido contiene el binario pineado y arranca sin Node.

### Automated evidence path

```text
python scripts/run_pytest.py                        # backend completo (fixture auth_client + fake app-server)
npx vitest run                                      # frontend (landing/auth/state/storage)
npm run test:all                                    # backend + frontend (+ playwright smoke)
docker build -t explainer-codex-test . && docker run --rm explainer-codex-test codex --version   # T08 (si Docker está disponible en el entorno; si no, documentar not-verified)
```

Cobertura exigida por tarea (ver briefs):

- T01: CRUD de `user_provider_connections`, cifrado/descifrado round-trip, campos nuevos de
  `get_user_api_key_status`, migración idempotente (RLS + PK).
- T02: spawn con `CODEX_HOME` 0700, restauración atómica de `auth.json`, JSON-RPC concurrente
  por id, semáforos (5/3), evicción LRU, shutdown persistente, rechazo de `user_id` no-UUID,
  errores `CodexSpawnError`/`CodexRequestError`.
- T03: parseo de turno, retry conversacional ante JSON inválido, mapeo de errores tipados
  (UsageLimitExceeded → `CodexRateLimitError`), `CodexUsage` con y sin conteos reportados.
- T04: flujo device-code feliz (start → completed → linked + planType), cancel, delete
  idempotente, timeout de vínculo, cold-start pendiente → `failed`, 409/400/503 correctos.
- T05/T06: cada variante devuelve `(data, CodexUsage)` con validación `*_validated` y reintentos;
  fixtures deterministas sin credenciales reales.
- T07: proyecto completo con proveedor codex contra el fake (statuses y partes), fallback
  YouTube→Gemini, pre-checks (sin vínculo → 400 con mensaje; PDF sin Mistral → 400), review y
  reformat por rama codex, `codex_quota_requests` acumulado, `part_failed` por
  `CodexRateLimitError`.
- T09: `validProviders`, persist/restore con fallback por vínculo, mensajes de validación,
  estados de la UI del vínculo (factory `renderLandingDom`), display de uso de cuota.

### Live gate (documentada, no prometida)

`tests/test_codex_live_login.py` (marker `integration`, skip por defecto): start real →
completar device code manualmente → status linked → un turno real `gpt-5.6-luna` → logout.
Requiere credenciales de ChatGPT de un humano; se ejecuta fuera de CI y su resultado se registra
en `final-review.md`. Hasta entonces, los puntos UNVERIFIED de la receta (formato exacto de
parámetros JSON-RPC, campos de usage, `auth.json`) siguen siendo riesgo vivo, mitigado porque el
fake app-server pinea el wire-format que el código produce y el gate live lo valida antes de
release.

### Evidence interpretation

- El fake app-server demuestra el contrato que el backend emite y tolera, no el comportamiento
  real del binario; el gate live es la única prueba de compatibilidad real.
- Los tests de pipeline usan `auth_client` (overrides de auth), no GoTrue real.
- `docker build`/`codex --version` demuestra instalación pineada; el presupuesto de memoria real
  en nano requiere observación post-deploy (riesgo R-MEM).

## Named risks and approval gate

1. **R-PROTO — JSON-RPC del app-server solo parcialmente verificado:** la receta verificó el
   flujo device-code en código fuente y el ciclo de turno quedó **reconciliado** (FR-01): el
   turno es streaming por notificaciones (`turn/completed` + `item/completed` +
   `thread/tokenUsage/updated`), verificado en source `08e482e2`/`rust-v0.147.0-alpha.9`; no
   existen `turn/end`/`turn/poll`. Pendiente de live gate: los parámetros del request
   (`thread/start`/`turn/start`) y los campos reales de usage contra el binario en ejecución.
   Mitigación: el fake pinea el wire-format verificado, el gate live valida antes de release,
   y `account/rateLimits/read`/`model/list` son consultas advisory en v1.
2. **R-MEM — Presupuesto de 512 MB en nano:** Python+uvicorn (~200 MB) + 3× app-server podrían
   rozar el límite. Mitigación: caps por env (`CODEX_MAX_PROCESSES`), evicción idle agresiva,
   `CodexBusyError` honesto en vez de OOM; observación post-deploy documentada en DEPLOY.md.
3. **R-AUTHJSON — Formato interno de `auth.json` sin ejercicio live:** se trata como blob opaco
   cifrado con round-trip probado contra el fake; si una versión futura del CLI cambia el
   formato, el síntoma es "vínculo no disponible" tras cold start (UX honesta que pide
   re-vincular), nunca corrupción.
4. **R-USAGE — Campos de uso no garantizados:** la UI muestra peticiones de cuota (siempre
   exactas) y tokens solo si el turno los reporta; cero coste USD por decisión de producto.
5. **R-MODEL — Disponibilidad de `gpt-5.6-luna` por plan contradictoria en docs:** sin allowlist
   de planes; `UsageLimitExceeded`/respuestas del turno son la autoridad y su UX está diseñada.
6. **R-CONC — Un app-server por tenant con 5 peticiones concurrentes puede serializar turns
   internamente** (el servidor es agéntico): latencia mayor, no error; el semáforo y el timeout
   por petición acotan el impacto. Los threads quedan aislados por `CODEX_HOME` por diseño.
7. **R-COLD — Muerte del proceso a mitad de turno** (scale-to-zero): la parte falla con mensaje
   honesto (`part_failed` + SSE) y el proyecto se puede reprocesar; el vínculo no se pierde
   porque vive en Supabase.
8. **R-RESOURCES — Resources sin búsqueda web en v1:** el modelo recomienda desde su
   conocimiento; si la frescura importa, v2 habilitaría tools del app-server (fuera de alcance).
9. **R-TARBALL — URL/sha256 del tarball npm por verificar en build:** T08 lo resuelve y pinea; si
   el layout difiere, cae al asset standalone de GitHub Releases registrando la decisión.
10. **Gate de aprobación:** el bundle queda pendiente de aprobación del usuario antes de
    despachar; T10 produce `final-review.md` con el live gate como ítem pendiente explícito si no
    se ha ejecutado.
