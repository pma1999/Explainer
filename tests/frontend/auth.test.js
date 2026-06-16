/**
 * Unit tests for auth.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { refreshApiKeyStatus } from '../../frontend/js/auth.js';
import { state } from '../../frontend/js/state.js';
import * as apiModule from '../../frontend/js/api.js';
import * as storageModule from '../../frontend/js/storage.js';

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
