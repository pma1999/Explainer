/**
 * Vitest setup for frontend tests.
 * Mocks browser globals required by Explainer modules.
 */
import { beforeAll, vi } from 'vitest';

beforeAll(() => {
  // Mock window globals (config.js / index.html)
  window.SUPABASE_URL = '';
  window.SUPABASE_ANON_KEY = '';
  window.supabase = null;
  window.EXPLAINER_API_BASE_URL = '';

  // Ensure required DOM elements exist for modules that use $
  const toastContainer = document.getElementById('toast-container');
  if (!toastContainer) {
    const div = document.createElement('div');
    div.id = 'toast-container';
    document.body.appendChild(div);
  }

  // Mock fetch for API tests
  global.fetch = vi.fn();
});
