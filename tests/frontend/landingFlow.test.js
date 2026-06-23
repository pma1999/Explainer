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
    <input id="openrouter-model-custom" type="radio" name="openrouter-model" value="__custom__" />
    <div id="openrouter-model-panel" class="hidden">
      <div class="provider-grid openrouter-model-grid" id="openrouter-model-group">
        <label class="provider-card" id="openrouter-model-card-pro"></label>
        <label class="provider-card" id="openrouter-model-card-standard"></label>
        <label class="provider-card" id="openrouter-model-card-deepseek"></label>
        <label class="provider-card" id="openrouter-model-card-custom"></label>
      </div>
    </div>
    <div id="openrouter-custom-panel" class="hidden">
      <div class="form-group">
        <label for="openrouter-custom-model-combobox">Modelo</label>
        <div id="openrouter-custom-model-combobox"></div>
        <p class="input-error hidden" id="openrouter-custom-model-error">Selecciona o escribe un modelo</p>
      </div>
      <div class="form-group">
        <label for="openrouter-provider-input">Proveedor preferido (opcional)</label>
        <input type="text" class="form-input" id="openrouter-provider-input" />
      </div>
      <label class="checkbox-label">
        <input type="checkbox" id="openrouter-provider-only" />
      </label>
      <p class="input-hint hidden" id="openrouter-custom-loading"></p>
      <p class="input-error hidden" id="openrouter-custom-fetch-error"></p>
    </div>
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
    <div id="openrouter-model-card-custom"></div>
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

  describe('custom model panel (Personalizado)', () => {
    it('shows the custom panel and deselects preset cards when custom radio is selected', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [{ value: 'qwen/qwen3.6-plus', label: 'Qwen 3.6 Plus' }] });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      // Select OpenRouter provider first
      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      const customPanel = document.getElementById('openrouter-custom-panel');
      expect(customPanel.classList.contains('hidden')).toBe(false);
      expect(document.getElementById('openrouter-model-card-pro').classList.contains('selected')).toBe(false);
      expect(document.getElementById('openrouter-model-card-standard').classList.contains('selected')).toBe(false);
      expect(document.getElementById('openrouter-model-card-deepseek').classList.contains('selected')).toBe(false);
      expect(document.getElementById('openrouter-model-card-custom').classList.contains('selected')).toBe(true);
    });

    it('hides the custom panel and selects the preset when a preset radio is clicked after custom', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [{ value: 'qwen/qwen3.6-plus', label: 'Qwen 3.6 Plus' }] });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      // Select custom first
      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      // Then select a preset
      document.getElementById('openrouter-model-pro').click();
      document.getElementById('openrouter-model-pro').dispatchEvent(new Event('change', { bubbles: true }));

      const customPanel = document.getElementById('openrouter-custom-panel');
      expect(customPanel.classList.contains('hidden')).toBe(true);
      expect(document.getElementById('openrouter-model-card-custom').classList.contains('selected')).toBe(false);
      expect(document.getElementById('openrouter-model-card-pro').classList.contains('selected')).toBe(true);
    });

    it('blocks submit when custom mode is active but no model is selected', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [{ value: 'qwen/qwen3.6-plus', label: 'Qwen 3.6 Plus' }] })
        .mockResolvedValueOnce({ id: 'project-1' });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      // Switch to web source so we don't need file
      document.getElementById('tab-web').click();
      document.getElementById('project-name').value = 'Test';
      document.getElementById('web-url').value = 'https://example.com/article';
      document.getElementById('web-url').dispatchEvent(new Event('input', { bubbles: true }));

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      // Select custom but do NOT pick a model from combobox
      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      document.getElementById('btn-upload').click();
      await flushAsyncWork();

      // The custom model error should be shown
      const customModelError = document.getElementById('openrouter-custom-model-error');
      expect(customModelError.classList.contains('hidden')).toBe(false);
      expect(customModelError.textContent).toMatch(/selecciona|elige|modelo/i);
      // API should NOT have been called for process
      expect(api).toHaveBeenCalledTimes(1); // only the models fetch
    });

    it('sends custom model, provider and provider-only in payload when custom mode is active with model and provider', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [{ value: 'qwen/qwen3.6-plus', label: 'Qwen 3.6 Plus' }] })
        .mockResolvedValueOnce({ id: 'project-1' })
        .mockResolvedValueOnce({ ok: true, status: 'started' });

      const { initLanding, setCustomOpenRouterModel } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('tab-web').click();
      document.getElementById('project-name').value = 'Test custom payload';
      document.getElementById('web-url').value = 'https://example.com/article';
      document.getElementById('web-url').dispatchEvent(new Event('input', { bubbles: true }));

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      // Select custom
      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      // Set the model programmatically (simulates combobox selection)
      setCustomOpenRouterModel('qwen/qwen3.6-plus');

      // Set provider input
      const providerInput = document.getElementById('openrouter-provider-input');
      providerInput.value = 'deepseek';
      providerInput.dispatchEvent(new Event('input', { bubbles: true }));

      // Check the "only this" checkbox
      const onlyCheckbox = document.getElementById('openrouter-provider-only');
      onlyCheckbox.checked = true;
      onlyCheckbox.dispatchEvent(new Event('change', { bubbles: true }));

      document.getElementById('btn-upload').click();
      await flushAsyncWork();

      expect(api).toHaveBeenCalledTimes(3);
      expect(api).toHaveBeenNthCalledWith(
        3,
        '/api/projects/project-1/process',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            explainer_provider: 'openrouter',
            target_language: 'es-ES',
            openrouter_model: 'qwen/qwen3.6-plus',
            openrouter_provider: 'deepseek',
            openrouter_provider_only: true,
          }),
        }),
      );
    });

    it('includes only openrouter_model (no provider fields) when preset mode is active', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ id: 'project-1' })
        .mockResolvedValueOnce({ ok: true, status: 'started' });

      const { initLanding, OPENROUTER_MODEL_MIMO_PRO } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('tab-web').click();
      document.getElementById('project-name').value = 'Test preset';
      document.getElementById('web-url').value = 'https://example.com/article';
      document.getElementById('web-url').dispatchEvent(new Event('input', { bubbles: true }));

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      // Select a preset (default is already MiMo Pro)
      document.getElementById('openrouter-model-pro').checked = true;
      document.getElementById('openrouter-model-pro').dispatchEvent(new Event('change', { bubbles: true }));

      document.getElementById('btn-upload').click();
      await flushAsyncWork();

      expect(api).toHaveBeenNthCalledWith(
        2,
        '/api/projects/project-1/process',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            explainer_provider: 'openrouter',
            target_language: 'es-ES',
            openrouter_model: OPENROUTER_MODEL_MIMO_PRO,
          }),
        }),
      );
    });

    it('shows fetch-error fallback when models endpoint fails — user can still type a model id manually', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockRejectedValueOnce(new Error('Network error'));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      const fetchError = document.getElementById('openrouter-custom-fetch-error');
      expect(fetchError.classList.contains('hidden')).toBe(false);
      expect(fetchError.textContent).toMatch(/no se pudieron|cargar|modelo|escribe/i);
    });
  });
});
