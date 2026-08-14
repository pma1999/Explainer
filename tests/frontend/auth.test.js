/**
 * Unit tests for auth.js.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  refreshApiKeyStatus,
  updateApiKeyUI,
  initSettings,
  hideSettings,
  startCodexLink,
  cancelCodexLink,
  unlinkCodexAccount,
} from '../../frontend/js/auth.js';
import { state } from '../../frontend/js/state.js';
import * as apiModule from '../../frontend/js/api.js';
import * as storageModule from '../../frontend/js/storage.js';

function renderCodexDom() {
  document.body.innerHTML = `
    <div id="toast-container"></div>
    <div id="modal-settings">
      <div id="settings-email"></div>
      <div id="codex-link-not-set" class="api-key-status hidden"></div>
      <div id="codex-link-pending" class="api-key-status hidden"></div>
      <div id="codex-link-set" class="api-key-status hidden">
        <p id="codex-link-set-text"></p>
      </div>
      <div id="codex-link-failed" class="api-key-status hidden">
        <p id="codex-link-failed-text"></p>
      </div>
      <button type="button" id="btn-start-codex-link">
        <span class="btn-text">Vincular cuenta ChatGPT</span>
        <span class="spinner hidden"></span>
      </button>
      <div id="codex-device-panel" class="hidden">
        <a id="codex-verification-url" href="#" target="_blank" rel="noopener noreferrer"></a>
        <input id="codex-user-code" readonly />
        <button type="button" id="btn-copy-codex-code"><span class="btn-text">Copiar</span></button>
        <p id="codex-device-hint"></p>
        <p id="codex-link-error" class="hidden"></p>
        <button type="button" id="btn-cancel-codex-link">Cancelar</button>
      </div>
      <button type="button" id="btn-unlink-codex" style="display:none">Desvincular</button>
    </div>
    <div id="provider-card-codex"><span id="provider-card-codex-status"></span></div>
    <p id="codex-panel-link-status">
      <span id="codex-panel-link-text"></span>
      <button type="button" id="codex-panel-btn-link" style="display:none">Vincular cuenta ChatGPT</button>
      <button type="button" id="codex-panel-btn-unlink" style="display:none">Desvincular</button>
    </p>
  `;
}

function isHidden(id) {
  const el = document.getElementById(id);
  return el.classList.contains('hidden');
}

async function flushAsyncWork() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('auth.js', () => {
  beforeEach(() => {
    state.user = { id: 'user-123' };
    state.hasApiKey = false;
    state.apiKeyStatus = 'loading';
    vi.mocked(global.fetch).mockReset();
    vi.spyOn(storageModule, 'getCachedApiKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedApiKeyStatus').mockImplementation(() => {});
    vi.spyOn(storageModule, 'getCachedOpenRouterKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedOpenRouterKeyStatus').mockImplementation(() => {});
    vi.spyOn(storageModule, 'getCachedMistralKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedMistralKeyStatus').mockImplementation(() => {});
    vi.spyOn(storageModule, 'getCachedDeepSeekKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedDeepSeekKeyStatus').mockImplementation(() => {});
    vi.spyOn(storageModule, 'getCachedTavilyKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedTavilyKeyStatus').mockImplementation(() => {});
  });

  describe('refreshApiKeyStatus', () => {
    it('updates state when API returns has_api_key true', async () => {
      vi.spyOn(apiModule, 'api').mockResolvedValue({ has_api_key: true });

      await refreshApiKeyStatus();

      expect(state.hasApiKey).toBe(true);
      expect(state.apiKeyStatus).toBe('has');
    });

    it('updates state when API returns has_api_key false', async () => {
      vi.spyOn(apiModule, 'api').mockResolvedValue({ has_api_key: false });

      await refreshApiKeyStatus();

      expect(state.hasApiKey).toBe(false);
      expect(state.apiKeyStatus).toBe('none');
    });

    it('uses cached value for initial state when available', async () => {
      vi.spyOn(storageModule, 'getCachedApiKeyStatus').mockReturnValue(true);
      vi.spyOn(apiModule, 'api').mockResolvedValue({ has_api_key: true });

      await refreshApiKeyStatus();

      expect(state.hasApiKey).toBe(true);
      expect(state.apiKeyStatus).toBe('has');
    });

    it('sets state to none on API error', async () => {
      vi.spyOn(apiModule, 'api').mockRejectedValue(new Error('Network error'));

      await refreshApiKeyStatus();

      expect(state.hasApiKey).toBe(false);
      expect(state.apiKeyStatus).toBe('none');
    });

    it('calls setCachedApiKeyStatus with userId and result', async () => {
      vi.spyOn(apiModule, 'api').mockResolvedValue({ has_api_key: true });

      await refreshApiKeyStatus();

      expect(storageModule.setCachedApiKeyStatus).toHaveBeenCalledWith('user-123', true);
    });
  });
});

it('refreshApiKeyStatus hydrates mistral key state from the API payload', async () => {
  state.hasMistralKey = false;
  state.mistralKeyStatus = 'loading';
  vi.spyOn(storageModule, 'getCachedMistralKeyStatus').mockReturnValue(null);
  vi.spyOn(storageModule, 'setCachedMistralKeyStatus').mockImplementation(() => {});
  vi.spyOn(apiModule, 'api').mockResolvedValue({
    has_api_key: true,
    has_openrouter_key: true,
    has_mistral_key: true,
  });

  await refreshApiKeyStatus();

  expect(state.hasMistralKey).toBe(true);
  expect(state.mistralKeyStatus).toBe('has');
});

it('refreshApiKeyStatus hydrates DeepSeek and Tavily key state from the API payload', async () => {
  state.hasDeepSeekKey = false;
  state.deepSeekKeyStatus = 'loading';
  state.hasTavilyKey = false;
  state.tavilyKeyStatus = 'loading';
  vi.spyOn(storageModule, 'getCachedDeepSeekKeyStatus').mockReturnValue(null);
  vi.spyOn(storageModule, 'setCachedDeepSeekKeyStatus').mockImplementation(() => {});
  vi.spyOn(storageModule, 'getCachedTavilyKeyStatus').mockReturnValue(null);
  vi.spyOn(storageModule, 'setCachedTavilyKeyStatus').mockImplementation(() => {});
  vi.spyOn(apiModule, 'api').mockResolvedValue({
    has_api_key: false,
    has_openrouter_key: false,
    has_mistral_key: false,
    has_deepseek_key: true,
    has_tavily_key: true,
  });

  await refreshApiKeyStatus();

  expect(state.hasDeepSeekKey).toBe(true);
  expect(state.deepSeekKeyStatus).toBe('has');
  expect(state.hasTavilyKey).toBe(true);
  expect(state.tavilyKeyStatus).toBe('has');
});

describe('auth.js codex link (ChatGPT)', () => {
  beforeEach(() => {
    renderCodexDom();
    initSettings();
    state.user = { id: 'user-123' };
    state.hasCodexLink = false;
    state.codexLinkStatus = 'none';
    state.codexPlanType = null;
    vi.spyOn(storageModule, 'getCachedCodexLinkStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedCodexLinkStatus').mockImplementation(() => {});
    window.confirm = vi.fn(() => true);
    navigator.clipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    vi.mocked(global.fetch).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('refreshApiKeyStatus', () => {
    it('hydrates codex link state and caches it when the account is linked', async () => {
      vi.spyOn(apiModule, 'api').mockResolvedValue({
        has_api_key: false,
        has_openrouter_key: false,
        has_mistral_key: false,
        has_deepseek_key: false,
        has_tavily_key: false,
        has_codex_link: true,
        codex_status: 'linked',
        codex_plan_type: 'plus',
        codex_updated_at: '2026-08-14T00:00:00Z',
      });

      await refreshApiKeyStatus();

      expect(state.hasCodexLink).toBe(true);
      expect(state.codexLinkStatus).toBe('linked');
      expect(state.codexPlanType).toBe('plus');
      expect(storageModule.setCachedCodexLinkStatus).toHaveBeenCalledWith(
        'user-123',
        expect.objectContaining({ hasCodexLink: true, codexStatus: 'linked', codexPlanType: 'plus' }),
      );
    });

    it('hydrates a failed codex status without inventing a plan type', async () => {
      vi.spyOn(apiModule, 'api').mockResolvedValue({
        has_api_key: false,
        has_codex_link: false,
        codex_status: 'failed',
        codex_plan_type: null,
      });

      await refreshApiKeyStatus();

      expect(state.hasCodexLink).toBe(false);
      expect(state.codexLinkStatus).toBe('failed');
      expect(state.codexPlanType).toBeNull();
    });

    it('seeds codex state from the cache before the network call', async () => {
      vi.spyOn(storageModule, 'getCachedCodexLinkStatus').mockReturnValue({
        hasCodexLink: true,
        codexStatus: 'linked',
        codexPlanType: 'pro',
      });
      vi.spyOn(apiModule, 'api').mockResolvedValue({
        has_api_key: false,
        has_codex_link: true,
        codex_status: 'linked',
        codex_plan_type: 'pro',
      });

      await refreshApiKeyStatus();

      expect(state.hasCodexLink).toBe(true);
      expect(state.codexLinkStatus).toBe('linked');
      expect(state.codexPlanType).toBe('pro');
    });
  });

  describe('updateApiKeyUI rendering', () => {
    it('renders the linked state in Ajustes, on the card and in the selector sub-panel', () => {
      state.hasCodexLink = true;
      state.codexLinkStatus = 'linked';
      state.codexPlanType = 'plus';

      updateApiKeyUI();

      expect(isHidden('codex-link-set')).toBe(false);
      expect(isHidden('codex-link-not-set')).toBe(true);
      expect(isHidden('codex-link-pending')).toBe(true);
      expect(isHidden('codex-link-failed')).toBe(true);
      expect(document.getElementById('codex-link-set-text').textContent).toMatch(/plus/);
      expect(document.getElementById('btn-start-codex-link').style.display).toBe('none');
      expect(document.getElementById('btn-unlink-codex').style.display).toBe('inline-block');
      expect(document.getElementById('provider-card-codex-status').textContent).toBe('Vinculada · plus');
      expect(document.getElementById('codex-panel-link-text').textContent).toBe('Vinculada · plus');
      expect(document.getElementById('codex-panel-btn-unlink').style.display).toBe('inline-block');
      expect(document.getElementById('codex-panel-btn-link').style.display).toBe('none');
    });

    it('renders the pending state', () => {
      state.codexLinkStatus = 'pending';

      updateApiKeyUI();

      expect(isHidden('codex-link-pending')).toBe(false);
      expect(isHidden('codex-link-set')).toBe(true);
      expect(document.getElementById('btn-start-codex-link').style.display).toBe('none');
      expect(document.getElementById('provider-card-codex-status').textContent).toMatch(/pendiente/i);
    });

    it('renders the failed state with a generic retry message when last_error is unknown', () => {
      state.codexLinkStatus = 'failed';

      updateApiKeyUI();

      expect(isHidden('codex-link-failed')).toBe(false);
      expect(document.getElementById('codex-link-failed-text').textContent).toMatch(/falló|reinic/i);
      expect(document.getElementById('btn-start-codex-link').style.display).toBe('inline-block');
    });

    it('renders the none state with the start button', () => {
      state.codexLinkStatus = 'none';

      updateApiKeyUI();

      expect(isHidden('codex-link-not-set')).toBe(false);
      expect(document.getElementById('btn-start-codex-link').style.display).toBe('inline-block');
      expect(document.getElementById('btn-unlink-codex').style.display).toBe('none');
      expect(document.getElementById('provider-card-codex-status').textContent).toMatch(/vincula/i);
    });
  });

  describe('device-code flow', () => {
    const START_RESPONSE = {
      ok: true,
      verification_url: 'https://chatgpt.com/device/verify',
      user_code: 'ABCD-EFGH',
      login_id: 'fake-login-1',
      expires_in: 600,
    };

    beforeEach(() => {
      // Isolate api history/queue per test (spyOn on an already-mocked export
      // keeps the same mock instance across tests in this file).
      vi.mocked(apiModule.api).mockReset();
    });

    it('start shows the device panel with the verification URL and the copyable code', async () => {
      vi.useFakeTimers();
      apiModule.api.mockResolvedValueOnce(START_RESPONSE);

      await startCodexLink();

      expect(isHidden('codex-device-panel')).toBe(false);
      const urlEl = document.getElementById('codex-verification-url');
      expect(urlEl.href).toBe('https://chatgpt.com/device/verify');
      expect(urlEl.textContent).toBe('https://chatgpt.com/device/verify');
      expect(urlEl.target).toBe('_blank');
      expect(urlEl.rel).toBe('noopener noreferrer');
      expect(document.getElementById('codex-user-code').value).toBe('ABCD-EFGH');
      expect(state.codexLinkStatus).toBe('pending');
    });

    it('polls every 3 s and links when the server reports linked', async () => {
      vi.useFakeTimers();
      apiModule.api
        .mockResolvedValueOnce(START_RESPONSE)
        .mockResolvedValueOnce({ ok: true, codex_status: 'pending', codex_plan_type: null, last_error: null })
        .mockResolvedValueOnce({ ok: true, codex_status: 'linked', codex_plan_type: 'plus', last_error: null });

      await startCodexLink();

      await vi.advanceTimersByTimeAsync(3000);
      expect(apiModule.api).toHaveBeenCalledWith('/api/settings/codex-link/status');
      expect(state.codexLinkStatus).toBe('pending');

      await vi.advanceTimersByTimeAsync(3000);
      expect(state.hasCodexLink).toBe(true);
      expect(state.codexLinkStatus).toBe('linked');
      expect(state.codexPlanType).toBe('plus');
      expect(isHidden('codex-device-panel')).toBe(true);
      expect(storageModule.setCachedCodexLinkStatus).toHaveBeenCalledWith(
        'user-123',
        expect.objectContaining({ hasCodexLink: true, codexStatus: 'linked', codexPlanType: 'plus' }),
      );

      // Interval must be stopped: further time produces no more status calls
      const callsBefore = apiModule.api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(9000);
      expect(apiModule.api.mock.calls.length).toBe(callsBefore);
    });

    it('renders last_error when the server reports failed', async () => {
      vi.useFakeTimers();
      apiModule.api
        .mockResolvedValueOnce(START_RESPONSE)
        .mockResolvedValueOnce({
          ok: true,
          codex_status: 'failed',
          codex_plan_type: null,
          last_error: 'El vínculo caducó por un reinicio del servidor. Vuelve a iniciarlo.',
        });

      await startCodexLink();
      await vi.advanceTimersByTimeAsync(3000);

      expect(state.codexLinkStatus).toBe('failed');
      expect(state.hasCodexLink).toBe(false);
      expect(isHidden('codex-link-failed')).toBe(false);
      expect(document.getElementById('codex-link-failed-text').textContent)
        .toBe('El vínculo caducó por un reinicio del servidor. Vuelve a iniciarlo.');
      expect(isHidden('codex-device-panel')).toBe(true);
    });

    it('marks the link as expired after 10 minutes of pending and stops polling', async () => {
      vi.useFakeTimers();
      apiModule.api
        .mockResolvedValueOnce(START_RESPONSE)
        .mockResolvedValue({ ok: true, codex_status: 'pending', codex_plan_type: null, last_error: null });

      await startCodexLink();
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000 + 3000);

      expect(state.codexLinkStatus).toBe('failed');
      expect(isHidden('codex-link-failed')).toBe(false);
      expect(document.getElementById('codex-link-failed-text').textContent).toMatch(/caduc/i);

      const callsBefore = apiModule.api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(9000);
      expect(apiModule.api.mock.calls.length).toBe(callsBefore);
    });

    it('cancel calls the endpoint, stops polling and resets the UI to none', async () => {
      vi.useFakeTimers();
      apiModule.api
        .mockResolvedValueOnce(START_RESPONSE)
        .mockResolvedValue({ ok: true, codex_status: 'pending', codex_plan_type: null, last_error: null });

      await startCodexLink();
      await vi.advanceTimersByTimeAsync(3000);
      expect(apiModule.api).toHaveBeenCalledWith('/api/settings/codex-link/status');

      apiModule.api.mockResolvedValueOnce({ ok: true });
      await cancelCodexLink();

      expect(apiModule.api).toHaveBeenCalledWith('/api/settings/codex-link/cancel', { method: 'POST' });
      expect(state.codexLinkStatus).toBe('none');
      expect(isHidden('codex-device-panel')).toBe(true);

      const callsBefore = apiModule.api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(9000);
      expect(apiModule.api.mock.calls.length).toBe(callsBefore);
    });

    it('unlink requires confirmation and calls DELETE', async () => {
      state.hasCodexLink = true;
      state.codexLinkStatus = 'linked';
      state.codexPlanType = 'plus';
      apiModule.api.mockResolvedValueOnce({ ok: true });
      window.confirm.mockReturnValue(true);

      await unlinkCodexAccount();

      expect(apiModule.api).toHaveBeenCalledWith('/api/settings/codex-link', { method: 'DELETE' });
      expect(state.hasCodexLink).toBe(false);
      expect(state.codexLinkStatus).toBe('none');
      expect(state.codexPlanType).toBeNull();
      expect(storageModule.setCachedCodexLinkStatus).toHaveBeenCalledWith(
        'user-123',
        expect.objectContaining({ hasCodexLink: false, codexStatus: 'none' }),
      );
    });

    it('unlink without confirmation does not call DELETE', async () => {
      state.hasCodexLink = true;
      state.codexLinkStatus = 'linked';
      window.confirm.mockReturnValue(false);

      await unlinkCodexAccount();

      expect(apiModule.api).not.toHaveBeenCalled();
      expect(state.hasCodexLink).toBe(true);
    });

    it('copy button copies the user code', async () => {
      document.getElementById('codex-user-code').value = 'ABCD-EFGH';

      document.getElementById('btn-copy-codex-code').click();
      await flushAsyncWork();

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('ABCD-EFGH');
    });

    it('hideSettings stops the polling interval', async () => {
      vi.useFakeTimers();
      apiModule.api
        .mockResolvedValueOnce(START_RESPONSE)
        .mockResolvedValue({ ok: true, codex_status: 'pending', codex_plan_type: null, last_error: null });

      await startCodexLink();
      await vi.advanceTimersByTimeAsync(3000);
      expect(apiModule.api).toHaveBeenCalledWith('/api/settings/codex-link/status');

      hideSettings();
      const callsBefore = apiModule.api.mock.calls.length;
      await vi.advanceTimersByTimeAsync(9000);
      expect(apiModule.api.mock.calls.length).toBe(callsBefore);
    });
  });
});
