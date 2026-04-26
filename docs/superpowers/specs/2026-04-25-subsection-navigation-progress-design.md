# Subsection Navigation & Progress Persistence — Design Spec

**Date:** 2026-04-25  
**Scope:** Frontend + Backend  
**Status:** Draft pending review  

---

## 1. Overview

Introduce seamless, non-invasive subsection navigation within the **Explicación** tab and persist reading progress at subsection granularity. When a user returns to a project, they land not just on the correct part and tab, but at the exact subsection where they left off.

**Success criteria:**
- Desktop users navigate subsections via an elegant "Ghost Rail" without leaving the reading flow.
- Mobile users get a retractible Smart Bar that appears only when needed.
- The backend stores `last_subsection` and `completed_subsections`, synced with local backup.
- URLs support deep-linking to subsections: `#/p/{id}/s/{part}/t/{tab}/u/{subsec}`.
- Everything degrades gracefully when a part has no subsections.

---

## 2. Context & Motivation

Current behavior:
- Navigation is part-level only (sidebar + prev/next buttons).
- Progress is saved as `completed_parts: [1,2]` and session storage holds `partId` + `activeTab`.
- Returning users land at the top of a part, losing their exact reading position within long explanations.

Pain points:
1. Long explanations can have 5–15 subsections; scrolling to find your place is friction.
2. Mobile reading is especially painful because there is no TOC or quick-jump mechanism inside a part.
3. Users who switch devices lose their exact position because only the part is remembered server-side.

---

## 3. Aesthetic Direction

**"Dark Academic Editorial"** — the reading surface is sacred; navigation is a whisper, not a shout.

- **Ghost Rail (desktop):** A 40px vertical thread to the right of the reading column. Nodules are barely visible grey dots until hovered or activated. The active nodule glows amber like a candle mark in a margin.
- **Smart Bar (mobile):** Retracts fully while reading, leaving only a 2px progress hairline. Reveals on scroll-up with a smooth, heavy physical transition (`cubic-bezier(0.22, 1, 0.36, 1)`).
- **Typography:** Preserve existing font stack (Playfair Display, Crimson Pro, Syne). Subsection `h4` titles increase from 11px to **13px with `letter-spacing: 0.05em`** to serve as true signposts.
- **Color:** `#0d1117` background, `#f59e0b` amber accent, `#f0ece3` text. Rail inactive nodules: `#30363d`. Read nodules: `#8b949e`.
- **Motion:** CSS-only transitions. Staggered nodule appearance on part load (40ms per item). No elastic bounces; everything feels weighted and paper-like.

---

## 4. Navigation Architecture

### 4.1 Ghost Rail — Desktop

**Placement:** Absolute-positioned container inside `project-main`, flush right, `width: 40px`, `height: 100%` of scrollable content.

**Components:**
- `.ghost-rail-line` — 2px vertical line, `#21262d`, centered, inset 24px from top/bottom.
- `.ghost-rail-node` — absolutely positioned circles mapped to each `h4.explainer-subsection-title` vertical offset.
  - Inactive: 6px disc, `#30363d`.
  - Active: 10px ring, `#f59e0b` with `box-shadow: 0 0 8px rgba(245,158,11,0.25)`.
  - Read: 6px disc, `#8b949e`.
- `.ghost-rail-label` — hidden by default. On rail hover, each node shifts 8px left and reveals its subsection title in **Syne 10px uppercase**, right-aligned, max-width 180px, color `#8b949e`, active title in `#f0ece3`.

**Interaction:**
- Click a node → smooth scroll to the corresponding `h4`.
- Hover the rail → all labels reveal with 300ms fade.

### 4.2 Smart Bar — Mobile

**Placement:** Injected as the last child of `#part-content` (inside the active tab panel). Uses `position: sticky; bottom: 0` so it anchors to the scroll context of `project-main` without using `position: fixed` (avoids Safari toolbar overlap bugs).

**States:**
1. **Initial:** On first load of a part, the bar starts **expanded** so the user knows it exists.
2. **Retracted (reading):** After the first scroll down (>5px), it collapses to show only a 2px amber progress hairline at the bottom edge. `transform: translateY(calc(100% - 2px))`.
3. **Expanded (navigating):** On scroll up (<-10px), the full 56px bar reveals with glassmorphism background (`rgba(13,17,23,0.85)` + `backdrop-filter: blur(12px)`).
   - Left: Prev arrow (disabled on first subsection).
   - Center: Current subsection title, **Crimson Pro 14px**, truncated to 1 line. Tappable.
   - Right: Next arrow (disabled on last subsection).
4. **Sheet:** Tapping the center title opens a bottom sheet (70% height, `#161b22`, rounded top) listing all subsections of the current part.

**Trigger logic:**
```
On part load           → expanded
scroll down (>5px)     → retract
scroll up  (<-10px)    → expand
```

### 4.3 Subsection Sheet / Drawer

- **Desktop:** A dropdown panel aligned to the Ghost Rail, triggered by clicking the active node or a subtle "Índice" text button beside the reading toolbar.
- **Mobile:** Bottom sheet as described above. Closes on backdrop tap, swipe-down, or selection.

---

## 5. Data Model & Persistence

### 5.1 Database Schema (JSONB)

Column: `projects.reading_progress` (existing, JSONB, default `{}`).

New shape (backward-compatible):

```json
{
  "completed_parts": [1, 2],
  "completed_subsections": ["subsec-2-0-0", "subsec-2-0-1"],
  "last_read_at": "2026-04-25T10:00:00Z",
  "last_subsection": {
    "part_id": 2,
    "subsection_id": "subsec-2-0-1",
    "tab": "explicacion"
  }
}
```

**Migration:** No schema migration required; JSONB structure is additive.

### 5.2 API Endpoints

**Existing endpoint (unchanged):**
```http
PATCH /api/projects/{project_id}/progress
Body: { "part_id": 3, "completed": true }
```

**New endpoint:**
```http
PATCH /api/projects/{project_id}/progress/subsection
Content-Type: application/json

Body:
{
  "subsection_id": "subsec-2-0-1",
  "part_id": 2,
  "completed": true,      // optional
  "is_last_read": true    // optional, updates last_subsection
}
```

**Validation rules:**
- `part_id` must exist in `project.segmentation.partes`.
- `subsection_id` must match the deterministic format `subsec-{part_id}-{sectionIdx}-{subIdx}`.
- If `completed` is omitted, only `last_subsection` is updated.
- Returns the updated `reading_progress` object.

**Backend implementation (`backend/supabase_data.py`):**
- Add `update_subsection_progress(project_id, user_id, subsection_id, part_id, completed=None, is_last_read=False)`.
- Reuses existing `update_project()` to write the mutated `reading_progress` JSONB.

### 5.3 Frontend State

**Session state (`sessionStorage`):**
Key: `explainer.viewState`
```json
{
  "userId": "uuid",
  "view": "view-project",
  "projectId": "uuid",
  "partId": 2,
  "subsectionId": "subsec-2-0-1",
  "activeTab": "explicacion",
  "savedAt": "2026-04-25T..."
}
```

**Runtime state (`state` object in `state.js`):**
```js
state.currentSubsectionId = null; // new field
```

### 5.4 Local Backup

`reading_progress` is already part of the project object synced to IndexedDB via `backupStorage.js`. No additional local storage keys needed; the existing backup pipeline replicates the expanded JSONB automatically.

---

## 6. URL & Routing

### 6.1 URL Format

Existing:
```
#/p/{projectId}/s/{partId}/t/{tab}
```

Extended:
```
#/p/{projectId}/s/{partId}/t/{tab}/u/{subsectionId}
```

Example:
```
#/p/abc-123/s/2/t/explicacion/u/subsec-2-0-1
```

### 6.2 Router Changes (`frontend/js/router.js`)

- `parseRoute()`: if `segments[6] === 'u' && segments[7]`, set `route.subsectionId = segments[7]`.
- `buildHash(route)`: append `/u/${route.subsectionId}` when present.
- `VALID_TABS` unchanged.

### 6.3 History Strategy

- **Subsection changes** (scroll, click rail, arrow nav): update URL via `replaceRoute` (`history.replaceState`) to avoid history spam.
- **Part or tab changes:** continue using `pushRoute` (`history.pushState`).
- **Deep link:** on load, parse `subsectionId`, call `selectPart()`, wait for render, then `scrollIntoView({ behavior: 'auto' })` to avoid motion sickness on cold load.

---

## 7. Scroll Behavior & Auto-Detection

### 7.1 IntersectionObserver

Observed elements: all `h4.explainer-subsection-title` inside the active `#panel-explicacion`.

```js
const observer = new IntersectionObserver((entries) => {
  const active = entries
    .filter(e => e.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (active) setActiveSubsection(active.target.id);
}, {
  root: document.getElementById('project-main'),
  rootMargin: '-35% 0px -55% 0px',
  threshold: [0, 0.25, 0.5, 0.75, 1]
});
```

- Disconnect and reconnect on every `selectPart()` + `activateTab('explicacion')`.
- Ignore if the active tab is not `explicacion`.

### 7.2 Active Subsection Handler

```js
let _subsectionDebounce = null;
let _lastSubsectionId = null;

function setActiveSubsection(id) {
  if (id === _lastSubsectionId) return;
  _lastSubsectionId = id;
  state.currentSubsectionId = id;

  // Update rail UI
  updateGhostRailActive(id);

  // Update Smart Bar text
  updateSmartBarText(id);

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
```

### 7.3 "Read" Detection

A subsection is marked as read when any of the following occurs:
1. **Time-based:** It has been the `active` subsection for **>3 seconds cumulative** within a single session. Implementation: store `lastActivatedAt` per subsection. On each `setActiveSubsection` change, add `Date.now() - lastActivatedAt` to an accumulator for the departing subsection. If the accumulator exceeds 3000ms, mark as read.
2. **Progression-based:** The user reaches the next subsection (i.e., the subsequent `h4` enters the observer viewport while the current one is still active). The departing subsection is immediately marked as read.
3. **Manual:** The user clicks the "Marcar como leída" button (future enhancement, not required in this phase).

On meeting criteria:
```js
saveSubsectionProgress({
  subsection_id: id,
  part_id: state.currentPartId,
  tab: state.activeTab,
  completed: true,
});
```

### 7.4 Keyboard Navigation (Desktop)

- `Alt + ArrowDown` → scroll to next subsection.
- `Alt + ArrowUp` → scroll to previous subsection.
- Implemented as a document-level listener in `project-main` scope.

---

## 8. Rendering & DOM

### 8.1 Subsection IDs

During `renderExplainer()`, assign deterministic IDs:
```js
const subsectionId = `subsec-${partId}-${sectionIndex}-${subIndex}`;
html += `<h4 class="explainer-subsection-title" id="${subsectionId}">...</h4>`;
```

### 8.2 Ghost Rail Rendering

A new function `renderGhostRail(partId, explainerData)` generates the rail DOM. It is called inside `renderTab('explicacion', contenido)` after injecting the HTML.

**Structure:**
```html
<div class="ghost-rail" id="ghost-rail" aria-label="Navegación de subsecciones">
  <div class="ghost-rail-line"></div>
  <!-- nodes injected here -->
</div>
```

**Positioning math:**
After render, measure `offsetTop` of each `h4.explainer-subsection-title` relative to `#panel-explicacion` and set `top` on each node.

### 8.3 Smart Bar Rendering

Injected once as the last child of `#part-content` (inside `#panel-explicacion`) via HTML template. Visibility toggled by CSS classes. Because `project-main` is the scroll container, `position: sticky; bottom: 0` on the bar anchors it to the bottom of the reading area without breaking on mobile Safari.

---

## 9. Accessibility

- **Ghost Rail nodes:** each has `aria-label="Subsección {n}: {title}"` and `role="button"`.
- **Smart Bar:** `role="navigation"`, `aria-label="Navegación de subsección"`.
- **Live region:** an `aria-live="polite"` span (visually hidden) announces subsection changes for screen readers:
  ```html
  <span id="subsection-announcer" class="sr-only" aria-live="polite"></span>
  ```
- **Focus management:** when a user clicks a rail node, focus moves to the corresponding `h4` (optional, configurable).

---

## 10. Edge Cases & Degradation

| Scenario | Behavior |
|----------|----------|
| Part has no subsections (flat explainer) | Ghost Rail hidden. Smart Bar shows only part-level progress. `subsectionId` is null. |
| Tab is not "explicacion" | Observer disconnected. Rail hidden. Smart Bar hidden. URL omits `/u/...`. |
| Shared view (read-only) | Navigation UI fully visible (rail + bar). Progress is NOT saved to backend (no user). `sessionStorage` still saves locally so the same browser session remembers position. |
| Offline mode | `last_subsection` updates in `sessionStorage` and IndexedDB backup. Server sync deferred until online. No error toasts for progress sync failures. |
| Old projects without formatter_version | Rail renders based on raw JSON structure; if no subsecciones array, degrades to hidden. |
| URL with invalid subsectionId | Scroll fails gracefully; logs a console warning; stays at top of part. |
| Rapid part switching | `lastPartChangeAt` cooldown (existing 600ms) prevents premature "read" marks. Observer disconnects immediately on `selectPart()`. |

---

## 11. Files to Touch

### Backend
- `backend/supabase_data.py`
  - Add `update_subsection_progress()`.
  - Update `set_section_read_status()` docstring for clarity.
- `main.py`
  - Add `PATCH /api/projects/{project_id}/progress/subsection` endpoint.

### Frontend
- `frontend/js/router.js`
  - `parseRoute()`: extract `subsectionId`.
  - `buildHash()`: append `/u/{subsectionId}`.
- `frontend/js/state.js`
  - Add `currentSubsectionId: null` to `state`.
- `frontend/js/projectView.js`
  - `renderExplainer()`: inject `id` attributes on subsection headers.
  - `renderTab('explicacion', ...)`: call `renderGhostRail()` and `initSmartBar()`.
  - `selectPart()`: reset `state.currentSubsectionId`, disconnect observer.
  - Add `updateGhostRailActive()`, `updateSmartBarText()`.
  - Add keyboard listener for `Alt + ArrowUp/Down`.
- `frontend/js/main.js`
  - `saveViewState()`: include `subsectionId`.
  - `navigateFromRoute()`: handle `route.subsectionId` with scroll.
  - Add `IntersectionObserver` init/disconnect logic.
  - Add Smart Bar scroll visibility logic.
  - Add `saveSubsectionProgress(payload)` helper: calls `PATCH /api/projects/{id}/progress/subsection`, silently fails on network error.
- `frontend/style.css`
  - Add `.ghost-rail`, `.ghost-rail-line`, `.ghost-rail-node`, `.ghost-rail-label`.
  - Add `.smart-bar`, `.smart-bar-retracted`, `.smart-bar-progress`, `.subsection-sheet`.
  - Add `.sr-only` utility if missing.

### Optional / Future
- `frontend/js/storage.js` — no changes needed (backup pipeline handles it).
- Database migration — none needed (JSONB additive).

---

## 12. Success Metrics

- [ ] User returns to project and lands within 200px of their last subsection.
- [ ] Desktop: user can jump to any subsection in ≤2 clicks.
- [ ] Mobile: user can navigate to next/previous subsection without touching the top toolbar.
- [ ] No visual regression when a part lacks subsections.
- [ ] Lighthouse accessibility score remains ≥95.
- [ ] No console errors on rapid tab/part switching.
