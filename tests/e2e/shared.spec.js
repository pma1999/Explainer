/**
 * E2E tests for shared view (#/s/{token}).
 * Uses Playwright route interception to mock API responses.
 */
import { test, expect } from '@playwright/test';

test.describe('Shared view', () => {
  test('invalid token shows error toast', async ({ page }) => {
    await page.route('**/api/shared/*', (route) => {
      route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Enlace no válido o expirado' }) });
    });

    await page.goto('/#/s/fake-invalid-token');
    await page.waitForLoadState('networkidle');

    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toContain('/s/');

    await expect(page.locator('.toast.error')).toBeVisible({ timeout: 2000 });
  });

  test('valid token shows project view with route interception', async ({ page }) => {
    const mockProject = {
      id: 'e2e-proj-1',
      name: 'Shared E2E Project',
      status: 'completed',
      segmentation: {
        partes: [
          { numero: 1, titulo: 'Parte 1', contenido: 'Contenido de la parte 1' },
          { numero: 2, titulo: 'Parte 2', contenido: 'Contenido de la parte 2' },
        ],
      },
      partes_contenido: {
        '1': { explainer: { explicacion: 'Explicación' }, recorrido: { anotaciones: [] }, resources: [] },
        '2': { explainer: { explicacion: 'Explicación 2' }, recorrido: { anotaciones: [] }, resources: [] },
      },
    };

    await page.route('**/api/shared/*', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProject) });
    });

    await page.goto('/#/s/valid-e2e-token');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('#view-project')).toBeVisible();
    await expect(page.locator('.project-layout, .sidebar-nav, #project-sidebar').first()).toBeVisible({ timeout: 5000 });
  });

  test('router parses shared deep link #/s/token/s/partId/t/tab', async ({ page }) => {
    await page.route('**/api/shared/*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'p1',
          name: 'Test',
          status: 'completed',
          segmentation: { partes: [{ numero: 1, titulo: 'P1', contenido: '' }, { numero: 2, titulo: 'P2', contenido: '' }] },
          partes_contenido: { '1': { explainer: {}, recorrido: {}, resources: [] }, '2': { explainer: {}, recorrido: {}, resources: [] } },
        }),
      });
    });

    await page.goto('/#/s/token123/s/2/t/recorrido');
    await page.waitForLoadState('networkidle');

    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toContain('/s/token123');
    expect(hash).toContain('/s/2');
    expect(hash).toContain('/t/recorrido');
  });

  test('mobile subsection dock remains visible and opens the index after scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });

    const longText = Array.from({ length: 12 }, (_, i) => `Párrafo ${i + 1}. `.repeat(48)).join('\n\n');
    const mockProject = {
      id: 'mobile-subsection-project',
      name: 'Proyecto móvil',
      status: 'completed',
      segmentation: {
        partes: [{ numero: 1, titulo: 'Parte móvil', contenido: 'Contenido largo para validar navegación móvil.' }],
      },
      reading_progress: { completed_parts: [], completed_subsections: [] },
      partes_contenido: {
        '1': {
          status: 'completed',
          explainer: {
            introduccion: longText,
            desarrollo: [
              {
                titulo_seccion: 'Bloque uno',
                subsecciones: [
                  { titulo_subseccion: 'Primera subsección', explicacion_detallada: longText },
                  { titulo_subseccion: 'Segunda subsección', explicacion_detallada: longText },
                ],
              },
              {
                titulo_seccion: 'Bloque dos',
                subsecciones: [
                  { titulo_subseccion: 'Tercera subsección', explicacion_detallada: longText },
                ],
              },
            ],
          },
          recorrido: {},
          resources: {},
        },
      },
    };

    await page.route('**/api/shared/*', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProject) });
    });

    await page.goto('/#/s/mobile-token/s/1/t/explicacion');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.locator('.smart-bar')).toBeVisible({ timeout: 5000 });

    const visibleAtLoad = await page.locator('.smart-bar').evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return rect.top >= 0 && rect.bottom <= window.innerHeight;
    });
    expect(visibleAtLoad).toBe(true);

    await page.locator('#project-main').evaluate((el) => {
      el.scrollTop = 1200;
      el.dispatchEvent(new Event('scroll', { bubbles: true }));
    });

    const visibleAfterScroll = await page.locator('.smart-bar').evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return rect.top >= 0 && rect.bottom <= window.innerHeight;
    });
    expect(visibleAfterScroll).toBe(true);

    await page.locator('.smart-bar-title').click();
    await expect(page.locator('.subsection-sheet-overlay')).toBeVisible();
    await expect(page.locator('.subsection-sheet-item')).toHaveCount(3);
  });
});
