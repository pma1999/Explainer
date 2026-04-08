# OpenRouter Real Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Explainer runs via OpenRouter, accumulate the **real execution cost** returned by OpenRouter (`usage.cost`) into the existing `usage.total_cost` (USD), instead of using hardcoded pricing for those calls.

**Architecture:** Extend the OpenRouter usage wrapper (`OpenRouterUsage`) to carry `cost_usd` parsed from the OpenRouter response payload (`usage.cost`). Update the central usage accumulator in `main.py` to prefer `cost_usd` when present, otherwise fall back to the existing `backend/pricing.py::calculate_cost(...)` estimate.

**Tech Stack:** Python, `requests`, `pytest`, existing in-repo OpenRouter client (`backend/openrouter_client.py`), usage accounting in `main.py`.

---

## Scope & Non-Goals

- **In scope**
  - Parse `usage.cost` from OpenRouter `/chat/completions` responses.
  - Persist/emit the cost through existing `OpenRouterUsage` object.
  - Accumulate this cost into `cumulative_usage["total_cost"]` (USD) in `main.py`.
  - Keep all token accounting unchanged.
  - Add/adjust tests to lock behavior down.

- **Out of scope (for this plan)**
  - Calling `/api/v1/generation` for asynchronous stats (not needed if `usage.cost` is present).
  - Changing UI schema / DB schema (we keep using existing `usage.total_cost`).
  - Reworking `backend/pricing.py` beyond what’s necessary for fallback behavior.

---

## Current Code Map (files we will touch)

**Modify**
- `backend/openrouter_client.py`
  - `class OpenRouterUsage` (currently tokens-only wrapper) at ~L33-L41.
  - OpenRouter response parsing in `call_openrouter_chat_full(...)` where `usage_raw` is used at ~L995-L999.
- `main.py`
  - `_update_usage(...)` cost calculation currently always uses `calculate_cost(...)` at ~L1269-L1296.
- `tests/backend/test_openrouter_client.py`
  - Helper `_success_payload(...)` and tests that assert on usage object behavior.

**No changes expected**
- `backend/agents/explainer_openrouter.py` (it already returns `OpenRouterUsage`).
- `backend/pricing.py` (kept for Gemini and as fallback when `cost_usd` is missing).

---

## Task 1: Add failing tests for OpenRouter `usage.cost` parsing (TDD)

**Files:**
- Modify: `tests/backend/test_openrouter_client.py`

### Why this task exists
We want the plan to be robust: tests should fail until `backend/openrouter_client.py` parses and exposes the cost.

- [ ] **Step 1: Update `_success_payload` helper to optionally include `usage.cost`**

Edit `tests/backend/test_openrouter_client.py` helper at `L31-L47` to accept an optional `cost` argument and include it in returned `usage` when provided.

New helper (full replacement of the function body):

```python
def _success_payload(
    content: str,
    *,
    annotations: list[dict] | None = None,
    cost: float | None = None,
) -> dict:
    message = {"content": content}
    if annotations is not None:
        message["annotations"] = annotations

    usage: dict = {
        "prompt_tokens": 13,
        "completion_tokens": 8,
    }
    if cost is not None:
        usage["cost"] = cost

    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }
```

- [ ] **Step 2: Add a new test asserting `usage.cost_usd` is parsed when present**

Append a new test near other `call_openrouter_chat_*` tests:

```python
def test_call_openrouter_chat_parses_usage_cost_into_usage_object(monkeypatch):
    def _fake_post(url, headers, json, timeout):
        return _make_response(
            status_code=200,
            payload=_success_payload("texto plano", cost=0.00014),
        )

    monkeypatch.setattr(requests, "post", _fake_post)

    content, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve texto",
        api_key="sk-or-v1-test",
        response_format="text",
        max_retries=1,
    )

    assert content == "texto plano"
    assert usage.total_token_count == 21
    assert getattr(usage, "cost_usd") == 0.00014
```

- [ ] **Step 3: Add a test asserting `usage.cost_usd` is `None` when absent**

```python
def test_call_openrouter_chat_sets_cost_usd_none_when_missing(monkeypatch):
    def _fake_post(url, headers, json, timeout):
        return _make_response(
            status_code=200,
            payload=_success_payload("texto plano"),
        )

    monkeypatch.setattr(requests, "post", _fake_post)

    _, usage = call_openrouter_chat(
        messages=[{"role": "user", "content": "Hola"}],
        model="test/model",
        system_prompt="Devuelve texto",
        api_key="sk-or-v1-test",
        response_format="text",
        max_retries=1,
    )

    assert getattr(usage, "cost_usd", None) is None
```

- [ ] **Step 4: Run tests to verify they fail (expected)**

Run:

```bash
pytest tests/backend/test_openrouter_client.py -q
```

Expected: FAIL, because `OpenRouterUsage` currently has no `cost_usd` attribute and no parsing from response.

- [ ] **Step 5: Commit tests**

```bash
git add tests/backend/test_openrouter_client.py
git commit -m "test: cover OpenRouter usage.cost parsing"
```

---

## Task 2: Implement `OpenRouterUsage.cost_usd` and parse it from OpenRouter responses

**Files:**
- Modify: `backend/openrouter_client.py`
- Test: `tests/backend/test_openrouter_client.py`

- [ ] **Step 1: Update `OpenRouterUsage` to include `cost_usd`**

In `backend/openrouter_client.py` at `L33-L41`, update the class to accept and store `cost_usd`.

Replace the class with:

```python
class OpenRouterUsage:
    """Wrapper de usage con atributos compatibles con Gemini para _update_usage."""

    def __init__(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        cost_usd: float | None = None,
    ):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = completion_tokens
        self.thoughts_token_count = 0
        self.tool_use_prompt_token_count = 0
        self.total_token_count = prompt_tokens + completion_tokens
        self.cost_usd = cost_usd
```

- [ ] **Step 2: Parse `usage.cost` inside `call_openrouter_chat_full`**

In `backend/openrouter_client.py` around `L995-L999`, add parsing of `usage_raw.get("cost")` and pass it into `OpenRouterUsage(...)`.

Implementation rules:
- If cost is missing: `cost_usd=None`.
- If cost is present but not numeric: `cost_usd=None` (do not crash the request).
- If numeric: `float(cost)` and round to 6 decimals (consistent with `backend/pricing.py`).

Concrete code to use:

```python
usage_raw = data.get("usage", {})
raw_cost = usage_raw.get("cost")
cost_usd: float | None = None
if isinstance(raw_cost, (int, float)):
    cost_usd = round(float(raw_cost), 6)

usage = OpenRouterUsage(
    prompt_tokens=usage_raw.get("prompt_tokens", 0),
    completion_tokens=usage_raw.get("completion_tokens", 0),
    cost_usd=cost_usd,
)
```

- [ ] **Step 3: Run the OpenRouter client tests**

Run:

```bash
pytest tests/backend/test_openrouter_client.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit implementation**

```bash
git add backend/openrouter_client.py
git commit -m "feat: parse OpenRouter usage.cost into usage wrapper"
```

---

## Task 3: Use real OpenRouter cost in `main.py` usage aggregation

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add real-cost override logic in `_update_usage(...)`**

In `main.py` within `_update_usage` at `L1269-L1296`, replace:

```python
cost = calculate_cost(cost_model, usage_meta)
```

with:

```python
raw_cost_usd = getattr(usage_meta, "cost_usd", None)
if isinstance(raw_cost_usd, (int, float)):
    cost = round(float(raw_cost_usd), 6)
    cost_source = "openrouter_real"
else:
    cost = calculate_cost(cost_model, usage_meta)
    cost_source = "estimated_pricing"
```

Then, in the logger `extra={...}` block, add:

```python
"cost_source": cost_source,
```

This preserves existing behavior for Gemini and for any OpenRouter responses that don’t include cost (fallback).

- [ ] **Step 2: (Optional but recommended) Add a small focused test for `_update_usage` override behavior**

If the repo has unit-testable helpers around `_update_usage`, add a test; if not, skip to avoid brittle integration harness work. (The core correctness is already covered by the OpenRouter client tests + small runtime safety checks here.)

- [ ] **Step 3: Run a fast test pass**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: prefer OpenRouter real cost in usage aggregation"
```

---

## Task 4: End-to-end verification (manual run)

**Files:**
- No code changes expected.

- [ ] **Step 1: Run the live compare pipeline (optional, requires keys & PDF)**

Run:

```bash
python -m tests.test_pipeline_live_neural_compare --openrouter-model minimax/minimax-m2.7
```

Expected:
- The run completes.
- The output JSON in `test_output/live_compare_neural_<run_id>/compare_99_summary.json` includes OpenRouter token usage as before.
- In the main application run (not this test script), `usage.total_cost` should now reflect OpenRouter’s returned `usage.cost` for OpenRouter explainer calls.\n+
---

## Plan Self-Review (performed now)

### Spec coverage
- **“precio hardcodeado”**: Addressed by preferring `OpenRouterUsage.cost_usd` over `calculate_cost(...)` for OpenRouter executions.\n+- **“coste real directamente de la ejecución”**: Achieved by parsing `usage.cost` from OpenRouter response payload (`backend/openrouter_client.py`).\n+- **Streaming note**: Current OpenRouter client uses non-streaming requests; this plan covers the response shape you already parse (`data.get(\"usage\")`). If streaming is introduced later, the same parsing must be applied to the final chunk.\n+
### Placeholder scan
- No `TODO`/`TBD`. All steps include exact code and commands.\n+
### Type consistency
- We consistently use `cost_usd` as the attribute name on `OpenRouterUsage` and check it in `main.py` via `getattr(usage_meta, \"cost_usd\", None)`.\n+
---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-08-openrouter-real-cost.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks\n+2. **Inline Execution** — execute tasks in this session with checkpoints

Which approach?

