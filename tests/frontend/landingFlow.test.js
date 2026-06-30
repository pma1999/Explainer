import { beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom doesn't implement scrollIntoView; stub it globally to suppress unhandled errors
// from the combobox calling el.scrollIntoView({ block: 'nearest' }).
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

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
        <label for="openrouter-provider-combobox">Proveedor preferido (opcional)</label>
        <div id="openrouter-provider-combobox"></div>
        <p class="input-error hidden" id="openrouter-provider-fetch-error"></p>
      </div>
      <label class="checkbox-label">
        <input type="checkbox" id="openrouter-provider-only" />
      </label>
      <div class="openrouter-custom-model-summary hidden" id="openrouter-custom-model-summary"></div>
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
    <div id="provider-card-gemini"><span id="provider-card-gemini-status"></span></div>
    <div id="provider-card-openrouter"><span id="provider-card-openrouter-status"></span></div>
    <div id="provider-card-deepseek"><span id="provider-card-deepseek-status"></span></div>
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
    localStorage.clear();
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
      await flushAsyncWork();

      // Set provider via combobox input
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      providerComboboxInput.value = 'deepseek';
      providerComboboxInput.dispatchEvent(new Event('input', { bubbles: true }));

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

      expect(api).toHaveBeenCalledTimes(2);
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

    it('enriches combobox items with a non-empty meta badge (context + price)', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      // Provide a rich model object with context_length and prompt_price
      api.mockResolvedValueOnce({
        models: [
          { id: 'qwen/qwen3.6-plus', name: 'Qwen 3.6 Plus', context_length: 128000, prompt_price: 0.0000005, completion_price: 0.0000015 },
        ],
      });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      // Open the combobox to trigger render() (options are rendered lazily on open)
      const comboboxInput = document.querySelector('#openrouter-custom-model-combobox input');
      expect(comboboxInput).not.toBeNull();
      comboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      // The combobox should now have rendered list items with meta spans
      const metaSpan = document.querySelector('.combobox-option-meta');
      expect(metaSpan).not.toBeNull();
      // Should contain context length badge
      expect(metaSpan.textContent).toMatch(/128K ctx/);
      // Should contain price badge (0.0000005 * 1e6 = 0.5 → $0.5/1M)
      expect(metaSpan.textContent).toMatch(/\$0\.5\/1M/);
    });

    it('populates and shows #openrouter-custom-model-summary when a model is selected', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({
          models: [
            { id: 'qwen/qwen3.6-plus', name: 'Qwen 3.6 Plus', context_length: 128000, prompt_price: 0.0000005, completion_price: 0.0000015 },
          ],
        })
        // fetchEndpointsForModel call (Task 01 contract: endpoints[])
        .mockResolvedValueOnce({ endpoints: [] });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();

      // Summary should be hidden before any selection
      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.classList.contains('hidden')).toBe(true);

      // Open the combobox to trigger render()
      const comboboxInput = document.querySelector('#openrouter-custom-model-combobox input');
      comboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      // Now trigger the combobox onSelect by clicking the first option in the list
      const firstOption = document.querySelector('.combobox-option');
      expect(firstOption).not.toBeNull();
      firstOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await flushAsyncWork();

      // Summary should now be visible with model details
      expect(summaryEl.classList.contains('hidden')).toBe(false);
      expect(summaryEl.textContent).toMatch(/Qwen 3\.6 Plus/);
      expect(summaryEl.textContent).toMatch(/qwen\/qwen3\.6-plus/);
      expect(summaryEl.textContent).toMatch(/128K ctx/);
      // No provider endpoint selected → aggregate label + model-list prices
      expect(summaryEl.textContent).toMatch(/Modelo \(agregado\)/);
      expect(summaryEl.textContent).not.toMatch(/Proveedor exacto/);
      expect(summaryEl.textContent).toMatch(/\$0\.5\/1M in/);
      expect(summaryEl.textContent).toMatch(/\$1\.5\/1M out/);
    });

    it('teardown guard: switching to preset while models fetch is in flight aborts combobox creation', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;

      // Use a deferred promise to simulate a slow fetch
      let resolveModels;
      const slowFetch = new Promise((resolve) => { resolveModels = resolve; });
      api.mockReturnValueOnce(slowFetch);

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      // Enter custom mode (kicks off the slow fetch)
      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));

      // Before the fetch resolves, switch back to preset
      document.getElementById('openrouter-model-pro').click();
      document.getElementById('openrouter-model-pro').dispatchEvent(new Event('change', { bubbles: true }));

      // Now resolve the fetch with model data
      resolveModels({ models: [{ id: 'qwen/qwen3.6-plus', name: 'Qwen', context_length: 128000, prompt_price: 0 }] });
      await flushAsyncWork();

      // The custom panel should be hidden (preset mode is active)
      const customPanel = document.getElementById('openrouter-custom-panel');
      expect(customPanel.classList.contains('hidden')).toBe(true);
      // No combobox option should have been rendered into the mount
      const comboboxOption = document.querySelector('.combobox-option');
      expect(comboboxOption).toBeNull();
    });
  });

  describe('provider endpoint hydration (Task 02)', () => {
    const RICH_MODEL = {
      id: 'qwen/qwen3.6-plus',
      name: 'Qwen 3.6 Plus',
      context_length: 128000,
      prompt_price: 0.0000005,
      completion_price: 0.0000015,
    };
    const RICH_ENDPOINT = {
      tag: 'novita/fp8',
      provider_name: 'Novita',
      name: 'Novita | qwen/qwen3.6-plus',
      context_length: 128000,
      max_completion_tokens: 16384,
      max_prompt_tokens: 120000,
      prompt_price: 0.0000005,
      completion_price: 0.0000015,
    };

    // Drives the UI into custom mode and commits the first model option,
    // which triggers fetchEndpointsForModel. Returns the model combobox input.
    async function selectCustomModel() {
      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));
      const customRadio = document.getElementById('openrouter-model-custom');
      customRadio.checked = true;
      customRadio.dispatchEvent(new Event('change', { bubbles: true }));
      await flushAsyncWork();
      const modelComboboxInput = document.querySelector('#openrouter-custom-model-combobox input');
      modelComboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      const modelOption = document.querySelector('#openrouter-custom-model-combobox .combobox-option');
      modelOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await flushAsyncWork();
      return modelComboboxInput;
    }

    it('renders provider combobox option with endpoint tag, provider_name and rich meta', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [RICH_MODEL] })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [RICH_ENDPOINT],
          stale: false,
        });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();
      await selectCustomModel();

      // Open the provider combobox so options render
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      providerComboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));

      const providerOption = document.querySelector('#openrouter-provider-combobox .combobox-option');
      expect(providerOption).not.toBeNull();
      // label is provider_name, sublabel is the canonical tag
      expect(providerOption.querySelector('.combobox-option-name').textContent).toBe('Novita');
      expect(providerOption.querySelector('.combobox-option-id').textContent).toBe('novita/fp8');
      const meta = providerOption.querySelector('.combobox-option-meta').textContent;
      expect(meta).toMatch(/128K ctx/);
      expect(meta).toMatch(/16K max out/);
      expect(meta).toMatch(/120K max in/);
      expect(meta).toMatch(/\$0\.5\/1M in/);
      expect(meta).toMatch(/\$1\.5\/1M out/);
    });

    it('selecting a provider endpoint shows Proveedor exacto summary and submits the canonical tag', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [RICH_MODEL] })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [RICH_ENDPOINT],
          stale: false,
        })
        .mockResolvedValueOnce({ id: 'project-1' })
        .mockResolvedValueOnce({ ok: true, status: 'started' });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      // Web source + name so the upload can proceed
      document.getElementById('tab-web').click();
      document.getElementById('project-name').value = 'Test endpoint pin';
      document.getElementById('web-url').value = 'https://example.com/article';
      document.getElementById('web-url').dispatchEvent(new Event('input', { bubbles: true }));

      await selectCustomModel();

      // Open provider combobox and pick the endpoint option
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      providerComboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      const providerOption = document.querySelector('#openrouter-provider-combobox .combobox-option');
      providerOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await flushAsyncWork();

      // Input display is the provider_name, NOT the tag
      expect(providerComboboxInput.value).toBe('Novita');

      // Summary switches to Proveedor exacto with endpoint-specific chips
      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.classList.contains('hidden')).toBe(false);
      expect(summaryEl.textContent).toMatch(/Proveedor exacto/);
      expect(summaryEl.textContent).toMatch(/Novita/);
      expect(summaryEl.textContent).toMatch(/novita\/fp8/);
      expect(summaryEl.textContent).toMatch(/128K ctx/);
      expect(summaryEl.textContent).toMatch(/16K max out/);
      expect(summaryEl.textContent).toMatch(/120K max in/);
      expect(summaryEl.textContent).toMatch(/\$0\.5\/1M in/);
      expect(summaryEl.textContent).toMatch(/\$1\.5\/1M out/);

      // Submit sends the canonical tag even though the display label is Novita
      document.getElementById('btn-upload').click();
      await flushAsyncWork();

      expect(api).toHaveBeenNthCalledWith(
        4,
        '/api/projects/project-1/process',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            explainer_provider: 'openrouter',
            target_language: 'es-ES',
            openrouter_model: 'qwen/qwen3.6-plus',
            openrouter_provider: 'novita/fp8',
            openrouter_provider_only: false,
          }),
        }),
      );
    });

    it('manual typed provider keeps aggregate chips and submits the typed value', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [RICH_MODEL] })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [RICH_ENDPOINT],
          stale: false,
        })
        .mockResolvedValueOnce({ id: 'project-1' })
        .mockResolvedValueOnce({ ok: true, status: 'started' });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('tab-web').click();
      document.getElementById('project-name').value = 'Test manual provider';
      document.getElementById('web-url').value = 'https://example.com/article';
      document.getElementById('web-url').dispatchEvent(new Event('input', { bubbles: true }));

      await selectCustomModel();

      // Type a provider that does not match any endpoint row (no option click)
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      providerComboboxInput.value = 'deepseek';
      providerComboboxInput.dispatchEvent(new Event('input', { bubbles: true }));
      await flushAsyncWork();

      // Summary stays on aggregate model chips — no exact endpoint chips
      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.classList.contains('hidden')).toBe(false);
      expect(summaryEl.textContent).toMatch(/Modelo \(agregado\)/);
      expect(summaryEl.textContent).not.toMatch(/Proveedor exacto/);
      expect(summaryEl.textContent).not.toMatch(/16K max out/);

      // Submit sends the typed value
      document.getElementById('btn-upload').click();
      await flushAsyncWork();

      expect(api).toHaveBeenNthCalledWith(
        4,
        '/api/projects/project-1/process',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            explainer_provider: 'openrouter',
            target_language: 'es-ES',
            openrouter_model: 'qwen/qwen3.6-plus',
            openrouter_provider: 'deepseek',
            openrouter_provider_only: false,
          }),
        }),
      );
    });

    it('editing the provider input after selecting an endpoint reverts the summary to aggregate', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({ models: [RICH_MODEL] })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [RICH_ENDPOINT],
          stale: false,
        });

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();
      await selectCustomModel();

      // Select the endpoint → exact summary
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      providerComboboxInput.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      const providerOption = document.querySelector('#openrouter-provider-combobox .combobox-option');
      providerOption.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await flushAsyncWork();

      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.textContent).toMatch(/Proveedor exacto/);

      // Manually edit the input → revert to aggregate, clear endpoint metadata
      providerComboboxInput.value = 'my-manual-provider';
      providerComboboxInput.dispatchEvent(new Event('input', { bubbles: true }));
      await flushAsyncWork();

      expect(summaryEl.textContent).toMatch(/Modelo \(agregado\)/);
      expect(summaryEl.textContent).not.toMatch(/Proveedor exacto/);
      expect(summaryEl.textContent).not.toMatch(/16K max out/);
    });
  });

  describe('provider API key status indicators', () => {
    it('shows needs-key indicator on OpenRouter card when hasOpenRouterKey is false', async () => {
      state.hasOpenRouterKey = false;

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      const openRouterCard = document.getElementById('provider-card-openrouter');
      const statusSlot = document.getElementById('provider-card-openrouter-status');

      expect(openRouterCard.classList.contains('needs-key')).toBe(true);
      expect(statusSlot.textContent).toMatch(/falta.*ajustes/i);
    });

    it('clears needs-key indicator on OpenRouter card when hasOpenRouterKey is true', async () => {
      state.hasOpenRouterKey = true;

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      const openRouterCard = document.getElementById('provider-card-openrouter');
      const statusSlot = document.getElementById('provider-card-openrouter-status');

      expect(openRouterCard.classList.contains('needs-key')).toBe(false);
      expect(statusSlot.textContent).toBe('');
    });

    it('shows needs-key indicator on Gemini card when hasApiKey is false', async () => {
      state.hasApiKey = false;

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      const geminiCard = document.getElementById('provider-card-gemini');
      const statusSlot = document.getElementById('provider-card-gemini-status');

      expect(geminiCard.classList.contains('needs-key')).toBe(true);
      expect(statusSlot.textContent).toMatch(/falta.*ajustes/i);
    });

    it('shows needs-key indicator on DeepSeek card when hasDeepSeekKey is false', async () => {
      state.hasDeepSeekKey = false;

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      const deepSeekCard = document.getElementById('provider-card-deepseek');
      const statusSlot = document.getElementById('provider-card-deepseek-status');

      expect(deepSeekCard.classList.contains('needs-key')).toBe(true);
      expect(statusSlot.textContent).toMatch(/falta.*ajustes/i);
    });

    it('clears all needs-key indicators when all required keys are present', async () => {
      state.hasApiKey = true;
      state.hasOpenRouterKey = true;
      state.hasDeepSeekKey = true;

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      expect(document.getElementById('provider-card-gemini').classList.contains('needs-key')).toBe(false);
      expect(document.getElementById('provider-card-openrouter').classList.contains('needs-key')).toBe(false);
      expect(document.getElementById('provider-card-deepseek').classList.contains('needs-key')).toBe(false);
      expect(document.getElementById('provider-card-gemini-status').textContent).toBe('');
      expect(document.getElementById('provider-card-openrouter-status').textContent).toBe('');
      expect(document.getElementById('provider-card-deepseek-status').textContent).toBe('');
    });
  });

  describe('localStorage persistence (T6)', () => {
    const SELECTOR_KEY = 'explainer.modelSelector.v1';

    it('selecting a provider persists it to localStorage', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
      expect(saved).not.toBeNull();
      expect(saved.explainerProvider).toBe('openrouter');
    });

    it('selecting a preset openrouter model persists it to localStorage', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      const { initLanding, OPENROUTER_MODEL_MIMO } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-openrouter').click();
      document.getElementById('explainer-provider-openrouter').dispatchEvent(new Event('change', { bubbles: true }));

      document.getElementById('openrouter-model-standard').checked = true;
      document.getElementById('openrouter-model-standard').dispatchEvent(new Event('change', { bubbles: true }));

      const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
      expect(saved.explainerProvider).toBe('openrouter');
      expect(saved.openrouterMode).toBe('preset');
      expect(saved.openrouterModel).toBe(OPENROUTER_MODEL_MIMO);
    });

    it('selecting a deepseek model persists it to localStorage', async () => {
      state.hasDeepSeekKey = true;
      state.hasTavilyKey = true;
      const { initLanding, DEEPSEEK_MODEL_V4_FLASH } = await import('../../frontend/js/landing.js');
      initLanding();

      document.getElementById('explainer-provider-deepseek').click();
      document.getElementById('explainer-provider-deepseek').dispatchEvent(new Event('change', { bubbles: true }));

      document.getElementById('deepseek-model-flash').checked = true;
      document.getElementById('deepseek-model-flash').dispatchEvent(new Event('change', { bubbles: true }));

      const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
      expect(saved.explainerProvider).toBe('deepseek');
      expect(saved.deepseekModel).toBe(DEEPSEEK_MODEL_V4_FLASH);
    });

    it('restores a saved gemini selection on initLanding re-entry', async () => {
      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'gemini',
        openrouterMode: 'preset',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: null,
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      expect(document.getElementById('explainer-provider-gemini').checked).toBe(true);
      expect(document.getElementById('provider-card-gemini').classList.contains('selected')).toBe(true);
    });

    it('restores a saved preset openrouter selection on initLanding re-entry', async () => {
      state.hasOpenRouterKey = true;
      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'preset',
        openrouterModel: 'xiaomi/mimo-v2.5',
        customOpenrouterModel: null,
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding, OPENROUTER_MODEL_MIMO } = await import('../../frontend/js/landing.js');
      initLanding();

      expect(document.getElementById('explainer-provider-openrouter').checked).toBe(true);
      expect(document.getElementById('openrouter-model-standard').checked).toBe(true);
      expect(document.getElementById('openrouter-model-card-standard').classList.contains('selected')).toBe(true);
    });

    it('restores a saved deepseek selection on initLanding re-entry', async () => {
      state.hasDeepSeekKey = true;
      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'deepseek',
        openrouterMode: 'preset',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: null,
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-flash',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      expect(document.getElementById('explainer-provider-deepseek').checked).toBe(true);
      expect(document.getElementById('deepseek-model-flash').checked).toBe(true);
    });

    it('falls back to gemini when the saved provider requires a missing key', async () => {
      // state.hasOpenRouterKey = false (default in beforeEach)
      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'preset',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: null,
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      // openrouter key is missing → must restore as gemini
      expect(document.getElementById('explainer-provider-gemini').checked).toBe(true);
      expect(document.getElementById('provider-card-gemini').classList.contains('selected')).toBe(true);
    });

    it('falls back to gemini when the saved deepseek provider is missing key', async () => {
      // state.hasDeepSeekKey = false (default in beforeEach)
      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'deepseek',
        openrouterMode: 'preset',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: null,
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      expect(document.getElementById('explainer-provider-gemini').checked).toBe(true);
    });

    it('restores custom openrouter mode — builds combobox and sets the saved model', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api.mockResolvedValueOnce({
        models: [
          { id: 'qwen/qwen3.6-plus', name: 'Qwen 3.6 Plus', context_length: 128000, prompt_price: 0, completion_price: 0 },
        ],
      });
      // Second call for fetchEndpointsForModel (Task 01 contract: endpoints[])
      api.mockResolvedValueOnce({ endpoints: [] });

      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'custom',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: 'qwen/qwen3.6-plus',
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();
      await flushAsyncWork();

      // Custom panel must be visible
      const customPanel = document.getElementById('openrouter-custom-panel');
      expect(customPanel.classList.contains('hidden')).toBe(false);

      // The model combobox must exist and have a value (label or id of saved model)
      const comboboxInput = document.querySelector('#openrouter-custom-model-combobox input');
      expect(comboboxInput).not.toBeNull();
      expect(comboboxInput.value).not.toBe('');
      // Should show the model name from the loaded list
      expect(comboboxInput.value).toContain('Qwen');

      // models API must have been called once (for the load)
      expect(api).toHaveBeenCalledWith('/api/openrouter/models');
    });

    it('teardown-race guard: switching away from custom before models load aborts restore', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;

      let resolveModels;
      const slowFetch = new Promise((resolve) => { resolveModels = resolve; });
      api.mockReturnValueOnce(slowFetch);

      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'custom',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: 'qwen/qwen3.6-plus',
        openrouterProvider: '',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();

      // Before models arrive, switch to a preset — this changes currentOpenRouterMode
      document.getElementById('openrouter-model-pro').click();
      document.getElementById('openrouter-model-pro').dispatchEvent(new Event('change', { bubbles: true }));

      // Now resolve models
      resolveModels({ models: [{ id: 'qwen/qwen3.6-plus', name: 'Qwen', context_length: 128000, prompt_price: 0 }] });
      await flushAsyncWork();

      // Custom panel must remain hidden (preset is active)
      const customPanel = document.getElementById('openrouter-custom-panel');
      expect(customPanel.classList.contains('hidden')).toBe(true);
    });

    it('restore custom mode with saved provider tag — refetches endpoints, matches by tag, sets provider display to provider_name, renders exact chips', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({
          models: [
            { id: 'qwen/qwen3.6-plus', name: 'Qwen 3.6 Plus', context_length: 128000, prompt_price: 0.0000005, completion_price: 0.0000015 },
          ],
        })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [
            {
              tag: 'novita/fp8',
              provider_name: 'Novita',
              name: 'Novita | qwen/qwen3.6-plus',
              context_length: 128000,
              max_completion_tokens: 16384,
              max_prompt_tokens: 120000,
              prompt_price: 0.0000005,
              completion_price: 0.0000015,
            },
          ],
          stale: false,
        });

      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'custom',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: 'qwen/qwen3.6-plus',
        openrouterProvider: 'novita/fp8',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();
      await flushAsyncWork();
      await flushAsyncWork();

      // Provider combobox display is the provider_name, not the tag
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      expect(providerComboboxInput.value).toBe('Novita');

      // Persisted provider remains the canonical tag
      const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
      expect(saved.openrouterProvider).toBe('novita/fp8');

      // Summary shows exact endpoint chips
      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.classList.contains('hidden')).toBe(false);
      expect(summaryEl.textContent).toMatch(/Proveedor exacto/);
      expect(summaryEl.textContent).toMatch(/Novita/);
      expect(summaryEl.textContent).toMatch(/novita\/fp8/);
      expect(summaryEl.textContent).toMatch(/128K ctx/);
      expect(summaryEl.textContent).toMatch(/16K max out/);
      expect(summaryEl.textContent).toMatch(/120K max in/);
      expect(summaryEl.textContent).toMatch(/\$0\.5\/1M in/);
      expect(summaryEl.textContent).toMatch(/\$1\.5\/1M out/);

      // Endpoints were refetched for the saved model
      expect(api).toHaveBeenCalledWith(expect.stringContaining('/api/openrouter/models/endpoints'));
    });

    it('restore with a saved provider tag that is not in endpoint rows sets the provider input to the saved tag and leaves aggregate model chips', async () => {
      state.hasOpenRouterKey = true;
      state.hasMistralKey = true;
      api
        .mockResolvedValueOnce({
          models: [
            { id: 'qwen/qwen3.6-plus', name: 'Qwen 3.6 Plus', context_length: 128000, prompt_price: 0, completion_price: 0 },
          ],
        })
        .mockResolvedValueOnce({
          model_id: 'qwen/qwen3.6-plus',
          model_name: 'Qwen 3.6 Plus',
          endpoints: [
            { tag: 'novita/fp8', provider_name: 'Novita', context_length: 128000, prompt_price: 0, completion_price: 0 },
          ],
          stale: false,
        });

      localStorage.setItem(SELECTOR_KEY, JSON.stringify({
        explainerProvider: 'openrouter',
        openrouterMode: 'custom',
        openrouterModel: 'xiaomi/mimo-v2.5-pro',
        customOpenrouterModel: 'qwen/qwen3.6-plus',
        openrouterProvider: 'some/other-tag',
        openrouterProviderOnly: false,
        deepseekModel: 'deepseek-v4-pro',
      }));

      const { initLanding } = await import('../../frontend/js/landing.js');
      initLanding();
      await flushAsyncWork();
      await flushAsyncWork();

      // Saved tag is not in endpoint rows → restore as manual text
      const providerComboboxInput = document.querySelector('#openrouter-provider-combobox input');
      expect(providerComboboxInput.value).toBe('some/other-tag');

      const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
      expect(saved.openrouterProvider).toBe('some/other-tag');

      // Summary stays on aggregate model chips
      const summaryEl = document.getElementById('openrouter-custom-model-summary');
      expect(summaryEl.classList.contains('hidden')).toBe(false);
      expect(summaryEl.textContent).toMatch(/Modelo \(agregado\)/);
      expect(summaryEl.textContent).not.toMatch(/Proveedor exacto/);
    });
  });
});
