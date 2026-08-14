# Integration Recipe: Codex CLI app-server

## Objective

Run the Codex app-server in a Linux FastAPI container so each tenant uses their own
ChatGPT-managed Codex entitlement, without sharing credentials, threads, or quota state.
The JSON-RPC protocol itself is intentionally not repeated here.

## Chosen Approach

Use the official standalone Linux-musl CLI installer, pinned in deployment rather than
tracking `latest`; the npm package is a valid alternative but its launcher requires Node.
At verification time npm reported `@openai/codex` version `0.147.0` and platform dist-tags
`0.147.0-linux-x64`/`0.147.0-linux-arm64`. Pin `@openai/codex@0.147.0` (or pin the exact
standalone release asset digest once selected). Do **not** run one app-server process for
multiple ChatGPT accounts: use one process and one `CODEX_HOME` per tenant, or a process
pool keyed by tenant. Keep each home private (mode 0700) and never expose `auth.json`.

## Verified Contract

- **Auth:** ChatGPT-managed login owns refresh tokens, persists credentials to disk, and
  refreshes automatically (official app-server README, per-docs). Device-code login returns
  `verificationUrl`, `userCode`, and `loginId`; the server polls asynchronously and emits
  `account/login/completed`. `account/login/cancel` cancels the matching pending login.
  The source implementation confirms cancellation via a `CancellationToken` and that only
  the matching active login is cleared. No `experimentalApi` capability is required for
  ChatGPT browser/device login; the README requires it for Amazon Bedrock only.
- **Calls/endpoints/selectors:** stdio is the default and is newline-delimited JSONL;
  `--stdio`/`--listen stdio://` are equivalent. Unix transport is
  `--listen unix://` or `--listen unix:///absolute/path` and defaults under
  `$CODEX_HOME/app-server-control/app-server-control.sock`. WebSocket `--listen ws://...`
  is explicitly experimental/unsupported for production. `--listen off` disables local
  transport. `codex app-server proxy` bridges the Unix socket to stdin/stdout.
- **Request params:** Set `model: "gpt-5.6-luna"` in `turn/start`; the app-server README
  documents model overrides there. `thread/start` also has model selection in the current
  schema/implementation, but the safe integration rule is to call `model/list` first and
  use the returned id, then set the per-turn override. Do not infer availability solely
  from the marketing name.
- **Response/extracted shape:** The checked-out official repository's static model catalog
  contains slug `gpt-5.6-luna` and display name `GPT-5.6-Luna`; this confirms the expected
  identifier in the current source, not a live entitlement check. `model/list` is the runtime
  authority for the logged-in account/provider.
- **Pagination/rate limits:** The app-server README documents `account/rateLimits/read` as
  returning ChatGPT rate limits, optional effective monthly credit limit, spend-control
  status, and earned reset credits; updates are sparse notifications. This is per-docs,
  not a live authenticated call. Do not hard-code plan enum values: the public pricing pages
  describe Free/Go/Plus/Pro/Business/Enterprise/Edu and flexible-credit variations, while
  the existing protocol notes may use a narrower `planType` vocabulary. Normalize unknown
  values and display the raw provider value.
- **Errors:** Existing protocol documentation covers quota errors. Treat login timeout,
  cancellation, invalid/expired device code, authentication refresh failure, and rate-limit
  exhaustion as separate retry/user-action states; never automatically retry a failed login
  indefinitely.

## Minimal Working Snippet

```bash
# Official Linux/macOS installer; pin the resolved release in image build/reproducibility.
curl -fsSL https://chatgpt.com/codex/install.sh | sh

# One long-lived server per tenant (home must already exist for CODEX_HOME).
install -d -m 700 "/data/codex/${TENANT_ID}"
CODEX_HOME="/data/codex/${TENANT_ID}" codex app-server --stdio
```

For npm-based images:

```bash
npm install -g @openai/codex@0.147.0
```

The npm distribution is a native prebuilt launcher/package, but the launcher requires a
compatible Node runtime. The standalone Linux archives are musl builds (`codex-x86_64-
unknown-linux-musl.tar.gz` or `codex-aarch64-unknown-linux-musl.tar.gz`) and do not require
Rust at runtime. Building from source does require Rust and is unnecessary for deployment.

## Setup

- **Env vars:** `CODEX_HOME` is the state root (default `~/.codex`) and includes config,
  auth, logs, sessions/threads, skills, and package metadata. `CODEX_SQLITE_HOME` controls
  SQLite-backed state and defaults to `CODEX_HOME`; use it only if deliberately separating
  database state. `CODEX_ACCESS_TOKEN` is a trusted-automation token override, not a
  per-request multi-account mechanism. Set `HOME`/container user consistently.
- **Install/version:** Official command above; pin `0.147.0` in npm or pin the standalone
  release URL/sha256. `npm view @openai/codex version dist-tags --json` was executed and
  returned `0.147.0`/the platform tags cited above.
- **Permissions/scopes:** The ChatGPT account must have Codex access under its plan. Login
  must be initiated by the tenant and the resulting device code completed by that tenant.
  No API key is needed for ChatGPT-managed usage; API-key login is a different billing path.

## Gotchas

1. **Isolation:** `CODEX_HOME` is process configuration, not a request/connection selector.
   A process has one auth/config/state context. Run separate app-server processes (recommended)
   or separate serialized workers with distinct `CODEX_HOME` directories. `account/logout`
   operates on the current process/home's account; with correctly isolated homes it cannot
   log out another tenant. A shared home is a credential and thread leakage risk.
2. **Device-code headless flow:** Device code is the appropriate server flow: show the URL
   and code in the web UI, retain `loginId`, await the completion notification, and offer
   cancellation. The browser `type: "chatgpt"` flow is also configured with `open_browser: false`
   in the current source, but it starts a local callback login server; do not assume a
   container's localhost callback is reachable from the user's browser. Prefer device code.
3. **Model naming/availability:** Current source says `gpt-5.6-luna`, not `GPT-5.6 Luna` or
   `gpt-5.6-Luna`. Runtime `model/list` wins if the catalog changes, hides a model, or the
   account/provider differs. ChatGPT pricing says Luna is included for supported ChatGPT
   plans; API-key usage is separately metered at API rates. The GitHub README's older quickstart
   wording mentions Plus/Pro/Business/Edu/Enterprise, while current learn.chatgpt.com/help
   pages say Free and Go are included too: this is a real documentation contradiction, so
   do not reject a plan from a local allowlist; use successful account/model responses.
4. **Headless transport:** stdio works without a TTY by contract. Unix sockets are suitable
   for same-container local control. Do not expose unauthenticated WebSocket transport; if
   remote access is required, use the documented WebSocket authentication/TLS options from
   the developer app-server page, or keep FastAPI as the authenticated broker.
5. **Quota semantics:** Limits are shared agentic usage/credits and vary by model, workload,
   and rolling window; a successful `rateLimits/read` is advisory, not a reservation. Enforce
   tenant ownership and rate limiting in FastAPI as well.

## Verification Status

- Official install command and Linux archive names - per-docs - `https://github.com/openai/codex/blob/main/README.md` and `https://chatgpt.com/codex/install.sh`.
- Current npm version/dist-tags - VERIFIED - command `npm view @openai/codex version dist-tags --json`; output reported `0.147.0`, `latest: 0.147.0`, and platform tags.
- CLI help - UNVERIFIED - local `codex --help` and `codex app-server --help` failed because the installed wrapper lacked optional `@openai/codex-linux-x64`; it printed: `Missing optional dependency ... Reinstall Codex: npm install -g @openai/codex@latest`.
- CODEX_HOME/CODEX_SQLITE_HOME and state contents - per-docs - `https://developers.openai.com/codex/environment-variables`, `https://developers.openai.com/codex/config-advanced`.
- stdio/unix/WebSocket transports and headless semantics - per-docs - `https://developers.openai.com/codex/app-server` and `https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md`.
- Device-code async polling/cancellation/token persistence - VERIFIED against checked-out source at commit `813dc5f08d771d351e1da7f00eace464ffe43263`, files `codex-rs/app-server/src/request_processors/account_processor.rs` (not a live provider call).
- Luna slug - VERIFIED against current checked-out source catalog, same commit, `codex-rs/models-manager/models.json`; live `model/list` with ChatGPT credentials - UNVERIFIED.
- Plans/limits - per-docs with contradiction - `https://learn.chatgpt.com/docs/pricing`, `https://developers.openai.com/codex/pricing`, `https://help.openai.com/en/articles/11369540-codex-and-chatgpt-plan-usage-limits`.

## Open Risks

- Release behavior and model catalog can change; pin and integration-test the exact CLI build.
- No authenticated account or tenant credentials were available, so login, `account/read`,
  `account/rateLimits/read`, `model/list`, refresh persistence, and logout isolation were not
  exercised end-to-end.
- The container must persist each tenant's `CODEX_HOME` securely if sessions/login survive
  restarts; otherwise require reauthentication. Treat all thread transcripts as tenant data.

## Turn lifecycle verification (reconciliación FR-01)

**Base de verificación.** No existe un tag estable exactamente llamado `0.147.0` en el
repositorio; la línea publicada más cercana disponible es `rust-v0.147.0-alpha.9`, commit
`08e482e2cc31491c048d85bded73c391cbfda73e` (y se contrastó el README de `main`, commit
`4e5a08feb63f79e407c86f69a78dc8c7ef115d88`). Por tanto, las afirmaciones de source llevan
esa salvedad de versionado.

1. **`turn/start` es streaming, no síncrono. VERIFIED (source/docs).** Su response exacta es
   `{ "turn": <Turn> }`: `TurnStartResponse` sólo contiene `turn`
   ([turn.rs#L163-L168](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L163-L168)).
   El `Turn` incluye `id`, `items`, `itemsView`, `status`, `error`, timestamps y duración
   ([thread_data.rs#L253-L276](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs#L253-L276)); al iniciar
   `status` es `inProgress` y `items` normalmente está vacío. No contiene el texto final.
   El README oficial confirma que responde inmediatamente y que el resultado se transmite
   después ([README.md#L81-L83](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server/README.md#L81-L83)).

2. **No hay `turn/end` ni `turn/poll`. VERIFIED (docs/source).** El método de cancelación es
   `turn/interrupt`, cuya response es `{}`; la terminación normal se detecta leyendo la
   notificación `turn/completed`, no una response RPC ([README.md#L200-L203](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server/README.md#L200-L203)).
   `TurnCompletedNotification` tiene `threadId` y `turn` ([turn.rs#L404-L410](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L404-L410)).

3. **Secuencia y texto. VERIFIED (source/docs).** Para texto simple, el cliente debe aceptar
   `turn/start` → `turn/started` → notificaciones de items (incluidos `item/started`, uno o
   más `item/agentMessage/delta`) → `item/completed` del `agentMessage` → `turn/completed`;
   `thread/tokenUsage/updated` puede intercalarse. Items de usuario, reasoning o herramientas
   pueden añadir eventos: el protocolo no promete una lista fija de eventos opcionales.
   Cada delta lleva `delta`, `itemId`, `threadId` y `turnId`
   ([item.rs#L1336-L1345](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/item.rs#L1336-L1345)).
   El `item/completed` es autoritativo: su `item` puede ser `agentMessage` con `text`
   ([item.rs#L1315-L1325](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/item.rs#L1315-L1325));
   acumular deltas sólo sirve para UI/progreso. El `turn/completed` trae el `turn` final y
   sus `items` cuando `itemsView` es `full`, pero no debe sustituir la correlación por
   `itemId` ni asumirse que cada notificación intermedia está ordenada como una lista fija.

4. **Usage. VERIFIED (source/docs).** No está en la response de `turn/start` ni como campo de
   `Turn`. Se emite en `thread/tokenUsage/updated` con `{threadId, turnId, tokenUsage}`;
   `tokenUsage` contiene `total`, `last` y `modelContextWindow`
   ([thread.rs#L1576-L1606](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L1576-L1606)).
   Cada breakdown contiene `inputTokens`, `cachedInputTokens`, `cacheWriteInputTokens`,
   `outputTokens`, `reasoningOutputTokens` y `totalTokens`. El servidor emite esa
   notificación al procesar `TokenCountEvent` ([bespoke_event_handling.rs#L1576-L1591](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server/src/bespoke_event_handling.rs#L1576-L1591));
   el `turn` final no tiene usage.

5. **Cuota. VERIFIED (source; live quota UNVERIFIED).** Una vez aceptado el turno, un límite
   se comunica como notificación `error`, no como texto de `turn/start`: su shape es
   `{error:{message,codexErrorInfo:"usageLimitExceeded",additionalDetails},willRetry:false,threadId,turnId}`
   ([notification.rs#L38-L48](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/notification.rs#L38-L48);
   [shared.rs#L75-L81](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/shared.rs#L75-L81)).
   El terminal `turn/completed` debe ser `status:"failed"` y su `turn.error` contiene el
   mismo `TurnError` (ese campo sólo se rellena en status failed; [thread_data.rs#L264-L266](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs#L264-L266)).
   Un error de validación/aceptación sí puede ser JSON-RPC error en la response de
   `turn/start`; no debe confundirse con la cuota descubierta durante ejecución.

6. **Modo síncrono/no-streaming. UNVERIFIED como ausencia de soporte en 0.147.0; source
   strongly indicates no.** `TurnStartParams` no tiene flag `sync`, `stream` ni `wait`
   ([turn.rs#L66-L75](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L66-L75));
   la documentación sólo define el flujo streaming. El cliente debe mantener el reader de
   notificaciones y resolver la operación en `turn/completed`, no esperar texto/usage en la
   response RPC.

**Cambio requerido para FR-01:** `backend/codex_client.py` debe correlacionar el `turnId`,
acumular/mostrar deltas, tomar el texto final de `item/completed.item` cuando sea
`type:"agentMessage"`, tomar usage de `thread/tokenUsage/updated`, y cerrar sólo en
`turn/completed`; eliminar cualquier dependencia de `turn/end` o de un resultado final en
 la response de `turn/start`.

## Request param shapes (reconciliación FR-01b)

**Base.** Verificación estática contra commit `08e482e2cc31491c048d85bded73c391cbfda73e`
(línea `rust-v0.147.0-alpha.9`). `#[serde(rename_all = "camelCase")]` determina los
nombres JSON; los campos `Option<T>` son opcionales/nullables.

1. **`thread/start` params — VERIFIED (source).** `ThreadStartParams` tiene exactamente los
   campos JSON `model?`, `modelProvider?`, `allowProviderModelFallback?`, `serviceTier?`,
   `cwd?`, `runtimeWorkspaceRoots?`, `approvalPolicy?`, `approvalsReviewer?`, `sandbox?`,
   `permissions?`, `config?`, `serviceName?`, `baseInstructions?`, `developerInstructions?`,
   `personality?`, `multiAgentMode?`, `ephemeral?`, `historyMode?`, `sessionStartSource?`,
   `threadSource?`, `environments?`, `dynamicTools?`, `selectedCapabilityRoots?`,
   `mockExperimentalField?`, `experimentalRawEvents?` (todos opcionales; tipos exactos en
   [`thread.rs#L52-L149`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L52-L149)).
   En particular, es `approvalPolicy` y `sandbox`, no `approval_policy` ni `sandboxPolicy`.

2. **`thread/start` response — VERIFIED (source).** Es `{"thread": Thread, "model": string,
   "modelProvider": string, "serviceTier": string|null, "cwd": AbsolutePathBuf,
   "runtimeWorkspaceRoots": AbsolutePathBuf[], "instructionSources": string[],
   "approvalPolicy": AskForApproval, "approvalsReviewer": ApprovalsReviewer,
   "sandbox": SandboxPolicy, "activePermissionProfile": ActivePermissionProfile|null,
   "reasoningEffort": ReasoningEffort|null, "multiAgentMode": MultiAgentMode}`
   ([`thread.rs#L168-L202`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L168-L202)).
   El id es `result.thread.id`; `Thread` define `id: string` anidado, no `threadId`/`threadID`
   ([`thread_data.rs#L181-L229`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs#L181-L229)).

3. **`turn/start` params — VERIFIED (source).** Los campos JSON exactos son `threadId`
   (obligatorio), `clientUserMessageId?`, `input` (obligatorio), `responsesapiClientMetadata?`,
   `additionalContext?`, `environments?`, `cwd?`, `runtimeWorkspaceRoots?`, `approvalPolicy?`,
   `approvalsReviewer?`, `sandboxPolicy?`, `permissions?`, `model?`, `serviceTier?`, `effort?`,
   `summary?`, `personality?`, `outputSchema?`, `collaborationMode?`, `multiAgentMode?`
   ([`turn.rs#L66-L158`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L66-L158)).
   No existen `message`, `system`, `temperature` ni `response_format`.

4. **`input` — VERIFIED (source).** El item de texto es `{"type":"text","text":"...",
   "textElements":[]}`; `textElements` tiene default `[]` y puede omitirse. El tag es `type`,
   no `role`/`content`/`input_text` ([`turn.rs#L288-L298`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L288-L298)).

5. **Developer/system instructions — VERIFIED (source).** No existe `settings` top-level en
   `TurnStartParams` ni campo `system`. Para un thread se usa `thread/start.developerInstructions`
   (o `baseInstructions`). En collaboration mode la ruta exacta es
   `turn/start.collaborationMode.settings.developer_instructions`: `collaborationMode` es
   camelCase, pero `Settings.developer_instructions` conserva snake_case
   ([`TurnStartParams.json#L107-L121`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/schema/json/v2/TurnStartParams.json#L107-L121),
   [`TurnStartParams.json#L307-L333`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/schema/json/v2/TurnStartParams.json#L307-L333)).

6. **Controles — VERIFIED (source).** `outputSchema` es directamente un `JsonValue` con el
   JSON Schema (no `response_format`). Los controles de generación son `model`, `serviceTier`,
   `effort`, `summary`, `personality` y `outputSchema`; `collaborationMode` puede tomar
   precedencia sobre model/effort/developer instructions. `temperature` no se acepta
   ([`turn.rs#L122-L158`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L122-L158)).

7. **`turn/start` response — VERIFIED (source).** Es exactamente `{"turn": Turn}` y no
   contiene un resultado textual separado ([`turn.rs#L160-L168`](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L160-L168)).

**Resumen JSON (12 líneas; shape estático VERIFIED, llamada live UNVERIFIED):**

```json
// 1 thread/start request: todos los campos son opcionales
{"model":"<model>","cwd":"/workspace","approvalPolicy":"on-request","sandbox":"workspaceWrite","personality":"pragmatic","serviceName":"<service>"}
// 3 thread/start response: wrapper anidado
{"thread":{"id":"<thread-id>","sessionId":"...", "status":"...", "cwd":"..."},"model":"...","modelProvider":"...","cwd":"..."}
// 5 thread id: no es threadId/threadID al top-level
{"thread":{"id":"thr_123"}}
// 7 turn/start request: nombres v2
{"threadId":"thr_123","input":[{"type":"text","text":"hola"}]}
// 9 turn/start optional controls
{"model":"...","serviceTier":"...","effort":"...","summary":"auto","personality":"pragmatic","outputSchema":{}}
// 11 developer instruction en collaboration mode
{"collaborationMode":{"mode":"default","settings":{"model":"...","developer_instructions":"..."}}}
// 12 response: no texto final síncrono
{"turn":{"id":"turn_123","status":"inProgress","items":[]}}
```

**Impacto FR-01b:** `_turn_params` debe reemplazar `threadID` por `threadId`, eliminar
`message`/`system`, y enviar `input` con `{type:"text",text}`. Para instrucciones usar
`developerInstructions` en `thread/start` o `collaborationMode.settings.developer_instructions`;
no introducir un `settings` top-level. No se realizó una llamada live autenticada: UNVERIFIED.
