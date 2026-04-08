# Parallel Parts Pipeline (k = 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After segmentation, run up to five parts’ agent phases concurrently (bounded by `asyncio.Semaphore(5)`), keep intra-part parallelism unchanged, release the semaphore before spawning each part’s formatter task, and serialize usage accounting with `asyncio.Lock` to avoid races.

**Architecture:** Replace the sequential `for parte in partes_segmentadas` block in `_process_project` (`main.py`) with one coroutine per parte that acquires a shared semaphore around “source prep + `asyncio.gather` of explainers/recorrido/resources + in-memory writes to `partes_contenido[part_id]`”, then returns the background `formatter` `Task` created outside the semaphore. Collect temporary file paths per parte into local lists and merge into `segment_pdf_paths` / `temp_paths` after `asyncio.gather` completes. Wrap all `cumulative_usage` mutations that can run concurrently in `async with usage_lock`.

**Tech Stack:** Python 3.x, FastAPI, `asyncio`, existing Gemini/OpenRouter agents in `backend/agents/`. Spec: `docs/superpowers/specs/2026-04-08-parallel-parts-pipeline-design.md`.

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `main.py` | Modify | `MAX_CONCURRENT_PARTS`, `usage_lock`, `_locked_apply_usage` (or equivalent), nested `async def` for one parte, `asyncio.gather` over partes, merge temp paths, comment on SSE ordering |
| `tests/backend/test_parallel_parts_pipeline.py` | Create | Semaphore concurrency smoke test + import of `MAX_CONCURRENT_PARTS` |

No new production modules; agents and segmentador stay unchanged per spec §5.

---

## Spec coverage (self-review)

| Spec section | Task(s) |
|--------------|---------|
| §3.1 Semaphore + gather | Task 3 |
| §3.2 Semaphore excludes formatter | Task 3 (structure: `create_task` after `async with`) |
| §3.3 Extract coroutine per parte | Task 3 |
| §3.4 `usage_lock`, per-part `partes_contenido` keys, temp path merge | Task 2, Task 3 |
| §3.5 await all formatter tasks | Task 3 (unchanged block after gather) |
| §3.6 constant k = 5 | Task 1 |
| §6 Tests | Task 4 |
| §7 Success criteria | Verified in Task 5 |

---

## Task 1: Add `MAX_CONCURRENT_PARTS` constant

**Files:**
- Modify: `main.py` (after module logger setup, ~lines 94–97)

- [ ] **Step 1: Insert the constant**

Immediately after `logger = get_logger("main")`, add:

```python
# Max concurrent parts in the agent phase (prep + explainer/recorrido/resources); formatters run outside this limit.
MAX_CONCURRENT_PARTS = 5
```

- [ ] **Step 2: Run pytest smoke (no behavior change yet)**

```powershell
cd c:\Users\PcVIP\Documents\Stuff\Explainer
python -m pytest tests/backend/test_main_helpers.py -q
```

Expected: all tests pass (baseline).

- [ ] **Step 3: Commit**

```powershell
git add main.py
git commit -m "feat: add MAX_CONCURRENT_PARTS constant for parallel part pipeline"
```

---

## Task 2: Introduce `usage_lock` and async-safe usage updates

**Files:**
- Modify: `main.py` — inside `_process_project`, immediately after `cumulative_usage = { ... }` and before `def _update_usage(...)` (~lines 1253–1270)

**Rationale:** `_update_usage` mutates `cumulative_usage` and calls `update_project`. Parallel part tasks will call it concurrently; the spec requires a lock (`docs/superpowers/specs/2026-04-08-parallel-parts-pipeline-design.md` §3.4).

- [ ] **Step 1: Add the lock**

Right after `update_project(project_id, user_id, {"usage": cumulative_usage})` that follows the initial `cumulative_usage` dict (the block around lines 1268–1268), insert:

```python
        usage_lock = asyncio.Lock()
```

(Place it **before** `def _update_usage` so nested functions can close over `usage_lock`.)

- [ ] **Step 2: Add async helper to apply one `_update_usage` under the lock**

Still inside `_process_project`, after `_update_usage` is defined, add:

```python
        async def _locked_apply_usage(usage_meta, phase: str = "unknown", *, cost_model: str) -> None:
            async with usage_lock:
                _update_usage(usage_meta, phase=phase, cost_model=cost_model)
```

- [ ] **Step 3: Replace pre-part sequential `_update_usage` calls with await**

Find and replace these **exact call sites** (line numbers may shift after edits):

1. Web extraction: `_update_usage(extraction_usage, phase="web_extraction", cost_model=MODEL_AGENTS)`  
   → `await _locked_apply_usage(extraction_usage, phase="web_extraction", cost_model=MODEL_AGENTS)`

2. Page classifier: `_update_usage(clf_usage, phase="page_classifier", cost_model=MODEL_CLASSIFIER)`  
   → `await _locked_apply_usage(clf_usage, phase="page_classifier", cost_model=MODEL_CLASSIFIER)`

3. Segmentador loop: `_update_usage(usage_meta, phase=phase, cost_model=MODEL_SEGMENTADOR)`  
   → `await _locked_apply_usage(usage_meta, phase=phase, cost_model=MODEL_SEGMENTADOR)`

Each of these runs **before** the parallel part phase; using the lock keeps one consistent pattern and avoids future ordering bugs.

- [ ] **Step 4: Defer part-loop usage batch (implemented in Task 3)**

Do **not** yet replace lines 2063–2085 inside the part loop; Task 3 will replace that whole block with a single `async with usage_lock:` batch that runs all `_update_usage` calls for that parte plus `await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})` inside the same lock scope.

- [ ] **Step 5: Run pytest**

```powershell
python -m pytest tests/backend/test_main_helpers.py tests/backend/test_api.py -q --tb=short
```

Expected: pass. If any test fails, fix before Task 3.

- [ ] **Step 6: Commit**

```powershell
git add main.py
git commit -m "feat: add usage_lock and _locked_apply_usage for thread-safe cumulative usage"
```

---

## Task 3: Extract per-parte coroutine, semaphore, `gather`, merge temp paths

**Files:**
- Modify: `main.py` — replace the sequential `for parte in partes_segmentadas:` loop (approximately lines 1758–2143) with the structure below.

**Behavior to preserve:**

- On the first uncaught exception in any parte task, `asyncio.gather` must raise (default `return_exceptions=False`), cancelling the other in-flight part tasks — matching the old sequential `for` which stopped the loop on first exception.
- `WebExtractionError` raised while building a text parte still aborts processing.
- `formatter_task` is created **only after** exiting `async with part_semaphore` (spec §3.2).
- `segment_pdf_paths.append` and `temp_paths.append` for PDF/text segments must not run concurrently; use local lists inside the per-parte coroutine and extend the master lists after `gather`.

- [ ] **Step 1: Create the semaphore before the coroutine**

After `logger.info(f"[Process] Comenzando procesamiento de {num_partes} partes")`, add:

```python
        part_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PARTS)
```

- [ ] **Step 2: Define nested async function `process_one_parte(parte: dict)`**

Inside `_process_project`, define:

```python
        async def process_one_parte(parte: dict) -> tuple[asyncio.Task, list[str], list[str]]:
            """Run agent phase under part_semaphore; return formatter Task and temp paths to merge."""
            local_segment_pdf_paths: list[str] = []
            local_temp_paths: list[str] = []
```

Move the **entire body** of the old `for parte in partes_segmentadas` loop into this function, with these mechanical edits:

1. **Indent** one level under `process_one_parte`.
2. Replace `segment_pdf_paths.append(...)` with `local_segment_pdf_paths.append(...)` (and the same for `temp_paths` → `local_temp_paths`) everywhere inside this function.
3. Wrap the block from **after** `await send_event(... part_started ...)` through **the end of agent storage** (through the `for result, agent_name in ...` loop that ends with `send_event(... agent_completed ...)`) in:

```python
            async with part_semaphore:
                # part_start = time.time()  — keep at start of this block
                # ... PDF / text / YouTube prep ...
                # ... asyncio.gather explainer + recorrido + resources ...
                # ... assemble explainer ...
                # ... single usage_lock batch (see Step 3) ...
                # ... assign partes_contenido[str(part_id)] for explainer, recorrido, resources ...
                # ... log "Agentes de parte X completados ..."
```

   **Do not** put `_format_and_finalize_part` inside `async with part_semaphore`.

4. **Usage batch inside the semaphore block:** Replace the separate `_update_usage` calls in the subpart loop and recorrido/resources (old lines 2054–2085) with one `async with usage_lock:` block:

```python
                async with usage_lock:
                    for i, sp_result in enumerate(subpart_results):
                        if not isinstance(sp_result, Exception):
                            sp_data, sp_usage = sp_result
                            if sp_usage:
                                _update_usage(
                                    sp_usage,
                                    phase=f"part_{part_id}_explainer_sp{i+1}",
                                    cost_model=explainer_model,
                                )
                    if usage_rec:
                        _update_usage(usage_rec, phase=f"part_{part_id}_recorrido", cost_model=MODEL_AGENTS)
                    if usage_res:
                        _update_usage(usage_res, phase=f"part_{part_id}_resources", cost_model=MODEL_AGENTS)
                    await send_event(project_id, {"type": "usage_update", "usage": cumulative_usage})
```

   Keep the existing `if isinstance(sp_result, Exception): logger.error(...)` **outside** the lock (only the successful branch calls `_update_usage`).

5. **After** `async with part_semaphore` ends, create the formatter task exactly as today:

```python
            formatter_task = asyncio.create_task(
                _format_and_finalize_part(
                    project_id,
                    user_id,
                    api_key,
                    part_id,
                    assembled_explainer,
                    partes_contenido,
                )
            )
            return formatter_task, local_segment_pdf_paths, local_temp_paths
```

6. Add a one-line comment above `process_one_parte` or near `gather`:

```python
        # SSE events may interleave per part_id; clients key off part_id (see spec 2026-04-08).
```

**Critical ordering note:** `part_started` and `update_project` for `"processing"` (lines ~1794–1796 in the current file) stay **before** `async with part_semaphore` so the UI can show a parte as queued/started even when the semaphore is saturated. Do not move those inside the semaphore unless you intentionally want to delay `part_started` until a slot frees (not in spec).

- [ ] **Step 3: Replace the `for` loop with gather + merge**

After `process_one_parte` is defined, replace the old loop with:

```python
        part_results = await asyncio.gather(
            *[process_one_parte(p) for p in partes_segmentadas],
        )
        formatter_tasks: list[asyncio.Task] = []
        for formatter_task, seg_paths, tmp_paths in part_results:
            formatter_tasks.append(formatter_task)
            segment_pdf_paths.extend(seg_paths)
            temp_paths.extend(tmp_paths)
```

Keep the existing block that starts with `# Esperar a que todos los formatters terminen` (lines ~2145–2152) unchanged except for ensuring `formatter_tasks` is populated as above.

- [ ] **Step 4: Run linters / tests**

```powershell
python -m pytest tests/backend/ -q --tb=short
```

If the repo has a full suite:

```powershell
node scripts/run-all-tests.js
```

(Use whatever CI runs locally; minimum: `tests/backend/` and any `test_pdf_process_flow` if present.)

- [ ] **Step 5: Commit**

```powershell
git add main.py
git commit -m "feat: run part agent pipelines with semaphore(5) and merge temp paths safely"
```

---

## Task 4: Add tests for semaphore constant and concurrency pattern

**Files:**
- Create: `tests/backend/test_parallel_parts_pipeline.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for parallel parts pipeline configuration (see spec 2026-04-08)."""

from __future__ import annotations

import asyncio

import pytest


def test_max_concurrent_parts_matches_spec():
    import main

    assert main.MAX_CONCURRENT_PARTS == 5


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_workers():
    """Sanity-check: at most k tasks hold the critical section (same pattern as part_semaphore)."""
    k = 5
    sem = asyncio.Semaphore(k)
    active = 0
    max_active = 0

    async def worker() -> None:
        nonlocal active, max_active
        async with sem:
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*[worker() for _ in range(25)])
    assert max_active <= k
```

- [ ] **Step 2: Run tests**

```powershell
python -m pytest tests/backend/test_parallel_parts_pipeline.py -v
```

Expected: PASS (2 passed).

- [ ] **Step 3: Commit**

```powershell
git add tests/backend/test_parallel_parts_pipeline.py
git commit -m "test: add parallel parts pipeline constants and semaphore sanity check"
```

---

## Task 5: Manual verification and merge checklist

**Files:** none (operational)

- [ ] **Step 1: Single-part PDF regression**

Run the smallest local integration path you use (e.g. existing demo script or manual upload) with a project that segments to **one** parte. Confirm project reaches `completed` and `partes_contenido` has one key with `status: completed`.

- [ ] **Step 2: Multi-part PDF**

Use a PDF that segments to **≥ 6** partes. Observe logs: multiple `"ejecutando agentes en paralelo"` lines may interleave; wall-clock should drop versus sequential (rough check). Confirm all partes end `completed`.

- [ ] **Step 3: Usage sanity**

Inspect `usage` in DB or API response: `total_tokens` / `total_cost` should be finite and consistent (no negative values, no obvious double-count from races).

- [ ] **Step 4: Final commit (if only doc updates)**

If you add nothing else, skip. Otherwise commit any fixups.

---

## Placeholder scan (self-review)

- No TBD/TODO left in tasks.
- `process_one_parte` return type `tuple[asyncio.Task, list[str], list[str]]` matches unpack in Task 3.
- `_locked_apply_usage` name used consistently; part-loop uses raw `_update_usage` only inside `async with usage_lock` batch.
- Spec §3.4 “merge temp paths after gather” covered in Task 3 Step 3.
- **Ordering:** `part_started` / `status: processing` remain before semaphore (documented in Task 3 Step 2).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-08-parallel-parts-pipeline.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach do you want?
