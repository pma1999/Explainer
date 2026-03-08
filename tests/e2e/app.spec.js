/**
 * E2E tests for Explainer frontend.
 * Verifies the app loads, critical elements exist, and no console errors.
 * Requires: frontend served (e.g. npx serve frontend -p 3333)
 * Optional: config.js with Supabase + backend API for full flow.
 */
import { test, expect } from '@playwright/test';

test.describe('Explainer App', () => {
  test('loads without console errors', async ({ page }) => {
    const errors = [];
    page.on('console', (msg) => {
      const type = msg.type();
      const text = msg.text();
      if (type === 'error' && !text.includes('favicon')) {
        errors.push(text);
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    expect(errors).toEqual([]);
  });

  test('has all required views in DOM', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.locator('#view-auth')).toBeVisible();
    await expect(page.locator('#view-landing')).toBeAttached();
    await expect(page.locator('#view-projects')).toBeAttached();
    await expect(page.locator('#view-project')).toBeAttached();
  });

  test('shows auth or landing based on session', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const authView = page.locator('#view-auth');
    const landingView = page.locator('#view-landing');

    const authVisible = await authView.isVisible();
    const landingVisible = await landingView.isVisible();

    expect(authVisible || landingVisible).toBeTruthy();
  });

  test('has critical form elements for auth', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.locator('#form-login')).toBeAttached();
    await expect(page.locator('#form-register')).toBeAttached();
    await expect(page.locator('#login-email')).toBeAttached();
    await expect(page.locator('#login-password')).toBeAttached();
  });

  test('router responds to hash changes', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    await page.evaluate(() => {
      window.location.hash = '#/projects';
    });
    await page.waitForTimeout(300);

    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toContain('projects');
  });

  test('has upload zone on landing', async ({ page }) => {
    await page.goto('/#/');
    await page.waitForLoadState('domcontentloaded');

    const uploadZone = page.locator('#upload-zone');
    const fileInput = page.locator('#file-input');
    await expect(uploadZone).toBeAttached();
    await expect(fileInput).toBeAttached();
  });

  test('has toast container', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.locator('#toast-container')).toBeAttached();
  });

  test('has settings modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.locator('#modal-settings')).toBeAttached();
  });

  test('submits a public web URL from the landing form', async ({ page }) => {
    let createBody = '';
    let processCalled = false;

    await page.route('**/api/projects', async (route) => {
      if (route.request().method() === 'POST') {
        createBody = route.request().postData() || '';
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'web-1',
            name: 'Artículo web',
            description: '',
            source_type: 'web',
            source_url: 'https://example.com/article',
            status: 'pending',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/projects/web-1/process**', async (route) => {
      processCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, status: 'started' }),
      });
    });

    await page.goto('/#/');
    await page.waitForLoadState('domcontentloaded');

    await page.evaluate(async () => {
      const { state } = await import('/js/state.js');
      const { showView } = await import('/js/dom.js');
      const landingModule = await import('/js/landing.js');

      state.hasApiKey = true;
      state.user = { id: 'user-123', email: 'test@example.com' };
      window.pushRoute = () => {};

      showView('view-landing');
      landingModule.initLanding();
    });

    await page.locator('#tab-web').click();
    await page.fill('#project-name', 'Artículo web');
    await page.fill('#web-url', 'https://example.com/article#intro');

    await expect(page.locator('#btn-upload')).toBeEnabled();
    await page.locator('#btn-upload').click();

    await expect.poll(() => processCalled).toBe(true);
    expect(createBody).toContain('name="web_url"');
    expect(createBody).toContain('https://example.com/article');
  });
});
