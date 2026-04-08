# Lightweight projects list + safe merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve `GET /api/projects` as memory-cheap list summaries (no `partes_contenido` / `source_text`), add `list_summary: true`, and merge server summaries with local backup without dropping offline bodies—preventing OOM on small instances while keeping AI pipeline parallelism unchanged.

**Architecture:** Supabase `select` with an explicit column list for the list path only; full `select("*")` remains for `get_project`, export, and all mutations. The frontend `mergeProjects` applies timestamp wins, with a special case: when the newer side is a server `list_summary`, copy `partes_contenido` and `source_text` from the older local object when those keys are absent on the server payload, then strip `list_summary` before the merged object is stored.

**Tech stack:** Python 3 / FastAPI / supabase-py, JavaScript (Vitest), Pydantic JSON responses.

---

## File map

| File | Role |
|------|------|
| `backend/supabase_data.py` | Add `_row_to_list_summary`, `list_projects_summary`; keep `list_projects` as full-row list for `export_projects_payload` only. |
| `main.py` | Import and call `list_projects_summary` from `api_list_projects`. |
| `frontend/js/storage.js` | Replace naive `mergeProjects` timestamp pick with `mergePairProjects` + summary-aware merge; export if needed for tests. |
| `tests/backend/test_api.py` or new `tests/backend/test_projects_list.py` | API test with mocked data layer. |
| `tests/frontend/storage.test.js` | Three merge scenarios from spec. |
| `docs/superpowers/specs/2026-04-08-lightweight-projects-list-design.md` | Set **Estado** to *Aprobado* after implementation (optional doc commit). |

**Invariant (must not regress):** `export_projects_payload` in `supabase_data.py` must keep calling **`list_projects`** (full rows), not the summary function.

---

### Task 1: Backend — list summary row builder + query

**Files:**
- Modify: `backend/supabase_data.py` (after `_row_to_project`, before `get_project`)
- Test: none yet (Task 2)

- [ ] **Step 1: Add constants and helpers**

Insert immediately after `_row_to_project` (after line 58, before `create_project`):

```python
# Columns for GET /api/projects list — omits heavy JSON blobs (OOM on small instances).
PROJECT_LIST_SUMMARY_SELECT = (
    "id,name,description,pdf_filename,source_type,source_url,source_metadata,"
    "file_uri,status,segmentation,usage,reading_progress,error_message,"
    "share_token,created_at,updated_at"
)


def _row_to_list_summary(row: dict[str, Any]) -> dict[str, Any]:
    """API list item: same shape as project minus heavy fields; marks list_summary."""
    result: dict[str, Any] = {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "pdf_filename": row["pdf_filename"],
        "source_type": row.get("source_type", "pdf"),
        "source_url": row.get("source_url"),
        "source_metadata": row.get("source_metadata") or {},
        "file_uri": row.get("file_uri"),
        "status": row["status"],
        "segmentation": row.get("segmentation"),
        "usage": row.get("usage") or {},
        "reading_progress": row.get("reading_progress") or {},
        "error_message": row.get("error_message"),
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else str(row["created_at"]),
        "updated_at": row["updated_at"].isoformat()
        if hasattr(row["updated_at"], "isoformat")
        else str(row["updated_at"]),
        "list_summary": True,
    }
    if "share_token" in row:
        result["share_token"] = row.get("share_token")
    return result


def list_projects_summary(user_id: str) -> list[dict[str, Any]]:
    """List projects for user (newest first) without partes_contenido or source_text."""
    client = _client()
    r = (
        client.table("projects")
        .select(PROJECT_LIST_SUMMARY_SELECT)
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return [_row_to_list_summary(row) for row in (r.data or [])]
```

- [ ] **Step 2: Leave `list_projects` unchanged**

Confirm `list_projects` still uses `.select("*")` and `_row_to_project` — `export_projects_payload` depends on it.

- [ ] **Step 3: Commit**

```bash
git add backend/supabase_data.py
git commit -m "feat(backend): add list_projects_summary without heavy project columns"
```

---

### Task 2: Wire FastAPI list endpoint

**Files:**
- Modify: `main.py` (imports + `api_list_projects`)

- [ ] **Step 1: Update imports**

Replace `list_projects` import from `backend.supabase_data` with:

```python
    list_projects_summary,
```

(Remove `list_projects` from imports unless used elsewhere in `main.py` — it is not; only export uses it inside supabase_data.)

- [ ] **Step 2: Change handler**

Replace the body of `api_list_projects`:

```python
@app.get("/api/projects")
async def api_list_projects(user_id: Annotated[str, Depends(get_current_user_id)]):
    return list_projects_summary(user_id)
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(api): return lightweight project list for GET /api/projects"
```

---

### Task 3: Backend test — list endpoint contract

**Files:**
- Create: `tests/backend/test_projects_list.py`

- [ ] **Step 1: Write failing test**

Create `tests/backend/test_projects_list.py`:

```python
"""GET /api/projects returns list_summary items without heavy keys."""

from unittest.mock import patch

import pytest

from main import app
from backend.auth import get_current_user_id


@pytest.fixture
def client():
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


def _override_user(user_id: str):
    def _():
        return user_id
    return _


class TestListProjectsSummary:
    def test_list_excludes_heavy_fields_and_sets_flag(self, client):
        app.dependency_overrides[get_current_user_id] = _override_user("user-1")
        try:
            with patch("main.list_projects_summary", return_value=[
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "name": "P1",
                    "description": "",
                    "pdf_filename": "a.pdf",
                    "source_type": "pdf",
                    "source_url": None,
                    "source_metadata": {},
                    "file_uri": None,
                    "status": "completed",
                    "segmentation": {"partes": [{"numero": 1}]},
                    "usage": {},
                    "reading_progress": {},
                    "error_message": None,
                    "share_token": None,
                    "created_at": "2024-01-01T12:00:00",
                    "updated_at": "2024-01-02T12:00:00",
                    "list_summary": True,
                }
            ]):
                r = client.get("/api/projects", headers={"Authorization": "Bearer fake"})
        finally:
            app.dependency_overrides.pop(get_current_user_id, None)

        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["list_summary"] is True
        assert "partes_contenido" not in data[0]
        assert "source_text" not in data[0]
```

- [ ] **Step 2: Run test — expect FAIL** if Task 2 not applied (import error). After Task 2, expect **PASS**.

Run:

```powershell
cd c:\Users\PcVIP\Documents\Stuff\Explainer
python -m pytest tests/backend/test_projects_list.py -v
```

Expected: `1 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_projects_list.py
git commit -m "test(backend): assert GET /api/projects list_summary contract"
```

---

### Task 4: Frontend — summary-aware `mergeProjects`

**Files:**
- Modify: `frontend/js/storage.js`
- Modify: `tests/frontend/storage.test.js`

- [ ] **Step 1: Add helpers and replace `mergeProjects`**

At top of `storage.js` after imports, add:

```javascript
function _projectTimeMs(project) {
  return new Date(project.updated_at || project.created_at || 0).getTime();
}

/**
 * Merge two project records for the same id. Prefers newer updated_at.
 * If the newer record is a server list_summary, preserve partes_contenido and source_text from the older record when missing on the newer.
 */
export function mergePairProjects(a, b) {
  const ta = _projectTimeMs(a);
  const tb = _projectTimeMs(b);
  let newer;
  let older;
  if (tb > ta) {
    newer = b;
    older = a;
  } else if (ta > tb) {
    newer = a;
    older = b;
  } else {
    return b;
  }

  if (!newer.list_summary) {
    return newer;
  }

  const out = { ...newer };
  if (!Object.prototype.hasOwnProperty.call(newer, 'partes_contenido') && older && Object.prototype.hasOwnProperty.call(older, 'partes_contenido')) {
    out.partes_contenido = older.partes_contenido;
  }
  if (!Object.prototype.hasOwnProperty.call(newer, 'source_text') && older && Object.prototype.hasOwnProperty.call(older, 'source_text')) {
    out.source_text = older.source_text;
  }
  delete out.list_summary;
  return out;
}
```

Replace the entire `mergeProjects` function with:

```javascript
export function mergeProjects(serverProjects = [], localProjects = []) {
  const byId = new Map();
  [...localProjects, ...serverProjects].forEach((project) => {
    if (!project || !project.id) return;
    const current = byId.get(project.id);
    if (!current) {
      byId.set(project.id, project);
      return;
    }
    byId.set(project.id, mergePairProjects(current, project));
  });

  return Array.from(byId.values()).sort(
    (a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime(),
  );
}
```

- [ ] **Step 2: Add Vitest tests** — append inside `describe('mergeProjects', ...)` in `tests/frontend/storage.test.js`:

Add tests:

```javascript
    it('when newer server is list_summary, keeps local partes_contenido and drops list_summary', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-01T00:00:00Z',
        partes_contenido: { 1: { explainer: { foo: 'bar' } } },
        source_text: 'cached',
      };
      const server = {
        id: '1',
        name: 'Renamed',
        status: 'completed',
        updated_at: '2024-01-05T00:00:00Z',
        list_summary: true,
        segmentation: { partes: [{ numero: 1 }] },
      };
      const merged = mergeProjects([server], [local]);
      expect(merged).toHaveLength(1);
      const p = merged[0];
      expect(p.name).toBe('Renamed');
      expect(p.list_summary).toBeUndefined();
      expect(p.partes_contenido).toEqual({ 1: { explainer: { foo: 'bar' } } });
      expect(p.source_text).toBe('cached');
    });

    it('when local is newer, keeps local unchanged', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-10T00:00:00Z',
        partes_contenido: { 1: {} },
      };
      const server = {
        id: '1',
        name: 'Server',
        updated_at: '2024-01-05T00:00:00Z',
        list_summary: true,
      };
      const merged = mergeProjects([server], [local]);
      expect(merged[0].name).toBe('Local');
      expect(merged[0].partes_contenido).toEqual({ 1: {} });
    });

    it('when newer server is full object, server wins entire record', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-01T00:00:00Z',
        partes_contenido: { 1: { old: true } },
      };
      const server = {
        id: '1',
        name: 'Server',
        updated_at: '2024-01-08T00:00:00Z',
        partes_contenido: { 1: { new: true } },
      };
      const merged = mergeProjects([server], [local]);
      expect(merged[0].partes_contenido).toEqual({ 1: { new: true } });
    });
```

Add a small `describe('mergePairProjects', ...)` with one tie-breaker test if desired; optional.

- [ ] **Step 3: Run Vitest**

```powershell
cd c:\Users\PcVIP\Documents\Stuff\Explainer
npm run test -- tests/frontend/storage.test.js
```

Expected: all tests in file **pass** (including new ones).

- [ ] **Step 4: Commit**

```bash
git add frontend/js/storage.js tests/frontend/storage.test.js
git commit -m "fix(storage): merge list_summary server rows without losing offline bodies"
```

---

### Task 5: Regression sweep — callers of `/api/projects`

**Files:**
- Read-only verification: `frontend/js/storage.js` (`ensureProjectsFetched`), `frontend/js/sse.js`, `frontend/js/projects.js`

- [ ] **Step 1: Confirm navigation loads full project**

In `projects.js`, opening a project must still call `GET /api/projects/{id}` (already does per codebase grep). No code change if confirmed.

- [ ] **Step 2: Run full backend + frontend unit tests**

```powershell
python -m pytest tests/backend -v
npm run test
```

Expected: **0 failures**.

- [ ] **Step 3: Commit** (only if a fix was needed; else skip)

---

### Task 6: Documentation sync

**Files:**
- Modify: `docs/superpowers/specs/2026-04-08-lightweight-projects-list-design.md`

- [ ] **Step 1: Set `Estado:` to `Aprobado`**

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-04-08-lightweight-projects-list-design.md
git commit -m "docs: mark lightweight list spec as approved"
```

---

## Why this prevents recurrence

| Mechanism | Effect |
|-----------|--------|
| No heavy columns in list query | Worker does not allocate giant dicts for every project on each list request — main OOM driver removed. |
| `list_summary` + merge rules | Backup/offline never drops `partes_contenido` when the server only sent metadata. |
| Export unchanged | Full export still loads complete rows via `list_projects` + `select("*")`. |
| AI pipeline untouched | No change to `MAX_CONCURRENT_PARTS` or agent threads — spec scope preserved. |

**Operational note:** If OOM persists after this ships, next suspects are concurrent **full** `GET /api/projects/:id` on huge JSON, or background processing memory — track separately; this plan addresses list-path OOM per spec.

---

## Self-review (plan vs spec)

| Spec section | Task covering it |
|--------------|------------------|
| 3.1 API contract (`list_summary`, exclude heavy fields) | Tasks 1–3 |
| 3.2 `list_projects_summary` + explicit select | Task 1 |
| 3.3 Client merge rules | Task 4 |
| 3.4 No AI parallelism change | Implicit (no main.py pipeline edits) |
| 4 Tests backend + frontend | Tasks 3–4 |
| Export/import contract | Task 1 invariant + Task 5 |
| Criterio éxito memoria | Addressed by column omission |

**Placeholder scan:** No TBD/TODO in steps; code blocks are complete.

**Type/name consistency:** `list_projects_summary` in `main` import matches `supabase_data`; `mergePairProjects` exported for tests optional — if not exported, tests only use `mergeProjects` (already covered by three new tests).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-08-lightweight-projects-list.md`.

**Two execution options:**

1. **Subagent-driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`.

2. **Inline execution** — Run tasks in this session with checkpoints. **REQUIRED SUB-SKILL:** `superpowers:executing-plans`.

**Which approach?**
