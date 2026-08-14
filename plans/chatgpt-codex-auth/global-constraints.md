# Global Constraints: Proveedor Codex (ChatGPT) — vinculación OAuth y app-server

Invariantes ejecutables para todas las tareas del bundle. No contiene reglas de proceso.
Un cambio de estos contratos exige volver a secuenciar dependientes y registrarlo en el decision
ledger de `progress.md`.

## Boundary and product scope

- Proveedor **adicional**: los flujos gemini/openrouter/deepseek permanecen intactos. Nada se
  elimina ni cambia de comportamiento en ellos.
- Alcance web-only. `android/`, `frontend/js/projectView.js` (salvo el bloque de uso), los
  contratos SSE existentes y `backend/auth.py` no cambian su comportamiento; los cambios en
  `main.py` son aditivos.
- Identidad del proveedor: `EXPLAINER_PROVIDER_CODEX = "codex"` (Literal y constante de
  almacenamiento `PROVIDER_CODEX = "codex"`). Modelo único fijo `gpt-5.6-luna`, sin selector de
  modelo en la UI ni en la API.
- Prohibido: login de ChatGPT por API key (vía de facturación distinta), transporte
  WebSocket/experimental del app-server, `experimentalApi`, compartir un proceso/CODEX_HOME entre
  usuarios, y habilitar tools del app-server en v1.

## Container runtime and binary

- Base `python:3.11-slim` sin Node. El binario `codex` se instala desde el tarball de
  `@openai/codex-linux-x64@0.147.0` (registry.npmjs.org), con **sha256 pineado** en el
  Dockerfile, a `/usr/local/bin/codex`. No se usa el instalador `install.sh` ni npm/npx en
  runtime.
- Ruta del binario en runtime: env `CODEX_BIN_PATH` (default `/usr/local/bin/codex`); los tests
  lo apuntan al fake app-server.
- `koyeb.yaml` mantiene nano, 512 MB, scale-to-zero, healthcheck `/healthz` y max 1 instancia.
  Todo cambio funcional en él debe ser reportado como excepción, no aplicado en silencio.

## Tenant isolation and process lifecycle

- Un proceso `codex app-server --stdio` por `user_id`, spawn perezoso vía
  `CodexAppServerManager.acquire(user_id)`, evicción por inactividad y shutdown del lifespan.
  Nunca un proceso compartido ni un spawn por request.
- `CODEX_HOME = /tmp/codex/<user_id>`, creado con modo **0700**. El `user_id` debe pasar
  `re.fullmatch(r"[0-9a-fA-F-]{36}", user_id)` antes de usarse en paths. El contenido de
  `CODEX_HOME` solo se escribe/lee cuando el proceso está detenido (restauración antes del spawn,
  snapshot tras terminar).
- `auth.json` es un blob opaco: se restaura desde `user_provider_connections.encrypted_credentials`
  (descifrado con `decrypt_user_api_key`) antes del spawn cuando `status="linked"`; se
  re-sincroniza cifrado al evacuar/apagar. Nunca se loguea su contenido ni se incluye en errores
  de usuario.
- Transporte: JSONL newline-delimited por stdin/stdout. Requests
  `{"jsonrpc":"2.0","id":N,"method":...,"params":{...}}`; respuestas se resuelven por `id`; las
  notificaciones (sin `id`) se despachan a handlers registrados con
  `add_notification_handler(method, handler)` donde `handler(user_id, params) -> Awaitable[None]`.
  Una única reader-task por proceso; nada bloquea el loop.
- stderr del proceso → fichero acotado `<CODEX_HOME>/app-server.stderr.log` (truncado en cada
  spawn); nunca se vuelca automáticamente a los logs de la aplicación.
- Límites por env: `CODEX_MAX_PROCESSES=3` (global, semáforo con espera
  `CODEX_SPAWN_WAIT_SECONDS=60` → `CodexSpawnError`), `CODEX_PER_PROCESS_MAX_CONCURRENCY=5`
  (por proceso), `CODEX_IDLE_TTL_SECONDS=600`, `CODEX_REQUEST_TIMEOUT_SECONDS=900`,
  `CODEX_LINK_TIMEOUT_SECONDS=600`. Evicción LRU de procesos inactivos antes de rechazar por
  capacidad.
- Concurrencia: hasta 5 peticiones simultáneas por proceso (una por parte, `MAX_CONCURRENT_PARTS`).
  Nunca se crean más de `CODEX_MAX_PROCESSES` procesos vivos.

## Persistence — tabla `user_provider_connections`

Migración: `supabase/migrations/20260814120000_user_provider_connections.sql`. Esquema fijo:

```sql
create table if not exists public.user_provider_connections (
  user_id uuid primary key references auth.users(id) on delete cascade,
  provider text not null default 'codex' check (provider = 'codex'),
  status text not null default 'none' check (status in ('none','pending','linked','failed')),
  encrypted_credentials text,
  login_id text,
  plan_type text,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

- RLS habilitada con políticas de select/insert/update sobre filas propias
  (`auth.uid() = user_id`), patrón de `user_api_keys`; el backend accede con service_role.
- `encrypted_credentials` = `encrypt_user_api_key(json.dumps(auth_json), user_id)` (Fernet por
  usuario, `backend/crypto.py`). Nunca texto plano. `login_id` y `plan_type` no son secretos.
- `status` transita: `none → pending → linked | failed`, y `linked → none` (desvincular).
  `last_error` guarda solo mensajes seguros (sin credenciales ni contenido del blob).
- Funciones en `backend/supabase_data.py` (firmas congeladas): `get_user_provider_connection`,
  `upsert_user_provider_connection`, `delete_user_provider_connection`.
  `get_user_api_key_status` devuelve además: `has_codex_link` (bool),
  `codex_status` (`none|pending|linked|failed`), `codex_plan_type` (str|null),
  `codex_updated_at` (str|null). Campos nuevos, ninguno existente renombrado.

## Link endpoints (device-code OAuth)

Todos con `@api_key_rate_limit` y `get_current_user_id`:

- `POST /api/settings/codex-link/start`: si `status="linked"` → 400
  ("Tu cuenta ChatGPT ya está vinculada."); si `pending` → 409. Llama
  `account/login/start` con `type="chatgptDeviceCode"`; respuesta esperada
  `{verificationUrl, userCode, loginId}` (casing de la receta). Devuelve 200
  `{"ok":true,"verification_url":...,"user_code":...,"login_id":...,"expires_in":...}` y guarda
  fila `pending` con `login_id`. Fallo de spawn → 503 con mensaje honesto, sin reintento
  silencioso.
- `GET /api/settings/codex-link/status`: lee la fila; devuelve
  `{"ok":true,"codex_status":...,"codex_plan_type":...,"last_error":...}`. Si `pending` y el
  proceso del tenant fue recreado sin login en vuelo (cold start), tras un grace de 60 s marca
  `failed` con "El vínculo caducó por un reinicio del servidor. Vuelve a iniciarlo.".
- `POST /api/settings/codex-link/cancel`: `account/login/cancel` con el `loginId` pendiente;
  fila → `none`. Idempotente si no hay pendiente.
- `DELETE /api/settings/codex-link`: si `linked`, `account/logout` (best-effort); borra la fila,
  evacúa el proceso y elimina `CODEX_HOME`. Idempotente; un logout fallido NO debe impedir el
  borrado local.
- La notificación `account/login/completed` dispara: leer `CODEX_HOME/auth.json` → cifrar →
  `upsert_user_provider_connection(status="linked", encrypted_credentials=..., plan_type=...)`
  con `account/read.planType` best-effort (valor crudo normalizado, sin allowlist de planes).
  Timeout global del vínculo: `CODEX_LINK_TIMEOUT_SECONDS` → `failed` + cancel en el servidor.
- Lifespan de FastAPI: en el `finally` existente se ejecuta `await codex_manager.shutdown()`
  (persiste auth.json de usuarios `linked`, termina procesos, limpia homes).

## Codex client and errors

- `call_codex_chat` es **corrutina async** (el manager vive en el event loop):
  `await codex_manager.acquire(user_id)` + `await app.request(...)`. Nunca se invoca dentro de
  `asyncio.to_thread`; las variantes de agentes Codex también son async y se esperan directo.
- **Ciclo de turno streaming (FR-01, verificado en source `08e482e2` /
  `rust-v0.147.0-alpha.9`):** la response de `turn/start` solo acepta el turno
  (`{turn:{id,status:"inProgress",items:[]}}`) — **no contiene texto ni usage**. No existen
  `turn/end` ni `turn/poll`: el cliente debe esperar la notificación `turn/completed`
  (correlación por `turnId` de la response + `user_id`). El texto final se toma SOLO del
  `item/completed` con `item.type=="agentMessage"` y `item.text`; los deltas
  (`item/agentMessage/delta`) son solo para UI/progreso y en v1 se ignoran. El usage llega en
  la notificación `thread/tokenUsage/updated`. Un error de cuota en ejecución llega como
  notificación `error` (`error.codexErrorInfo=="usageLimitExceeded"`, `willRetry:false`) y
  termina con `turn/completed` `status:"failed"` y `turn.error` (mismo TurnError); un error de
  aceptación de `turn/start` SÍ puede ser JSON-RPC error en la response — son caminos
  distintos.
- `CodexUsage` expone: `prompt_token_count`, `tool_use_prompt_token_count`,
  `candidates_token_count`, `thoughts_token_count`, `total_token_count` (ceros si el turno no
  los reporta; nunca valores inventados), `cost_usd = 0.0`, `cost_source = "chatgpt_quota"`,
  `quota_requests = 1`. Mapeo congelado desde `thread/tokenUsage/updated.tokenUsage`
  (preferir `last`, fallback `total`): `inputTokens → prompt_token_count`,
  `cacheWriteInputTokens → tool_use_prompt_token_count`, `outputTokens →
  candidates_token_count`, `reasoningOutputTokens → thoughts_token_count`, `totalTokens →
  total_token_count`.
- Errores tipados (jerarquía `CodexError`): `CodexRateLimitError` (quota/UsageLimitExceeded →
  mensaje UX: "Has agotado la cuota de Codex de tu plan ChatGPT por ahora. Inténtalo más tarde o
  cambia de proveedor."), `CodexAuthError` (refresh fallido/desvinculado → "Tu cuenta ChatGPT ya
  no está vinculada. Vuelve a vincularla en Ajustes."), `CodexBusyError` (capacidad →
  "Codex está saturado en este momento. Espera un poco e inténtalo de nuevo."),
  `CodexTimeoutError`, `CodexSpawnError`, `CodexRequestError` (con `.code/.message/.data`).
  `call_codex_chat` re-lanza `CodexSpawnError` como `CodexBusyError`.
  Mapeo de notificaciones/turn.error: `codexErrorInfo` (case-insensitive)
  `usageLimitExceeded` → `CodexRateLimitError`; `unauthorized` → `CodexAuthError`; cualquier
  otro → `CodexError(CODEX_TURN_FAILED_MESSAGE)` donde `CODEX_TURN_FAILED_MESSAGE =
  "Codex no pudo completar el turno. Espera un poco e inténtalo de nuevo."` (constante
  ADITIVA del amendo FR-01; los mensajes UX existentes no cambian). El mapeo por `code` de los
  error objects de response (aceptación) se mantiene como estaba.
- `call_codex_chat` usa `thread/start` + `turn/start` con override `model="gpt-5.6-luna"` por
  turno; con `response_format="json_object"` hace `json.loads` del texto final y reintenta
  conversacionalmente (máx. `OPENROUTER_PAYLOAD_VALIDATION_MAX_RETRIES`), añadiendo turno
  correctivo corto sin reenviar la fuente (patrón `_DeepSeekExplainerConversation`). Sin tools.
  El turno correctivo es un nuevo `turn/start` en el MISMO thread, con su propio `turnId` y su
  propia espera de `turn/completed`.
- Concurrencia: la correlación de notificaciones es por `(user_id, turnId)` con un registro de
  esperas propio del cliente (futures); llamadas simultáneas del mismo usuario no pueden cruzar
  texto, usage ni errores. Los handlers se registran una vez a nivel de módulo
  (idempotente). El `timeout` de `call_codex_chat` cubre cada request RPC y la espera de
  `turn/completed` por intento.
- Los conteos de tokens se parsean defensivamente de la notificación de usage (campos
  verificados arriba); su ausencia no es error.

## Agent variants (contratos posicionales congelados)

- Cada variante es una **corrutina `async`** que se espera directamente en el pipeline (no vía
  `asyncio.to_thread`) y devuelve `(data, CodexUsage)` (o `(data, CodexUsage, list)` las
  validadas). Reutiliza los builders de prompts y validadores existentes
  (`build_openrouter_explainer_system_prompt`, `_validate_full_explainer_payload`,
  `build_*_system_instruction`, contracts JSON de cada agente). Firmas exactas en `plan.md` →
  Cross-task interfaces; el parámetro `user_id` ocupa la posición de `api_key` en las variantes
  `_ds` para que el threading posicional de `main.py` no cambie el orden de argumentos (solo la
  mecánica: `await` directo en lugar de `asyncio.to_thread`).
- El validador de completitud del explainer se ejecuta vía Codex
  (`run_with_codex_explainer_validation`, en `explainer_codex.py`), sin clave de DeepSeek.
- `run_resources_codex` **no** usa Tavily ni búsqueda web en v1; recomienda desde conocimiento
  del modelo.
- Ninguna variante loguea prompts completos, `auth.json` ni contenido de `CODEX_HOME`; se usa
  truncado de previews como en las variantes `_ds`.

## Fake app-server (fixture de test)

- `tests/backend/fake_codex_app_server.py` (T02) es la única autoridad del wire-format en tests y
  es **read-only para el resto de tareas**: T03/T04/T05/T06/T07 lo consumen sin editarlo; si falta
  un escenario, se reporta (decisión del orquestador), no se edita en paralelo.
- Escenarios base del fixture (seleccionables por env, amendo FR-01): `echo`, `login_completes`
  (emite notificación `account/login/completed` tras N s), `login_pending`, `logout_ok`,
  `account_read_plan`, `invalid_json`, `slow_turn` (respuesta RPC lenta),
  `scripted_turn` (secuencia STREAMING completa: response `{turn:{id,status:"inProgress",
  items:[]}}` + notificaciones `turn/started`, `item/started`, `item/agentMessage/delta`,
  `item/completed` agentMessage con el texto final desde `FAKE_CODEX_TURN_OUTPUT_FILE`,
  `thread/tokenUsage/updated` si hay `FAKE_CODEX_TOKEN_USAGE_FILE`, y `turn/completed`
  `status:"completed"`), `usage_limit` (notificación `error` con
  `codexErrorInfo:"usageLimitExceeded"` + `turn/completed` `status:"failed"` con `turn.error`;
  `thread/start` responde normal; los demás métodos devuelven error object UsageLimitExceeded),
  `stalled_turn` (turno aceptado y sin notificaciones: timeout de espera de `turn/completed`) y
  `scripted_error` (error object en la response — error de aceptación — desde
  `FAKE_CODEX_ERROR_CODE`).
- Convención de ficheros por turno (determinismo multi-turno/concurrente): el turno N lee
  `<FAKE_CODEX_TURN_OUTPUT_FILE>.<N>` si existe y si no el fichero base (ídem para
  `FAKE_CODEX_TOKEN_USAGE_FILE`). El fichero de salida se emite como texto plano UTF-8 (nunca
  `json.load`). Shape de `tokenUsage`: `{"total": <breakdown>, "last": <breakdown>,
  "modelContextWindow": <int>}` con breakdown
  `{"inputTokens","cachedInputTokens","cacheWriteInputTokens","outputTokens",
  "reasoningOutputTokens","totalTokens"}`.

## Pipeline wiring (main.py) — reglas exactas

- `ExplainerProvider = Literal["gemini","openrouter","deepseek","codex"]`; 
  `_resolve_explainer_model("codex", ...)` → `CODEX_MODEL` siempre (sin parámetros extra).
- `ProcessProjectRequest` **no** gana campos nuevos. `explainer_config` persiste
  `{"provider":"codex","model":"gpt-5.6-luna"}`.
- En `_process_project`: `use_codex_explainer` y `use_text_provider_explainer = or|deepseek|codex`.
  YouTube → fallback a Gemini también para codex (mismo bloque 2235-2248, reseteando
  `use_codex_explainer`). Modelos de clasificador/segmentador/auxiliares/validador/formatter →
  `CODEX_MODEL` cuando codex. `text_provider_api_key = user_id`; las variantes codex son
  corrutinas async que se **esperan directamente** (`await`/`asyncio.gather`) en los mismos
  puntos donde hoy se eligen las `_ds` (que van por `asyncio.to_thread`); el orden posicional de
  argumentos es idéntico (`validator_user_id = user_id` en las variantes validadas).
- Pre-checks en `api_process_project` para codex (y source != youtube):
  vínculo `linked` requerido → si no: 400 "Vincula tu cuenta ChatGPT en Ajustes para usar Codex
  (GPT-5.6 Luna)."; `source_type=="pdf"` → key Mistral requerida (mensaje análogo al de
  DeepSeek: "…OCR nativo en PDFs con Codex"). Regla Gemini: `requires_gemini_key =
  explainer_provider in (GEMINI, OPENROUTER) or source_type == "youtube"`.
- Errores de agente codex caen en el try/except por parte existente → `part_failed` + SSE con el
  mensaje UX del error tipado (sin stack). `_failed_part_ids`/`_format_and_finalize_part`
  intactos.
- `api_part_review`: rama `provider == EXPLAINER_PROVIDER_CODEX` → modelo de `explainer_config`
  o `CODEX_MODEL`, `provider_label="Codex"`, gate de vínculo `linked` (mismo mensaje del
  pre-check), `review_agent = run_review_codex` con `user_id` en la posición de key.
  `CodexRateLimitError` → 429 con su mensaje; `CodexAuthError` → 400 "vuelve a vincular".
- `api_reformat_project`: rama codex → `format_explainer_content_codex(user_id, explainer, lang)`;
  `formatter_usage` con coste 0 y conteos si existen.
- `api_generate_mermaid`: **sin cambios** (key DeepSeek de plataforma; decisión documentada).
- Usage: `cumulative_usage` gana `"codex_quota_requests": 0` y acumula
  `getattr(usage_meta, "quota_requests", 0)`; `_update_usage` acepta
  `getattr(usage_meta, "cost_source", None)` y lo usa en `cost_source` (con coste 0 para
  `chatgpt_quota`); `_accumulate_review_usage` admite `CodexUsage` sin romper gemini/or.
  `backend/pricing.py` gana la entrada `"gpt-5.6-luna"` con los 4 precios a `0.0`
  (fallback de `calculate_cost`, nunca un coste positivo).

## Frontend invariants

- `validProviders = ['gemini','openrouter','deepseek','codex']` en `landing.js`; la clave de
  persistencia `explainer.modelSelector.v1` no gana campos (modelo fijo).
- `isExplainerProviderSupportedForSource('codex', 'youtube') === false` (cae a Gemini con hint);
  pdf y web soportados.
- `restoreModelSelector`: `codex` requiere `state.hasCodexLink`, si no → fallback `gemini`
  (patrón existente de fallback por key).
- `validateExplainerProviderSelection` añade (con los mismos parámetros + `hasCodexLink`):
  codex sin vínculo → "Vincula tu cuenta ChatGPT en Ajustes para usar Codex.";
  codex + pdf sin Mistral → "Necesitas configurar tu API key de Mistral para usar OCR en PDFs
  con Codex.".
- Estado en `state.js`: `hasCodexLink` (bool), `codexLinkStatus`
  (`'none'|'pending'|'linked'|'failed'|'loading'`), `codexPlanType` (str|null); cache
  `explainer.codexLinkStatus.v1` en storage.js con el patrón de caches por proveedor existente.
- Flujo de vínculo en Ajustes: botón iniciar → panel device-code (verification_url como enlace
  `target="_blank" rel="noopener noreferrer"`, user_code copiable, botón cancelar) → polling de
  `GET /api/settings/codex-link/status` cada 3 s, máx. 10 min → estados linked (muestra planType)
  / failed (muestra last_error) / expired con reintento; botón "Desvincular" confirmado llama a
  DELETE.
- Display de uso (projectView.js): si `usage.codex_quota_requests > 0`, mostrar
  "Cuota ChatGPT: N peticiones"; `total_cost` se muestra como 0/incluido sin inventar dólares.
- Card del proveedor en `#explainer-provider-group` con sub "GPT-5.6 Luna — incluida en tu plan
  ChatGPT" y punto de estado `#provider-card-codex-status` actualizado por `updateApiKeyUI`.

## Security invariants

- Nunca loguear: contenido de `auth.json`, `encrypted_credentials`, tokens, `loginId` junto a
  credenciales, ni stderr crudo del app-server. `mask_api_key` solo para keys BYOK existentes.
- El backend accede a `user_provider_connections` con service_role; la identidad siempre viene
  del JWT verificado (`get_current_user_id`), nunca de campos del body.
- Cualquier error devuelto al frontend pasa por el mensaje UX tipado; sin stack traces ni
  detalles internos del JSON-RPC (solo `.code`/categoría cuando sea seguro).
- `user_id` usado en `CODEX_HOME` pasa validación UUID estricta (anti path traversal).
