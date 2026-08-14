# Review: task T05

## Verdict
APPROVE

## Functional Verification
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend/test_codex_agents_core.py -q` — **11 passed**, 1 pre-existing `APP_ENCRYPTION_KEY` warning.
- `.venv-win/Scripts/python.exe scripts/run_pytest.py tests/backend -q` — **563 passed, 3 skipped**, 10 deprecation warnings.
- Contract probe with `inspect.signature` and `inspect.iscoroutinefunction` — all 7 variants are async and preserve the frozen positional order/defaults.

## Spec Compliance
- The five explainer functions plus segmentador/classifier are async and return the specified tuple shapes; `user_id`/`validator_user_id` occupy the required positions.
- Explainer payload builders/validators and completeness-validator helpers are imported and reused; no `deepseek_client` import exists in `explainer_codex.py` and no agent call is wrapped in `asyncio.to_thread`.
- Codex completeness validation and conversational retries use Codex, preserve the initial source-message prefix, and accumulate validator usage.
- Segmentador and classifier additions are additive; existing `_ds` imports/flows remain present.
- Logs use truncated user IDs and metadata rather than complete source prompts or credentials.
- Test coverage exercises valid full/subpart explainers, invalid payload retry/exhaustion, validated retry/exhaustion, segmentador conversation retry, classifier success, rate-limit mapping, and deterministic timeout propagation (RC-01 resolved).

## Code Quality
- The implementation is a focused async mirror of the existing DeepSeek/OpenRouter patterns and keeps prompt/payload logic centralized.
- No material production defect was found in the reviewed paths.

## Named Risk Checks
- Frozen signatures: verified by runtime introspection; all seven are coroutine functions and match the plan’s positional layout.
- Async boundary: reviewed calls use `await call_codex_chat`; no production `asyncio.to_thread` invocation was found in the T05 agent implementation.
- Completeness validator: `check_explainer_validation_codex` calls Codex with the validator user ID and fail-open behavior; no DeepSeek key/client is used.
- Conversation prefix: tests assert identical initial conversation entries/system prompt and appended assistant/feedback turns.
- Security logging: reviewed log fields contain lengths/previews and `user_id[:8]`; no complete source prompt or credential logging found.
- Regression/scope: full suite passed; segmentador/page_classifier changes are additive in the diff reviewed.

## Required Changes
- `RC-01` | Scope: same-task | Owner hint: `tests/backend/test_codex_agents_core.py` | `tests/backend/test_codex_agents_core.py:283-325` | Problem: the required T05 error matrix lacked deterministic timeout coverage. | Why: the green suite did not demonstrate propagation of the client timeout path without wrapping or remapping it. | Required change: add a deterministic timeout test using the existing fake `slow_turn` scenario, asserting the typed timeout error and user-facing contract. | Status: resolved

## Remediation History
### Round 1
- Implementer report/diff: `plans/chatgpt-codex-auth/task-T05-report.md` (Remediation Round 1); `tests/backend/test_codex_agents_core.py:283-325`
- IDs checked: `RC-01`
- Result: **resolved**. The test uses fake `slow_turn` with a 5-second delay and injects a 0.2-second client timeout; it asserts exact `CodexTimeoutError` propagation and `CODEX_TIMEOUT_MESSAGE`. Focused tests pass 11/11; backend regression passes 563 with 3 skipped.

## Evidence
- Reviewed `plans/chatgpt-codex-auth/task-T05-brief.md`, `task-T05-report.md`, `global-constraints.md` (§Agent variants and §Security invariants), and `plan.md` Cross-task interfaces.
- Reviewed `backend/agents/explainer_codex.py`, the T05 additions in `segmentador.py` and `page_classifier.py`, and `tests/backend/test_codex_agents_core.py` with its fixtures.
- Focused timeout test is present at `tests/backend/test_codex_agents_core.py:283-325`; the requested focused command passes `11 passed`. The requested backend command passes `563 passed, 3 skipped` (the observed count, rather than the report's expected `536`).

## Limitations
- No live Codex app-server or real credentials were used; verification is against the deterministic fake and local client contracts.
