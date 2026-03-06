# Explainer Tests

## Test Suite

| Suite | Command | Description |
|-------|---------|-------------|
| Unit | `npm run test` | Vitest: dom, storage, landing, export, modules (59 tests) |
| E2E | `npm run test:e2e` | Playwright: app load, views, router, forms (8 tests) |
| All | `npm run test:all` | Runs both suites sequentially |

## Unit Tests (Vitest)

- **dom.test.js**: formatDate, formatBytes, statusLabel, formatIconForResource, escHtml, nl2p
- **storage.test.js**: getLocalBackupKey, mergeProjects, loadLocalBackup, getCachedApiKeyStatus, getFirstIncompletePart
- **landing.test.js**: extractYouTubeVideoId, isValidYouTubeUrl
- **export.test.js**: sanitizeFolderName, buildSectionFolderName, prefillFromProjectName
- **modules.test.js**: Verifies all 10 frontend modules load without errors

## E2E Tests (Playwright)

- Loads app without console errors
- Verifies all views exist (auth, landing, projects, project)
- Checks auth forms, upload zone, toast container, settings modal
- Validates router hash navigation

E2E tests auto-start a local server (`npx serve frontend -p 3333`) unless `BASE_URL` is set.

## Prerequisites

```bash
npm install
npm run build   # Generates frontend/config.js
```

For E2E: Playwright installs Chromium on first run. For full browser coverage:

```bash
npx playwright install
```
