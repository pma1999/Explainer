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
    state.user = null;
    state.hasApiKey = false;
    state.apiKeyStatus = 'loading';
    vi.mocked(global.fetch).mockReset();
    vi.spyOn(storageModule, 'getCachedApiKeyStatus').mockReturnValue(null);
    vi.spyOn(storageModule, 'setCachedApiKeyStatus').mockImplementation(() => {});
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
      state.user = { id: 'user-123' };
      vi.spyOn(apiModule, 'api').mockResolvedValue({ has_api_key: true });

      await refreshApiKeyStatus();

      expect(storageModule.setCachedApiKeyStatus).toHaveBeenCalledWith('user-123', true);
    });
  });
});
