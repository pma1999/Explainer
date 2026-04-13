/**
 * Vitest setup for frontend tests.
 * Mocks browser globals required by Explainer modules.
 */
import { beforeAll, vi } from 'vitest';
import { parseRoute, buildHash, pushRoute, replaceRoute, initRouter } from '../../frontend/js/router.js';

function ensureElement(id, tag = 'div') {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement(tag);
    el.id = id;
    document.body.appendChild(el);
  }
  return el;
}

/** Stub element for $() when real element is missing - avoids addEventListener throws in bootstrap */
function createStubElement() {
  return {
    addEventListener: () => {},
    removeEventListener: () => {},
    classList: { add: () => {}, remove: () => {}, toggle: () => {}, contains: () => false },
    appendChild: () => {},
    removeChild: () => {},
    remove: () => {},
    querySelectorAll: () => [],
    querySelector: () => null,
    textContent: '',
    innerHTML: '',
    value: '',
    disabled: false,
    style: {},
    dataset: {},
    setAttribute: () => {},
    getAttribute: () => null,
    removeAttribute: () => {},
    closest: () => null,
    contains: () => false,
    open: false,
  };
}

beforeAll(() => {
  // Mock window globals (config.js / index.html)
  window.SUPABASE_URL = '';
  window.SUPABASE_ANON_KEY = '';
  window.supabase = null;
  window.EXPLAINER_API_BASE_URL = '';

  // Expose router on window for main.js bootstrap
  window.parseRoute = parseRoute;
  window.buildHash = buildHash;
  window.pushRoute = pushRoute;
  window.replaceRoute = replaceRoute;
  window.initRouter = initRouter;

  // Ensure required DOM elements exist for modules that use $
  ensureElement('toast-container');

  // PWA offline banner (real nodes — stub classList.contains breaks height sync)
  const offlineBanner = ensureElement('offline-banner');
  offlineBanner.classList.add('hidden');
  ensureElement('offline-banner-text');

  // View containers (main.js showView, bootstrap)
  ['view-auth', 'view-landing', 'view-projects', 'view-project'].forEach((id) => {
    const el = ensureElement(id);
    el.classList.add('view');
  });

  // auth-subtitle (main.js when supabase not configured)
  const viewAuth = document.getElementById('view-auth');
  if (viewAuth && !viewAuth.querySelector('.auth-subtitle')) {
    const p = document.createElement('p');
    p.className = 'auth-subtitle';
    viewAuth.appendChild(p);
  }

  // Elements used in bootstrap() - $('id').addEventListener
  const bootstrapIds = [
    'btn-home-from-projects', 'btn-new-project', 'btn-new-project-2',
    'btn-export-projects', 'import-projects-input', 'btn-back-to-projects',
    'btn-delete-project', 'shared-cta-link', 'shared-cta-floating-link',
  ];
  bootstrapIds.forEach((id) => ensureElement(id, id === 'import-projects-input' ? 'input' : 'button'));

  // tab-btn (bootstrap querySelectorAll)
  const viewProject = document.getElementById('view-project');
  if (viewProject && !viewProject.querySelector('.tab-btn')) {
    const tab = document.createElement('button');
    tab.className = 'tab-btn';
    tab.dataset.tab = 'explicacion';
    viewProject.appendChild(tab);
  }

  // Mock fetch for API tests
  global.fetch = vi.fn();

  // jsdom has no matchMedia; PWA / main.js call it at load time
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  // Return stub for missing elements so bootstrap and initSettings don't throw
  const stubEl = createStubElement();
  const origGetElementById = document.getElementById.bind(document);
  document.getElementById = (id) => origGetElementById(id) || stubEl;
});
