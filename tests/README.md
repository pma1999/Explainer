# Explainer Tests

## Test Suite

| Suite | Command | Description |
|-------|---------|--------------|
| Frontend unit | `npm run test` | Vitest: dom, storage, landing, export, router, api, shared, auth, modules |
| Backend | `npm run test:backend` | pytest via the project runner: FastAPI endpoints, supabase_data |
| E2E | `npm run test:e2e` | Playwright: app load, views, router, forms, shared view |
| All | `npm run test:all` | Runs frontend unit, backend, and E2E sequentially |

## Frontend Unit Tests (Vitest)

- **dom.test.js**: formatDate, formatBytes, statusLabel, formatIconForResource, escHtml, nl2p
- **storage.test.js**: getLocalBackupKey, mergeProjects, loadLocalBackup, getCachedApiKeyStatus, getFirstIncompletePart
- **landing.test.js**: extractYouTubeVideoId, isValidYouTubeUrl
- **export.test.js**: sanitizeFolderName, buildSectionFolderName, prefillFromProjectName
- **router.test.js**: parseRoute, buildHash for all route types (landing, projects, project, shared)
- **api.test.js**: getAccessToken, api (Authorization header, 200/401/404/500)
- **shared.test.js**: exitSharedView, loadSharedProject
- **auth.test.js**: refreshApiKeyStatus
- **modules.test.js**: Verifies all frontend modules (including main.js) load without errors

## Backend Tests (pytest)

- **test_api.py**: FastAPI TestClient for GET /api/shared/{token}, POST/DELETE /api/projects/{id}/share, GET /api/projects/{id}
- **test_supabase_data.py**: _sanitize_project_for_shared, create_share_token, revoke_share_token, get_project_by_share_token

Use the project runner instead of calling `python -m pytest` directly. It disables global pytest plugin auto-loading and loads only the async plugin required by this suite:

```bash
python scripts/run_pytest.py tests/backend/test_supabase_data.py::TestApiUpdateSubsectionProgress -v
```

Requires: `pip install -r requirements-dev.txt`.

## E2E Tests (Playwright)

- Loads app without console errors
- Verifies all views exist (auth, landing, projects, project)
- Checks auth forms, upload zone, toast container, settings modal
- Validates router hash navigation
- **Shared view**: invalid token shows error toast; valid token (mocked) shows project view; deep link #/s/token/s/partId/t/tab

E2E tests use Playwright route interception to mock `/api/shared/*` responses. No backend required for shared view tests.

E2E auto-starts a local server (`npx serve frontend -p 3333`) unless `BASE_URL` is set.

## Prerequisites

```bash
npm install
npm run build   # Generates frontend/config.js
```

For backend tests:

```bash
pip install -r requirements-dev.txt
```

For E2E: Playwright installs Chromium on first run. For full browser coverage:

```bash
npx playwright install
```
