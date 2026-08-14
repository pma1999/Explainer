# Integration Recipe: Codex reasoning effort (`gpt-5.6-luna`)

## Objective

Expose exactly the effort options advertised for `gpt-5.6-luna` through the app-server v2
selector, while retaining a thread default and a per-turn override.

## Chosen Approach

Use the runtime `model/list` entry as the authority for the selector, with the checked-in
`rust-v0.147.0-alpha.9` catalog as the pinned fallback. For Luna the exact advertised order is
`low`, `medium`, `high`, `xhigh`, `max`; default is `medium`. Do not expose `none`, `minimal`,
`ultra`, `extra_high`, or `auto` for this model. Note that the protocol type is intentionally
forward-compatible and is not a closed enum.

## Verified Contract

- **Auth:** Unchanged from the Codex app-server recipe; this artifact verifies effort only.
- **Calls/endpoints/selectors:** Call `model/list`; map each returned `supportedReasoningEfforts`
  entry to the UI, preserving provider order. The v2 model response fields are
  `supportedReasoningEfforts` and `defaultReasoningEffort` ([model.rs#L86-L101](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/model.rs#L86-L101)).
- **Request params:** `turn/start` accepts `effort` (camelCase does not change this name) and
  its field is `Option<ReasoningEffort>` ([turn.rs#L122-L136](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L122-L136)).
  `thread/start` has no top-level `effort` field ([thread.rs#L57-L149](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L57-L149)); set a thread default through `config: {"model_reasoning_effort": "..."}`.
- **Default/precedence:** The thread response reports the resolved `reasoningEffort`
  ([thread.rs#L168-L202](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L168-L202)). A per-turn `effort` is documented in source as an override, so both may be used: thread config default, then turn override. If both are omitted, normal config/model resolution supplies the default; Luna's catalog default is `medium` ([models.json#L258-L282](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/models-manager/models.json#L258-L282)).
- **Response/extracted shape:** At this commit the Luna catalog uses legacy names
  `supported_reasoning_levels` and `default_reasoning_level`; its exact values are low,
  medium, high, xhigh, max ([models.json#L258-L282](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/models-manager/models.json#L258-L282)). The app-server translates these to the v2 names above.
- **Enum/wire values:** The known variants serialize exactly as `none`, `minimal`, `low`,
  `medium`, `high`, `xhigh`, `max`, `ultra`; `extra_high` and `auto` are not variants. However,
  deserialization accepts every non-empty unknown string as `Custom`, so this is not a closed
  wire enum ([openai_models.rs#L37-L67](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/protocol/src/openai_models.rs#L37-L67), [openai_models.rs#L109-L135](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/protocol/src/openai_models.rs#L109-L135)).
- **Pagination/rate limits:** Not specific to effort; no effort pagination contract was found.
- **Errors/validation:** The source proves model-specific rejection in the multi-agent
  `spawn_agent` path: unsupported effort returns a model-visible error listing supported values
  ([multi_agents_common.rs#L456-L475](https://github.com/openai/codex/blob/08e482e2cc31491c048d85bded73c391cbfda73e/codex-rs/core/src/tools/handlers/multi_agents_common.rs#L456-L475)). A generic `turn/start` rejection/degradation for an unsupported effort was not proven in this checkout; treat it as UNVERIFIED and validate client-side from `model/list`.

## Minimal Working Snippet

```json
{"method":"thread/start","params":{"model":"gpt-5.6-luna","config":{"model_reasoning_effort":"medium"}}}
{"method":"turn/start","params":{"threadId":"thr_123","input":[{"type":"text","text":"Hola"}],"effort":"xhigh"}}
```

## Setup

- **Env vars:** None specific to effort.
- **Install/version:** Codex app-server line `rust-v0.147.0-alpha.9`, commit
  `08e482e2cc31491c048d85bded73c391cbfda73e`.
- **Permissions/scopes:** The authenticated account must have Luna available; use live
  `model/list` rather than a static plan allowlist.

## Gotchas

1. `ThreadStartParams` does **not** contain a top-level `effort`; the existing request-shape note
   claiming it does is incorrect. Use `config.model_reasoning_effort` for the thread default.
2. `reasoning_effort` is the TOML/config key; `effort` is the v2 `turn/start` field. Do not send
   `reasoning_effort` as a top-level v2 turn parameter.
3. Official config docs list `minimal | low | medium | high | xhigh` for
   `model_reasoning_effort`; the source parser also preserves unknown non-empty values, while
   Luna's catalog additionally advertises `max`. The model catalog/runtime list wins.
4. `none` exists in the shared protocol type but is not advertised by Luna. Whether `none`
   suppresses visible reasoning for Luna is not established and must not be inferred.

## Verification Status

- Luna catalog identifier, default `medium`, and supported `low/medium/high/xhigh/max` - **VERIFIED** - pinned source `models.json#L230-L282`.
- v2 `turn/start.effort` and absence of `thread/start.effort` - **VERIFIED** - pinned protocol source links above.
- Known wire spellings and forward-compatible `Custom` behavior - **VERIFIED** - pinned `openai_models.rs` links above.
- Thread config default plus per-turn override - **VERIFIED** for field shapes/override comments; exact live precedence with an authenticated server - **UNVERIFIED**.
- CLI/config documentation values - **per-docs** - [Config Reference](https://developers.openai.com/codex/config-reference) and [Learn Config Reference](https://learn.chatgpt.com/docs/config-file/config-reference), both list `minimal | low | medium | high | xhigh`; a 0.147.0 binary `--effort` acceptance test was not available.
- Generic unsupported `turn/start` handling and Luna's `none` semantics - **UNVERIFIED** - no direct live call/explicit generic validation path available.

## Open Risks

- Runtime `model/list` may differ by account/provider or release; never hard-code the selector
  without reconciling it with the returned model entry.
- The protocol accepts arbitrary non-empty custom strings, so client-side allowlisting is needed
  to prevent sending `extra_high`, `auto`, or other unsupported values.
- The repository's catalog field names are `supported_reasoning_levels`/`default_reasoning_level`,
  while v2 response names are `supportedReasoningEfforts`/`defaultReasoningEffort`; keep this
  translation explicit.
