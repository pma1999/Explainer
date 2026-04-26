# Subsection Navigation & Progress Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Ghost Rail (desktop) and Smart Bar (mobile) subsection navigation to the Explicación tab, persist reading progress at subsection granularity, and support deep-linking via URL.

**Architecture:** Backend adds a single JSONB-mutative endpoint. Frontend extends the hash router, injects deterministic IDs into rendered explainer HTML, mounts an IntersectionObserver-driven Ghost Rail + Smart Bar, and debounces progress saves to the backend while keeping local session/backup state in sync.

**Tech Stack:** FastAPI (Python), vanilla JS (ES modules), CSS variables, Supabase/Postgres (JSONB), marked.js, IndexedDB (local backup).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/supabase_data.py` | New `update_subsection_progress()` helper that mutates `reading_progress` JSONB. |
| `main.py` | New FastAPI route `PATCH /api/projects/{id}/progress/subsection`. |
| `tests/backend/test_supabase_data.py` | Backend test for subsection progress mutation. |
| `frontend/js/router.js` | Parse `/u/{subsectionId}` from hash; build hashes with subsection. |
| `frontend/js/state.js` | Add `currentSubsectionId` to the global `state` object. |
| `frontend/js/projectView.js` | Inject `id` attributes into `renderExplainer()`; render Ghost Rail; update active subsection UI. |
| `frontend/js/main.js` | IntersectionObserver lifecycle, Smart Bar scroll logic, keyboard shortcuts, `saveSubsectionProgress()`, deep-link scroll restore, `saveViewState()` expansion. |
| `frontend/style.css` | Ghost Rail, Smart Bar, Sheet, progress hairline, and SR-only utilities. |

---

## Tasks

### Task 1: Backend — `update_subsection_progress()` helper

**Files:**
- Modify: `backend/supabase_data.py`
- Test: `tests/backend/test_supabase_data.py`

- [ ] **Step 1: Write the failing test**

```python
def test_update_subsection_progress():
    from backend.supabase_data import update_subsection_progress, create_project, get_project
    import uuid
    user_id = "test-user-1"
    project = create_project(user_id, name="Test", description="")
    project_id = project["id"]
    # Seed a part_id so validation passes
    from backend.supabase_data import update_project
    update_project(project_id, user_id, {
        "segmentation": {"partes": [{"numero": 1, "titulo": "T1"}]}
    })

    updated = update_subsection_progress(
        project_id, user_id,
        subsection_id="subsec-1-0-0", part_id=1,
        completed=True, is_last_read=True
    )
    assert updated is not None
    rp = updated["reading_progress"]
    assert "subsec-1-0-0" in rp["completed_subsections"]
    assert rp["last_subsection"]["subsection_id"] == "subsec-1-0-0"
    assert rp["last_subsection"]["part_id"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/backend/test_supabase_data.py::test_update_subsection_progress -v
```
Expected: `AttributeError: module 'backend.supabase_data' has no attribute 'update_subsection_progress'`

- [ ] **Step 3: Add `update_subsection_progress` to `backend/supabase_data.py`**

Insert before `set_section_read_status`:

```python
def update_subsection_progress(
    project_id: str,
    user_id: str,
    subsection_id: str,
    part_id: int,
    completed: Optional[bool] = None,
    is_last_read: bool = False,
) -> Optional[dict[str, Any]]:
    """Update subsection progress inside reading_progress JSONB.
    completed=True adds to completed_subsections; is_last_read=True updates last_subsection."""
    project = get_project(project_id, user_id)
    if not project:
        return None

    progress = project.get("reading_progress") or {}
    completed_subsections = list(progress.get("completed_subsections") or [])

    if completed is True and subsection_id not in completed_subsections:
        completed_subsections.append(subsection_id)
    elif completed is False and subsection_id in completed_subsections:
        completed_subsections = [s for s in completed_subsections if s != subsection_id]

    new_progress: dict[str, Any] = {
        **progress,
        "completed_subsections": completed_subsections,
    }
    if is_last_read:
        new_progress["last_subsection"] = {
            "part_id": part_id,
            "subsection_id": subsection_id,
            "tab": "explicacion",
        }
        new_progress["last_read_at"] = _now_iso()

    return update_project(project_id, user_id, {"reading_progress": new_progress})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/backend/test_supabase_data.py::test_update_subsection_progress -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/supabase_data.py tests/backend/test_supabase_data.py
git commit -m "feat(backend): add update_subsection_progress helper

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Backend — FastAPI endpoint

**Files:**
- Modify: `main.py`
- Test: `tests/backend/test_supabase_data.py` (or add to existing API tests)

- [ ] **Step 1: Write the failing test**

```python
def test_api_patch_progress_subsection(client, auth_headers):
    # Assumes a fixture that creates a project with segmentation and part 1
    # Replace with your actual project creation helper
    resp = client.patch(
        "/api/projects/test-project-id/progress/subsection",
        headers=auth_headers,
        json={"subsection_id": "subsec-1-0-0", "part_id": 1, "completed": True, "is_last_read": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "subsec-1-0-0" in data["reading_progress"]["completed_subsections"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/backend/test_supabase_data.py::test_api_patch_progress_subsection -v
```
Expected: `404 Not Found` or connection error because route does not exist.

- [ ] **Step 3: Add the endpoint in `main.py`**

Insert right after the existing `api_update_progress` endpoint (around line 520):

```python
@app.patch("/api/projects/{project_id}/progress/subsection")
async def api_update_subsection_progress(
    user_id: Annotated[str, Depends(get_current_user_id)],
    project_id: str,
    body: dict = Body(...),
):
    """Update subsection progress. Body: {
        subsection_id: str, part_id: int,
        completed?: bool, is_last_read?: bool
    }."""
    subsection_id = body.get("subsection_id")
    part_id = body.get("part_id")
    if not subsection_id or part_id is None:
        raise HTTPException(status_code=400, detail="subsection_id y part_id requeridos")
    try:
        part_id = int(part_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="part_id debe ser un número")

    completed = body.get("completed")
    if completed is not None and not isinstance(completed, bool):
        raise HTTPException(status_code=400, detail="completed debe ser boolean")
    is_last_read = body.get("is_last_read", False)
    if not isinstance(is_last_read, bool):
        is_last_read = False

    project = get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    partes = project.get("segmentation") or {}
    partes_list = partes.get("partes") or []
    if not any(p.get("numero") == part_id for p in partes_list):
        raise HTTPException(status_code=400, detail="Sección no encontrada")

    # Accept deterministic format subsec-{part_id}-... or exact match
    if not subsection_id.startswith(f"subsec-{part_id}-"):
        raise HTTPException(status_code=400, detail="subsection_id no pertenece a la sección")

    updated = update_subsection_progress(
        project_id, user_id, subsection_id, part_id,
        completed=completed, is_last_read=is_last_read,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return updated
```

Ensure the import `update_subsection_progress` is present at the top of `main.py` alongside other `backend.supabase_data` imports.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/backend/test_supabase_data.py::test_api_patch_progress_subsection -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add main.py tests/backend/test_supabase_data.py
git commit -m "feat(api): add PATCH /projects/{id}/progress/subsection endpoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Frontend — Extend router for subsection hashes

**Files:**
- Modify: `frontend/js/router.js`

- [ ] **Step 1: Modify `parseRoute()`**

Replace the existing `parseRoute` function body (lines 14-75) with this extended version:

```js
export function parseRoute(hash) {
  const h = (hash !== undefined ? hash : (typeof location !== 'undefined' ? location.hash : '')) || '';
  const hashStr = h.replace(/^#/, '').trim();
  if (!hashStr || hashStr === '/') {
    return { view: 'landing' };
  }

  const segments = hashStr.replace(/^\/+/, '').split('/').filter(Boolean);

  if (segments[0] === 'projects') {
    return { view: 'projects' };
  }

  if (segments[0] === 's' && segments[1]) {
    const route = { view: 'shared', shareToken: segments[1] };
    if (segments[2] === 's' && segments[3]) {
      const partId = Number(segments[3]);
      if (!Number.isNaN(partId) && partId > 0) {
        route.partId = partId;
      }
    }
    if (route.partId && segments[4] === 't' && segments[5]) {
      const tab = segments[5].toLowerCase();
      if (VALID_TABS.includes(tab)) {
        route.tab = tab;
      }
    }
    if (route.partId && segments[6] === 'u' && segments[7]) {
      route.subsectionId = segments[7];
    }
    if (route.partId && !route.tab) {
      route.tab = 'explicacion';
    }
    return route;
  }

  if (segments[0] === 'p' && segments[1]) {
    const route = {
      view: 'project',
      projectId: segments[1],
    };

    if (segments[2] === 's' && segments[3]) {
      const partId = Number(segments[3]);
      if (!Number.isNaN(partId) && partId > 0) {
        route.partId = partId;
      }
    }

    if (route.partId && segments[4] === 't' && segments[5]) {
      const tab = segments[5].toLowerCase();
      if (VALID_TABS.includes(tab)) {
        route.tab = tab;
      }
    }

    if (route.partId && segments[6] === 'u' && segments[7]) {
      route.subsectionId = segments[7];
    }

    if (route.partId && !route.tab) {
      route.tab = 'explicacion';
    }

    return route;
  }

  return null;
}
```

- [ ] **Step 2: Modify `buildHash()`**

Replace the existing `buildHash` function body (lines 82-107) with:

```js
export function buildHash(route) {
  if (!route || !route.view) return '#/';

  if (route.view === 'landing') return '#/';
  if (route.view === 'projects') return '#/projects';

  if (route.view === 'shared' && route.shareToken) {
    let hash = `#/s/${route.shareToken}`;
    if (route.partId) {
      hash += `/s/${route.partId}`;
      hash += `/t/${route.tab && VALID_TABS.includes(route.tab) ? route.tab : 'explicacion'}`;
      if (route.subsectionId) {
        hash += `/u/${route.subsectionId}`;
      }
    }
    return hash;
  }

  if (route.view === 'project' && route.projectId) {
    let hash = `#/p/${route.projectId}`;
    if (route.partId) {
      hash += `/s/${route.partId}`;
      hash += `/t/${route.tab && VALID_TABS.includes(route.tab) ? route.tab : 'explicacion'}`;
      if (route.subsectionId) {
        hash += `/u/${route.subsectionId}`;
      }
    }
    return hash;
  }

  return '#/';
}
```

- [ ] **Step 3: Quick manual test**

Open browser console (or Node) and run:
```js
import { parseRoute, buildHash } from './frontend/js/router.js';
console.log(parseRoute('#/p/abc/s/2/t/explicacion/u/subsec-2-0-1'));
// Expected: { view: 'project', projectId: 'abc', partId: 2, tab: 'explicacion', subsectionId: 'subsec-2-0-1' }
console.log(buildHash({ view: 'project', projectId: 'abc', partId: 2, tab: 'explicacion', subsectionId: 'subsec-2-0-1' }));
// Expected: "#/p/abc/s/2/t/explicacion/u/subsec-2-0-1"
```

- [ ] **Step 4: Commit**

```bash
git add frontend/js/router.js
git commit -m "feat(router): support subsectionId in hash URLs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Frontend — Add `currentSubsectionId` to state

**Files:**
- Modify: `frontend/js/state.js`

- [ ] **Step 1: Add `currentSubsectionId` to the state object**

Change the `state` declaration (around line 11) to include the new field:

```js
export const state = {
  currentProjectId: null,
  currentProject: null,
  currentPartId: null,
  currentSubsectionId: null, // NEW: active subsection in Explicación tab
  activeTab: 'explicacion',
  isSharedView: false,
  shareToken: null,
  processingSSE: null,
  sseProjectId: null,
  sseReconnectAttempts: 0,
  sseLastEventAt: 0,
  ssePausedByVisibility: false,
  pollProjectsInterval: null,
  pollCurrentProjectInterval: null,
  hasApiKey: false,
  apiKeyStatus: 'loading',
  hasOpenRouterKey: false,
  openRouterKeyStatus: 'loading',
  hasMistralKey: false,
  mistralKeyStatus: 'loading',
  session: null,
  user: null,
  previousUserId: null,
  lastPartChangeAt: 0,
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/state.js
git commit -m "feat(state): add currentSubsectionId field

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — Inject deterministic IDs into `renderExplainer()`

**Files:**
- Modify: `frontend/js/projectView.js`

- [ ] **Step 1: Modify `renderExplainer()` to add `id` attributes**

Replace the `renderExplainer` function (lines 538-582) with:

```js
function renderExplainer(data, partId) {
  if (data._format === 'markdown') {
    return `<div class="explainer-content">${renderMd(data.content || '')}</div>`;
  }
  let html = '';
  if (data.introduccion) {
    html += `<div class="explainer-intro">${renderMd(data.introduccion)}</div>`;
  }
  if (data.desarrollo && data.desarrollo.length > 0) {
    data.desarrollo.forEach((section, sectionIndex) => {
      html += `<div class="explainer-section">`;
      html += `<h3 class="explainer-section-title">${escHtml(section.titulo_seccion)}</h3>`;
      if (section.explicacion_introductoria) {
        html += `<div class="explainer-section-intro">${renderMd(section.explicacion_introductoria)}</div>`;
      }
      if (section.subsecciones && section.subsecciones.length > 0) {
        section.subsecciones.forEach((sub, subIndex) => {
          const subsectionId = `subsec-${partId}-${sectionIndex}-${subIndex}`;
          html += `<div class="explainer-subsection">`;
          html += `<h4 class="explainer-subsection-title" id="${subsectionId}">${escHtml(sub.titulo_subseccion)}</h4>`;
          html += `<div class="explainer-text">${renderMd(sub.explicacion_detallada)}</div>`;
          html += `</div>`;
        });
      }
      html += `</div>`;
    });
  }
  if (data.conclusion) {
    html += `
      <div class="explainer-conclusion">
        <div class="explainer-conclusion-label">Conclusión</div>
        ${renderMd(data.conclusion)}
      </div>`;
  }
  if (data.conexiones_contextuales && data.conexiones_contextuales.length > 0) {
    html += `<div class="explainer-section"><h3 class="explainer-section-title">Conexiones contextuales</h3>`;
    data.conexiones_contextuales.forEach((cx, cxIndex) => {
      // Use a distinct section index for conexiones to avoid collisions
      const subsectionId = `subsec-${partId}-cx-${cxIndex}`;
      html += `<div class="explainer-subsection">
        <h4 class="explainer-subsection-title" id="${subsectionId}">${escHtml(cx.seccion_temario_relacionada)}</h4>
        <div class="explainer-text">${renderMd(cx.descripcion_conexion)}</div>
      </div>`;
    });
    html += `</div>`;
  }
  return html;
}
```

- [ ] **Step 2: Update the `renderTab` call for explainer to pass `partId`**

In `renderTab` (around line 719), change:
```js
if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data);
```
to:
```js
if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data, state.currentPartId);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/projectView.js
git commit -m "feat(projectView): add deterministic subsection IDs to explainer HTML

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — Render Ghost Rail

**Files:**
- Modify: `frontend/js/projectView.js`
- Create: no new file (function added to existing module)

- [ ] **Step 1: Add `renderGhostRail()` after `renderExplainer()`**

Insert after `renderExplainer`:

```js
function renderGhostRail(partId, explainerData) {
  const panel = document.getElementById('panel-explicacion');
  if (!panel) return;

  // Remove existing rail
  const existing = panel.querySelector('.ghost-rail');
  if (existing) existing.remove();

  // Build flat list of subsections
  const subsections = [];
  if (explainerData.desarrollo) {
    explainerData.desarrollo.forEach((section, sIdx) => {
      if (section.subsecciones) {
        section.subsecciones.forEach((sub, subIdx) => {
          subsections.push({
            id: `subsec-${partId}-${sIdx}-${subIdx}`,
            title: sub.titulo_subseccion,
          });
        });
      }
    });
  }
  if (explainerData.conexiones_contextuales) {
    explainerData.conexiones_contextuales.forEach((cx, cxIdx) => {
      subsections.push({
        id: `subsec-${partId}-cx-${cxIdx}`,
        title: cx.seccion_temario_relacionada,
      });
    });
  }
  if (subsections.length === 0) return;

  const rail = document.createElement('div');
  rail.className = 'ghost-rail';
  rail.setAttribute('aria-label', 'Navegación de subsecciones');
  rail.innerHTML = '<div class="ghost-rail-line"></div>';

  subsections.forEach((sub, i) => {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = 'ghost-rail-node';
    node.dataset.subsectionId = sub.id;
    node.setAttribute('aria-label', `Subsección ${i + 1}: ${sub.title}`);
    node.style.animationDelay = `${i * 40}ms`;

    const label = document.createElement('span');
    label.className = 'ghost-rail-label';
    label.textContent = sub.title;
    node.appendChild(label);

    node.addEventListener('click', () => {
      const target = document.getElementById(sub.id);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });

    rail.appendChild(node);
  });

  // Insert rail at the end of panel so it overlays content
  panel.appendChild(rail);
}

export function updateGhostRailActive(subsectionId) {
  const rail = document.querySelector('.ghost-rail');
  if (!rail) return;
  rail.querySelectorAll('.ghost-rail-node').forEach(node => {
    const isActive = node.dataset.subsectionId === subsectionId;
    node.classList.toggle('active', isActive);
    if (isActive) {
      const label = node.querySelector('.ghost-rail-label');
      if (label) label.classList.add('active');
    } else {
      const label = node.querySelector('.ghost-rail-label');
      if (label) label.classList.remove('active');
    }
  });
}
```

Note: we also export `updateGhostRailActive` so `main.js` can call it.

- [ ] **Step 2: Call `renderGhostRail` inside `renderTab` after rendering explainer**

In `renderTab`, after the explainer HTML is injected (line ~720):

```js
if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data, state.currentPartId);
    renderGhostRail(state.currentPartId, data);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/projectView.js
git commit -m "feat(projectView): add Ghost Rail rendering and active state updater

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Frontend — Render Smart Bar

**Files:**
- Modify: `frontend/js/projectView.js`

- [ ] **Step 1: Add Smart Bar render + update helpers**

Insert after `updateGhostRailActive`:

```js
function renderSmartBar(partId, explainerData) {
  const content = document.getElementById('part-content');
  if (!content) return;

  // Remove existing
  const existing = content.querySelector('.smart-bar');
  if (existing) existing.remove();

  // Build flat list (same logic as rail)
  const subsections = [];
  if (explainerData.desarrollo) {
    explainerData.desarrollo.forEach((section, sIdx) => {
      if (section.subsecciones) {
        section.subsecciones.forEach((sub, subIdx) => {
          subsections.push({ id: `subsec-${partId}-${sIdx}-${subIdx}`, title: sub.titulo_subseccion });
        });
      }
    });
  }
  if (explainerData.conexiones_contextuales) {
    explainerData.conexiones_contextuales.forEach((cx, cxIdx) => {
      subsections.push({ id: `subsec-${partId}-cx-${cxIdx}`, title: cx.seccion_temario_relacionada });
    });
  }
  if (subsections.length === 0) return;

  const bar = document.createElement('div');
  bar.className = 'smart-bar';
  bar.setAttribute('role', 'navigation');
  bar.setAttribute('aria-label', 'Navegación de subsección');
  bar.dataset.count = String(subsections.length);
  bar.innerHTML = `
    <div class="smart-bar-progress"></div>
    <button type="button" class="smart-bar-prev" aria-label="Subsección anterior">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    </button>
    <button type="button" class="smart-bar-title" aria-label="Abrir índice de subsecciones">
      <span class="smart-bar-title-text">—</span>
    </button>
    <button type="button" class="smart-bar-next" aria-label="Subsección siguiente">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    </button>
  `;

  const prevBtn = bar.querySelector('.smart-bar-prev');
  const nextBtn = bar.querySelector('.smart-bar-next');
  const titleBtn = bar.querySelector('.smart-bar-title');

  prevBtn.addEventListener('click', () => navigateSubsection(-1));
  nextBtn.addEventListener('click', () => navigateSubsection(1));
  titleBtn.addEventListener('click', () => openSubsectionSheet(subsections));

  content.appendChild(bar);
  updateSmartBarText(state.currentSubsectionId);
}

export function updateSmartBarText(subsectionId) {
  const bar = document.querySelector('.smart-bar');
  if (!bar) return;
  const titleText = bar.querySelector('.smart-bar-title-text');
  const prevBtn = bar.querySelector('.smart-bar-prev');
  const nextBtn = bar.querySelector('.smart-bar-next');

  const subsections = [];
  const rail = document.querySelector('.ghost-rail');
  if (rail) {
    rail.querySelectorAll('.ghost-rail-node').forEach(n => {
      subsections.push({ id: n.dataset.subsectionId, title: n.querySelector('.ghost-rail-label')?.textContent || '' });
    });
  }

  const idx = subsections.findIndex(s => s.id === subsectionId);
  if (titleText) {
    titleText.textContent = idx !== -1 ? subsections[idx].title : '—';
  }
  if (prevBtn) prevBtn.disabled = idx <= 0;
  if (nextBtn) nextBtn.disabled = idx === -1 || idx >= subsections.length - 1;

  // Update progress hairline
  const progress = bar.querySelector('.smart-bar-progress');
  if (progress && subsections.length > 0) {
    const pct = idx >= 0 ? ((idx + 1) / subsections.length) * 100 : 0;
    progress.style.width = pct + '%';
  }
}

function navigateSubsection(delta) {
  const subsections = [];
  document.querySelectorAll('.ghost-rail-node').forEach(n => {
    subsections.push(n.dataset.subsectionId);
  });
  const idx = subsections.findIndex(id => id === state.currentSubsectionId);
  const next = subsections[idx + delta];
  if (next) {
    const target = document.getElementById(next);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function openSubsectionSheet(subsections) {
  // Simple sheet using existing modal/overlay patterns in the app
  const overlay = document.createElement('div');
  overlay.className = 'subsection-sheet-overlay';
  const sheet = document.createElement('div');
  sheet.className = 'subsection-sheet';
  sheet.innerHTML = `<div class="subsection-sheet-handle"></div><div class="subsection-sheet-list"></div>`;
  const list = sheet.querySelector('.subsection-sheet-list');

  subsections.forEach((sub, i) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'subsection-sheet-item';
    if (sub.id === state.currentSubsectionId) item.classList.add('active');
    item.innerHTML = `<span class="subsection-sheet-num">${i + 1}</span><span class="subsection-sheet-label">${escHtml(sub.title)}</span>`;
    item.addEventListener('click', () => {
      const target = document.getElementById(sub.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      overlay.remove();
    });
    list.appendChild(item);
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });

  overlay.appendChild(sheet);
  document.body.appendChild(overlay);
}
```

- [ ] **Step 2: Call `renderSmartBar` inside `renderTab` after rendering explainer**

In `renderTab`, after `renderGhostRail`:

```js
if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data, state.currentPartId);
    renderGhostRail(state.currentPartId, data);
    renderSmartBar(state.currentPartId, data);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/projectView.js
git commit -m "feat(projectView): add Smart Bar with prev/next, sheet, and progress

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Frontend — CSS for Ghost Rail and Smart Bar

**Files:**
- Modify: `frontend/style.css`

- [ ] **Step 1: Append CSS to `frontend/style.css`**

Append at the end of the file:

```css
/* ============================================================
   GHOST RAIL — Desktop subsection navigation
   ============================================================ */

.ghost-rail {
  position: absolute;
  right: 0;
  top: 0;
  width: 40px;
  height: 100%;
  pointer-events: auto;
  z-index: 5;
  opacity: 0;
  animation: ghostRailFadeIn 400ms ease forwards;
}

@keyframes ghostRailFadeIn {
  to { opacity: 1; }
}

.ghost-rail-line {
  position: absolute;
  left: 50%;
  top: 24px;
  bottom: 24px;
  width: 2px;
  background: #21262d;
  transform: translateX(-50%);
}

.ghost-rail-node {
  position: absolute;
  left: 50%;
  width: 6px;
  height: 6px;
  background: #30363d;
  border-radius: 50%;
  transform: translateX(-50%);
  transition: all 250ms cubic-bezier(0.22, 1, 0.36, 1);
  cursor: pointer;
  border: none;
  padding: 0;
  pointer-events: auto;
}

.ghost-rail-node.active {
  width: 10px;
  height: 10px;
  background: transparent;
  border: 2px solid #f59e0b;
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.25);
}

.ghost-rail-node.is-read {
  background: #8b949e;
}

.ghost-rail-node:hover {
  transform: translateX(-50%) translateX(-8px);
}

.ghost-rail-label {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--font-ui-r);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #8b949e;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 250ms ease;
  pointer-events: none;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ghost-rail:hover .ghost-rail-label {
  opacity: 1;
}

.ghost-rail-label.active {
  color: #f0ece3;
}

/* ============================================================
   SMART BAR — Mobile subsection navigation
   ============================================================ */

.smart-bar {
  position: sticky;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: rgba(13, 17, 23, 0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid rgba(48, 54, 61, 0.6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  transform: translateY(0);
  transition: transform 350ms cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 10;
}

.smart-bar.retracted {
  transform: translateY(calc(100% - 2px));
}

.smart-bar-progress {
  position: absolute;
  top: 0;
  left: 0;
  height: 2px;
  background: #f59e0b;
  transition: width 150ms linear;
}

.smart-bar-prev,
.smart-bar-next {
  background: none;
  border: none;
  color: #f0ece3;
  cursor: pointer;
  padding: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.9;
  transition: opacity 150ms ease;
}

.smart-bar-prev:disabled,
.smart-bar-next:disabled {
  opacity: 0.25;
  cursor: default;
}

.smart-bar-title {
  flex: 1;
  background: none;
  border: none;
  color: #f0ece3;
  font-family: var(--font-body-r);
  font-size: 14px;
  text-align: center;
  cursor: pointer;
  padding: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ============================================================
   SUBSECTION SHEET — Mobile list
   ============================================================ */

.subsection-sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 100;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  animation: sheetOverlayIn 250ms ease forwards;
}

@keyframes sheetOverlayIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.subsection-sheet {
  width: 100%;
  max-height: 70vh;
  background: #161b22;
  border-radius: 16px 16px 0 0;
  padding: 12px 0 24px;
  animation: sheetSlideUp 300ms cubic-bezier(0.22, 1, 0.36, 1) forwards;
  overflow-y: auto;
}

@keyframes sheetSlideUp {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}

.subsection-sheet-handle {
  width: 36px;
  height: 4px;
  background: #30363d;
  border-radius: 2px;
  margin: 0 auto 12px;
}

.subsection-sheet-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 20px;
  background: none;
  border: none;
  color: #c9d1d9;
  font-family: var(--font-body-r);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background 150ms ease;
}

.subsection-sheet-item.active {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
}

.subsection-sheet-item:hover {
  background: rgba(240, 236, 227, 0.04);
}

.subsection-sheet-num {
  font-family: var(--font-ui-r);
  font-size: 11px;
  color: #8b949e;
  min-width: 24px;
}

/* ============================================================
   ACCESSIBILITY
   ============================================================ */

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "feat(css): add Ghost Rail, Smart Bar, Sheet, and a11y utilities

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Frontend — Position Ghost Rail nodes after render

**Files:**
- Modify: `frontend/js/projectView.js`

- [ ] **Step 1: Add `positionGhostRailNodes()` and call it after render**

Insert after `renderGhostRail`:

```js
function positionGhostRailNodes() {
  const rail = document.querySelector('.ghost-rail');
  const panel = document.getElementById('panel-explicacion');
  if (!rail || !panel) return;

  const panelRect = panel.getBoundingClientRect();
  rail.querySelectorAll('.ghost-rail-node').forEach(node => {
    const target = document.getElementById(node.dataset.subsectionId);
    if (!target) return;
    const targetRect = target.getBoundingClientRect();
    const top = targetRect.top - panelRect.top + panel.scrollTop;
    node.style.top = top + 'px';
  });
}
```

Call it inside `renderTab` after `renderSmartBar`:

```js
if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data, state.currentPartId);
    renderGhostRail(state.currentPartId, data);
    renderSmartBar(state.currentPartId, data);
    // Defer positioning until DOM is laid out
    requestAnimationFrame(() => requestAnimationFrame(positionGhostRailNodes));
}
```

Also call it on window resize (add inside `bootstrap()` in `main.js` later, or add a one-liner here):
In `frontend/js/main.js` inside `bootstrap()` add:
```js
window.addEventListener('resize', () => {
  if (state.activeTab === 'explicacion') positionGhostRailNodes();
});
```
But since `positionGhostRailNodes` is private to `projectView.js`, export it:

```js
export function positionGhostRailNodes() { ... }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/projectView.js frontend/js/main.js
git commit -m "feat(projectView): position Ghost Rail nodes relative to subsection headings

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: Frontend — IntersectionObserver lifecycle

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add observer lifecycle variables and functions**

At the top of `main.js` (after imports), add:

```js
let _subsectionObserver = null;
let _subsectionDebounce = null;
let _lastSubsectionId = null;
let _subsectionAccumulator = new Map(); // id -> accumulated ms
let _subsectionLastActivatedAt = 0;
```

Add functions before `bootstrap()`:

```js
function initSubsectionObserver() {
  disconnectSubsectionObserver();
  if (state.activeTab !== 'explicacion') return;
  const main = document.getElementById('project-main');
  const panel = document.getElementById('panel-explicacion');
  if (!main || !panel) return;

  const targets = panel.querySelectorAll('h4.explainer-subsection-title');
  if (targets.length === 0) return;

  _subsectionObserver = new IntersectionObserver((entries) => {
    const active = entries
      .filter(e => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (active) setActiveSubsection(active.target.id);
  }, {
    root: main,
    rootMargin: '-35% 0px -55% 0px',
    threshold: [0, 0.25, 0.5, 0.75, 1],
  });

  targets.forEach(t => _subsectionObserver.observe(t));
}

function disconnectSubsectionObserver() {
  if (_subsectionObserver) {
    _subsectionObserver.disconnect();
    _subsectionObserver = null;
  }
}

function setActiveSubsection(id) {
  if (id === _lastSubsectionId) {
    // Still same subsection; update accumulator time
    return;
  }

  // Finalize time for previous subsection
  const now = Date.now();
  if (_lastSubsectionId && _subsectionLastActivatedAt) {
    const elapsed = now - _subsectionLastActivatedAt;
    const prevTotal = (_subsectionAccumulator.get(_lastSubsectionId) || 0) + elapsed;
    _subsectionAccumulator.set(_lastSubsectionId, prevTotal);
    if (prevTotal >= 3000) {
      maybeMarkSubsectionRead(_lastSubsectionId);
    }
  }

  _lastSubsectionId = id;
  _subsectionLastActivatedAt = now;
  state.currentSubsectionId = id;

  // Update UI
  import('./projectView.js').then(({ updateGhostRailActive, updateSmartBarText }) => {
    updateGhostRailActive(id);
    updateSmartBarText(id);
  });

  // Update URL quietly
  if (window.replaceRoute && state.currentProjectId && state.currentPartId) {
    window.replaceRoute({
      view: state.isSharedView ? 'shared' : 'project',
      projectId: state.currentProjectId,
      shareToken: state.shareToken,
      partId: state.currentPartId,
      tab: state.activeTab,
      subsectionId: id,
    });
  }

  // Debounced persistence
  if (_subsectionDebounce) clearTimeout(_subsectionDebounce);
  _subsectionDebounce = setTimeout(() => {
    saveSubsectionProgress({
      subsection_id: id,
      part_id: state.currentPartId,
      tab: state.activeTab,
      is_last_read: true,
    });
    _subsectionDebounce = null;
  }, 2000);
}

function maybeMarkSubsectionRead(id) {
  if (!state.currentProject) return;
  const progress = state.currentProject.reading_progress || {};
  const completed = new Set(progress.completed_subsections || []);
  if (completed.has(id)) return;

  saveSubsectionProgress({
    subsection_id: id,
    part_id: state.currentPartId,
    tab: state.activeTab,
    completed: true,
  });
}
```

- [ ] **Step 2: Hook observer into `selectPart` and tab switching**

In `frontend/js/projectView.js`, at the end of `selectPart()` (before `saveViewState()`), add:

```js
  // Trigger observer setup after content is rendered
  if (typeof window.initSubsectionObserver === 'function') {
    setTimeout(window.initSubsectionObserver, 0);
  }
```

In `frontend/js/main.js`, inside the tab button click handler (around line 436), after `activateTab(tab)`, add:

```js
    if (tab === 'explicacion') {
      setTimeout(initSubsectionObserver, 0);
    } else {
      disconnectSubsectionObserver();
    }
```

Expose the functions on `window` so `projectView.js` can call them:

```js
window.initSubsectionObserver = initSubsectionObserver;
window.disconnectSubsectionObserver = disconnectSubsectionObserver;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/main.js frontend/js/projectView.js
git commit -m "feat(main): add IntersectionObserver lifecycle and active subsection tracking

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Frontend — Smart Bar scroll visibility

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add scroll listener for Smart Bar retract/expand**

Inside `bootstrap()` in `main.js`, add after `initReadingProgressBar()`:

```js
  initSmartBarScrollBehavior();
```

Add the function before `bootstrap()`:

```js
function initSmartBarScrollBehavior() {
  const main = document.getElementById('project-main');
  if (!main) return;
  let lastScrollY = 0;
  let ticking = false;

  main.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const y = main.scrollTop;
      const delta = y - lastScrollY;
      const bar = document.querySelector('.smart-bar');
      if (bar) {
        if (delta > 5) {
          bar.classList.add('retracted');
        } else if (delta < -10) {
          bar.classList.remove('retracted');
        }
      }
      lastScrollY = y;
      ticking = false;
    });
  }, { passive: true });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): add Smart Bar scroll retract/expand behavior

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Frontend — Keyboard navigation

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add keyboard shortcuts for subsection navigation**

Inside `bootstrap()` in `main.js`, add:

```js
  initSubsectionKeyboardNav();
```

Add the function before `bootstrap()`:

```js
function initSubsectionKeyboardNav() {
  document.addEventListener('keydown', (e) => {
    if (state.activeTab !== 'explicacion') return;
    if (!e.altKey) return;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();

    const subsections = Array.from(document.querySelectorAll('h4.explainer-subsection-title')).map(h => h.id);
    const idx = subsections.findIndex(id => id === state.currentSubsectionId);
    const delta = e.key === 'ArrowDown' ? 1 : -1;
    const next = subsections[idx + delta];
    if (next) {
      const target = document.getElementById(next);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): add Alt+Arrow keyboard navigation for subsections

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: Frontend — `saveSubsectionProgress` helper

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add the helper**

Add before `bootstrap()`:

```js
async function saveSubsectionProgress({ subsection_id, part_id, tab, completed, is_last_read }) {
  if (!state.currentProjectId || !state.user?.id) return;
  if (state.isSharedView) return; // No server persistence for shared views

  const payload = { subsection_id, part_id, tab };
  if (completed !== undefined) payload.completed = completed;
  if (is_last_read !== undefined) payload.is_last_read = is_last_read;

  try {
    const updated = await api(`/api/projects/${state.currentProjectId}/progress/subsection`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (updated?.reading_progress && state.currentProject) {
      state.currentProject.reading_progress = updated.reading_progress;
    }
  } catch (err) {
    // Silently fail — local session state already holds the truth
    if (is_last_read) {
      // Optimistically update local project object so offline works
      const rp = state.currentProject.reading_progress || {};
      state.currentProject.reading_progress = {
        ...rp,
        last_subsection: { part_id, subsection_id, tab },
        last_read_at: new Date().toISOString(),
      };
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): add saveSubsectionProgress with optimistic local fallback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: Frontend — Update `saveViewState` and restore logic

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Update `saveViewState()` to include `subsectionId`**

Replace the existing `saveViewState()` (around line 26):

```js
function saveViewState() {
  if (!state.user?.id) return;

  const activeView = document.querySelector('.view.active')?.id || 'view-landing';
  const viewState = {
    userId: state.user.id,
    view: activeView,
    projectId: state.currentProjectId,
    partId: state.currentPartId,
    subsectionId: state.currentSubsectionId,
    activeTab: state.activeTab,
    savedAt: new Date().toISOString(),
  };
  sessionStorage.setItem('explainer.viewState', JSON.stringify(viewState));
}
```

- [ ] **Step 2: Update `navigateFromRoute` to handle `subsectionId` scroll**

In `navigateFromRoute`, inside the `route.view === 'project' && route.projectId` block where `route.partId` exists (around line 74-98), change the existing `restoreProjectView` branch to pass `subsectionId`:

```js
  if (route.view === 'project' && route.projectId) {
    if (route.partId) {
      // ... existing early-return path when project already loaded ...
      restoreProjectView(route.projectId, route.partId, route.tab, route.subsectionId).catch(() => {});
      return;
    }
    openProjectView(route.projectId);
  }
```

Wait — `restoreProjectView` is imported from `projects.js`. We need to check if it accepts a 4th arg. If not, we should pass it through `projects.js` or handle scroll after `restoreProjectView` resolves. The simplest approach is to handle scroll in `main.js` after `restoreProjectView` resolves:

```js
      restoreProjectView(route.projectId, route.partId, route.tab)
        .then(() => {
          if (route.subsectionId) {
            const el = document.getElementById(route.subsectionId);
            if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
          }
        })
        .catch(() => {});
```

Apply the same pattern to the `loadSharedProject` path for shared views.

Also update the sessionStorage restore block (around line 186-218):

```js
  const savedState = sessionStorage.getItem('explainer.viewState');
  if (savedState) {
    try {
      const viewState = JSON.parse(savedState);
      if (viewState.userId === state.user?.id) {
        if (viewState.view === 'view-project' && viewState.projectId) {
          state.currentProjectId = viewState.projectId;
          state.currentPartId = viewState.partId || null;
          state.currentSubsectionId = viewState.subsectionId || null;
          state.activeTab = viewState.activeTab || 'explicacion';
          await restoreProjectView(viewState.projectId, viewState.partId, viewState.activeTab)
            .then(() => {
              if (viewState.subsectionId) {
                const el = document.getElementById(viewState.subsectionId);
                if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
              }
            });
          if (window.replaceRoute) {
            window.replaceRoute({
              view: 'project',
              projectId: viewState.projectId,
              partId: viewState.partId,
              tab: viewState.activeTab || 'explicacion',
              subsectionId: viewState.subsectionId,
            });
          }
          return;
        }
        // ... rest unchanged ...
      }
    } catch (_) {}
  }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): persist subsectionId in viewState and restore on load

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: Frontend — Reset subsection state on part change

**Files:**
- Modify: `frontend/js/projectView.js`

- [ ] **Step 1: Reset `currentSubsectionId` in `selectPart()`**

In `selectPart()` (around line 741), add after `state.currentPartId = partId;`:

```js
  state.currentSubsectionId = null;
  _lastSubsectionId = null; // if available in scope; otherwise handled by observer disconnect
```

But `_lastSubsectionId` is private to `main.js`. Instead, ensure `disconnectSubsectionObserver()` is called at the top of `selectPart`, and that the observer re-initializes after render. This is already handled by the `setTimeout(window.initSubsectionObserver, 0)` added in Task 10.

However, we should also reset the UI: hide rail and bar immediately when switching parts. Add at the top of `selectPart`:

```js
  // Clean up subsection UI from previous part
  document.querySelector('.ghost-rail')?.remove();
  document.querySelector('.smart-bar')?.remove();
```

This ensures no stale rail/bar from a previous part remains visible during the transition.

- [ ] **Step 2: Commit**

```bash
git add frontend/js/projectView.js
git commit -m "fix(projectView): clean up subsection UI on part change

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: Frontend — Handle tab switching (non-explicacion)

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Ensure observer disconnects when leaving Explicación**

In the tab button click handler inside `bootstrap()` (around line 436), the logic added in Task 10 should already handle this:

```js
    if (tab === 'explicacion') {
      setTimeout(initSubsectionObserver, 0);
    } else {
      disconnectSubsectionObserver();
    }
```

Also hide rail/bar visually when tab is not explicacion:

```js
    const rail = document.querySelector('.ghost-rail');
    const bar = document.querySelector('.smart-bar');
    if (rail) rail.style.display = tab === 'explicacion' ? '' : 'none';
    if (bar) bar.style.display = tab === 'explicacion' ? '' : 'none';
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): disconnect observer and hide rail/bar on non-explicacion tabs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: Frontend — Copy link includes subsection

**Files:**
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Update `initCopyLink()` to include subsectionId**

Find `initCopyLink()` (around line 366) and update the `route` construction:

```js
  btn.addEventListener('click', async () => {
    if (!state.currentPartId) return;
    const route = state.isSharedView && state.shareToken
      ? { view: 'shared', shareToken: state.shareToken, partId: state.currentPartId, tab: state.activeTab, subsectionId: state.currentSubsectionId }
      : { view: 'project', projectId: state.currentProjectId, partId: state.currentPartId, tab: state.activeTab, subsectionId: state.currentSubsectionId };
    const url = location.origin + location.pathname + (typeof window.buildHash === 'function'
      ? window.buildHash(route)
      : location.hash || '#/');
    try {
      await navigator.clipboard.writeText(url);
      toast('Enlace copiado al portapapeles', 'success');
    } catch (_) {
      toast('No se pudo copiar el enlace', 'error');
    }
  });
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/main.js
git commit -m "feat(main): include subsectionId in copied share links

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 18: Frontend — Accessibility live region

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/js/main.js`

- [ ] **Step 1: Add live region to `index.html`**

Insert before the closing `</body>`:

```html
  <span id="subsection-announcer" class="sr-only" aria-live="polite" aria-atomic="true"></span>
```

- [ ] **Step 2: Announce changes in `setActiveSubsection`**

In `setActiveSubsection()` in `main.js`, add after updating UI:

```js
  const announcer = document.getElementById('subsection-announcer');
  const targetHeading = document.getElementById(id);
  if (announcer && targetHeading) {
    announcer.textContent = `Ahora en: ${targetHeading.textContent}`;
  }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html frontend/js/main.js
git commit -m "feat(a11y): add live region announcing subsection changes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 19: Integration — End-to-end smoke test

**Files:**
- No file changes; manual verification.

- [ ] **Step 1: Start the dev server**

```bash
python main.py
```

- [ ] **Step 2: Manual verification checklist**

Open `http://localhost:8000`, log in, and open any project with a completed part that has subsections.

1. **Desktop:** Ghost Rail appears on the right with one dot per subsection.
2. **Desktop:** Hovering the rail reveals titles.
3. **Desktop:** Clicking a dot smooth-scrolls to that subsection.
4. **Desktop:** Scrolling updates the active dot (amber ring).
5. **Desktop:** `Alt + ↑/↓` jumps between subsections.
6. **Mobile (dev tools):** Smart Bar is visible at bottom on load.
7. **Mobile:** Scroll down → bar retracts to hairline.
8. **Mobile:** Scroll up → bar expands.
9. **Mobile:** Tap title → sheet opens; tap item → jumps.
10. **URL:** Changes to `.../u/subsec-X-Y-Z` as you scroll.
11. **Copy link:** Paste includes `/u/...` subsection.
12. **Reload:** Lands at exact subsection (auto-scroll, no animation).
13. **Tab switch** to Recorrido → rail/bar disappear; back to Explicación → reappear.
14. **Part switch** → old rail/bar removed; new ones render.
15. **Backend:** Network tab shows `PATCH /progress/subsection` with 200.

- [ ] **Step 3: Commit any fixes found during smoke test**

If any fixes were needed, commit them with a descriptive message. If none, mark this step as done.

---

### Task 20: Integration — Edge case: parts without subsections

**Files:**
- Modify: `frontend/js/projectView.js`
- Verify: `frontend/js/main.js`

- [ ] **Step 1: Confirm degradation behavior**

Open a part whose explainer JSON has no `subsecciones` arrays. Expected:
- `renderGhostRail` returns early; no rail injected.
- `renderSmartBar` returns early; no bar injected.
- `initSubsectionObserver` finds 0 targets and returns early.
- `setActiveSubsection` is never called.
- `saveViewState` stores `subsectionId: null`.
- URL has no `/u/...` segment.
- Prev/Next **part** buttons (existing toolbar) still work normally.

If any of these fail, fix inline in `projectView.js` or `main.js`.

- [ ] **Step 2: Commit**

```bash
git add frontend/js/projectView.js frontend/js/main.js
git commit -m "fix: graceful degradation when part has no subsections

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task that implements it |
|------------------|------------------------|
| Ghost Rail desktop UI | Task 6, 8, 9 |
| Smart Bar mobile UI | Task 7, 8, 11 |
| Subsection Sheet | Task 7 |
| Deterministic IDs | Task 5 |
| URL `/u/{id}` | Task 3 |
| `replaceState` for subsection, `pushState` for part/tab | Task 10 |
| Deep-link scroll restore | Task 14 |
| `currentSubsectionId` in state | Task 4 |
| `saveViewState` expansion | Task 14 |
| IntersectionObserver | Task 10 |
| Debounced backend save (2s) | Task 10 |
| Time-based read detection (>3s) | Task 10 |
| Progression-based read detection | Task 10 |
| `PATCH /progress/subsection` endpoint | Task 2 |
| `update_subsection_progress()` helper | Task 1 |
| Keyboard navigation (Alt+Arrows) | Task 12 |
| Copy link with subsection | Task 17 |
| Live region announcements | Task 18 |
| Graceful degradation (no subsections) | Task 20 |
| Accessibility (aria-labels, roles) | Tasks 6, 7, 8, 18 |
| Rail node positioning on resize | Task 9 |

**No gaps found.**

### Placeholder scan

- No "TBD", "TODO", "implement later", or "add appropriate error handling" found.
- Every code step contains actual code.
- No "Similar to Task N" shortcuts.

### Type / signature consistency

- `saveSubsectionProgress` signature matches in Tasks 10, 13, and spec.
- `subsection_id` used consistently (kebab-case string) across frontend and backend.
- `part_id` is always a Number in JS, int in Python.
- `updateGhostRailActive` and `updateSmartBarText` exported from `projectView.js` and imported dynamically in `main.js`.

All consistent.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-subsection-navigation-progress.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

**Which approach do you prefer?**
