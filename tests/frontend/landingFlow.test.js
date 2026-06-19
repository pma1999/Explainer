import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  hasApiKey: true,
  hasOpenRouterKey: false,
  hasMistralKey: false,
  hasDeepSeekKey: false,
  hasTavilyKey: false,
  user: { id: 'user-1', email: 'test@example.com' },
};

const api = vi.fn();
const invalidateProjectsCache = vi.fn();
const loadBackupAsync = vi.fn(async () => ({ projects: [] }));
const mergeProjects = vi.fn((serverProjects, localProjects) => [...serverProjects, ...localProjects]);
const syncProjectsToBackup = vi.fn(async () => ({ ok: true }));
const updateApiKeyUI = vi.fn();
const showSettings = vi.fn();
const toast = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({ state }));
vi.mock('../../frontend/js/dom.js', () => ({
  $: (id) => document.getElementById(id),
  show: (el) => el && el.classList.remove('hidden'),
  hide: (el) => el && el.classList.add('hidden'),
  formatBytes: (bytes) => `${bytes} B`,
  toast,
}));
vi.mock('../../frontend/js/api.js', () => ({ api }));
vi.mock('../../frontend/js/storage.js', () => ({
  invalidateProjectsCache,
  loadBackupAsync,
  mergeProjects,
  syncProjectsToBackup,
}));
vi.mock('../../frontend/js/auth.js', () => ({
  updateApiKeyUI,
  showSettings,
}));

function renderLandingDom() {
  document.body.innerHTML = `
    <div id="upload-zone"></div>
    <input id="file-input" type="file" />
    <button id="btn-upload"><span class="btn-text">Iniciar análisis</span></button>
    <input id="project-name" />
    <textarea id="project-description"></textarea>
    <input id="youtube-url" />
    <input id="web-url" />
    <select id="target-language">
      <option value="es-ES">Castellano de España</option>
      <option value="en">English</option>
      <option value="fr">Français</option>
    </select>
    <input id="explainer-provider-gemini" type="radio" name="provider" checked />
    <input id="explainer-provider-openrouter" type="radio" name="provider" />
    <input id="explainer-provider-deepseek" type="radio" name="provider" />
    <input id="openrouter-model-pro" type="radio" name="openrouter-model" />
    <input id="openrouter-model-standard" type="radio" name="openrouter-model" />
    <input id="openrouter-model-deepseek" type="radio" name="openrouter-model" />
    <div id="openrouter-model-panel" class="hidden"></div>
    <input id="deepseek-model-pro" type="radio" name="deepseek-model" />
    <input id="deepseek-model-flash" type="radio" name="deepseek-model" />
    <div id="deepseek-model-panel" class="hidden"></div>
    <div id="explainer-provider-hint"></div>
    <div id="explainer-provider-error" class="hidden"></div>
    <button id="tab-pdf" type="button"></button>
    <button id="tab-youtube" type="button"></button>
    <button id="tab-web" type="button"></button>
    <div id="panel-pdf"></div>
    <div id="panel-youtube"></div>
    <div id="panel-web"></div>
    <div id="provider-card-gemini"></div>
    <div id="provider-card-openrouter"></div>
    <div id="provider-card-deepseek"></div>
    <div id="openrouter-model-card-pro"></div>
    <div id="openrouter-model-card-standard"></div>
    <div id="openrouter-model-card-deepseek"></div>
    <div id="deepseek-model-card-pro"></div>
    <div id="deepseek-model-card-flash"></div>
    <div id="upload-error"></div>
    <div id="youtube-url-error" class="hidden"></div>
    <div id="web-url-error" class="hidden"></div>
    <button id="btn-remove-file" type="button"></button>
    <div id="file-name-display"></div>
    <div id="file-size-display"></div>
    <div id="file-preview" class="hidden"></div>
    <button id="btn-go-projects" type="button"></button>
  `;
}

async function flushAsyncWork() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('landing.js project creation flow', () => {
  beforeEach(() => {
    vi.resetModules();
    api.mockReset();
    invalidateProjectsCache.mockReset();
    loadBackupAsync.mockReset();
    loadBackupAsync.mockResolvedValue({ projects: [] });
    mergeProjects.mockClear();
    syncProjectsToBackup.mockReset();
    syncProjectsToBackup.mockResolvedValue({ ok: true });
    updateApiKeyUI.mockReset();
    showSettings.mockReset();
    toast.mockReset();

    state.hasApiKey = true;
    state.hasOpenRouterKey = false;
    state.hasMistralKey = false;
    state.hasDeepSeekKey = false;
    state.hasTavilyKey = false;
    state.user = { id: 'user-1', email: 'test@example.com' };

    renderLandingDom();
    window.pushRoute = vi.fn();
  });

  it('registra los event listeners solo una vez aunque initLanding se llame varias veces (idempotencia)', async () => {
    const { initLanding } = await import('../../frontend/js/landing.js');

    // Simulate the router calling initLanding on each landing navigation
    initLanding();
    initLanding();
    initLanding();

    const fileInput = document.getElementById('file-input');
    const clickSpy = vi.spyOn(fileInput, 'click').mockImplementation(() => {});

    document.getElementById('upload-zone').click();

    // Despite three initLanding() calls, the click listener must fire exactly once
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('starts processing with the selected target language and resets the selector', async () => {
    api
      .mockResolvedValueOnce({
        id: 'project-1',
        name: 'Artículo web',
        description: '',
      })
      .mockResolvedValueOnce({ ok: true, status: 'started' });

    const { initLanding, DEFAULT_TARGET_LANGUAGE } = await import('../../frontend/js/landing.js');

    initLanding();

    document.getElementById('tab-web').click();

    const nameInput = document.getElementById('project-name');
    nameInput.value = 'Artículo web';
    nameInput.dispatchEvent(new Event('input', { bubbles: true }));

    const webUrlInput = document.getElementById('web-url');
    webUrlInput.value = 'https://example.com/article';
    webUrlInput.dispatchEvent(new Event('input', { bubbles: true }));

    const targetLanguageSelect = document.getElementById('target-language');
    targetLanguageSelect.value = 'en';
    targetLanguageSelect.dispatchEvent(new Event('change', { bubbles: true }));

    expect(document.getElementById('btn-upload').disabled).toBe(false);

    document.getElementById('btn-upload').click();
    await flushAsyncWork();

    expect(api).toHaveBeenCalledTimes(2);
    expect(api).toHaveBeenNthCalledWith(
      2,
      '/api/projects/project-1/process',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          explainer_provider: 'gemini',
          target_language: 'en',
        }),
      }),
    );
    expect(targetLanguageSelect.value).toBe(DEFAULT_TARGET_LANGUAGE);
    expect(document.getElementById('upload-error').textContent).toBe('');
  });
});
