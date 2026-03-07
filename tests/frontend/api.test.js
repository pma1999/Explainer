/**
 * Unit tests for api.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getAccessToken, api } from '../../frontend/js/api.js';
import { state } from '../../frontend/js/state.js';

describe('api.js', () => {
  beforeEach(() => {
    state.session = null;
    state.user = null;
    vi.mocked(global.fetch).mockReset();
  });

  describe('getAccessToken', () => {
    it('returns null when state.session is null', () => {
      state.session = null;
      expect(getAccessToken()).toBeNull();
    });

    it('returns access_token when state.session has it', () => {
      state.session = { access_token: 'token-xyz' };
      expect(getAccessToken()).toBe('token-xyz');
    });
  });

  describe('api', () => {
    it('adds Authorization header when token exists', async () => {
      state.session = { access_token: 'bearer-token' };
      vi.mocked(global.fetch).mockResolvedValue({
        ok: true,
        json: async () => ({}),
      });

      await api('/api/test');

      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/test'),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer bearer-token',
          }),
        })
      );
    });

    it('does not add Authorization when no token', async () => {
      state.session = null;
      vi.mocked(global.fetch).mockResolvedValue({
        ok: true,
        json: async () => ({}),
      });

      await api('/api/test');

      const call = vi.mocked(global.fetch).mock.calls[0];
      const opts = call[1] || {};
      expect(opts.headers).not.toHaveProperty('Authorization');
    });

    it('returns JSON on 200', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: true,
        json: async () => ({ id: '1', name: 'Test' }),
      });

      const result = await api('/api/projects/1');
      expect(result).toEqual({ id: '1', name: 'Test' });
    });

    it('throws on 401', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'No autorizado' }),
      });

      await expect(api('/api/protected')).rejects.toThrow('No autorizado');
    });

    it('throws on 404', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'No encontrado' }),
      });

      await expect(api('/api/missing')).rejects.toThrow('No encontrado');
    });

    it('throws on 500', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Error interno' }),
      });

      await expect(api('/api/error')).rejects.toThrow('Error interno');
    });

    it('throws fallback message when JSON parse fails', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      await expect(api('/api/error')).rejects.toThrow('Error desconocido');
    });
  });
});
