/**
 * Unit tests for shared.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { exitSharedView, loadSharedProject } from '../../frontend/js/shared.js';
import { state } from '../../frontend/js/state.js';

describe('shared.js', () => {
  beforeEach(() => {
    state.isSharedView = false;
    state.shareToken = null;
    state.currentProjectId = null;
    state.currentProject = null;
    state.currentPartId = null;
    state.activeTab = 'explicacion';
    vi.mocked(global.fetch).mockReset();
  });

  describe('exitSharedView', () => {
    it('clears isSharedView, shareToken, currentProject, currentProjectId, currentPartId', () => {
      state.isSharedView = true;
      state.shareToken = 'token-xyz';
      state.currentProjectId = 'proj-1';
      state.currentProject = { id: 'proj-1', name: 'Test' };
      state.currentPartId = 2;

      exitSharedView();

      expect(state.isSharedView).toBe(false);
      expect(state.shareToken).toBeNull();
      expect(state.currentProjectId).toBeNull();
      expect(state.currentProject).toBeNull();
      expect(state.currentPartId).toBeNull();
    });
  });

  describe('loadSharedProject', () => {
    it('sets shared state and fetches project', async () => {
      const mockProject = {
        id: 'proj-1',
        name: 'Shared Project',
        segmentation: { partes: [{ numero: 1 }] },
      };
      vi.mocked(global.fetch).mockResolvedValue({
        ok: true,
        json: async () => mockProject,
      });

      await loadSharedProject('valid-token');

      expect(state.isSharedView).toBe(true);
      expect(state.shareToken).toBe('valid-token');
      expect(state.currentProject).toEqual(mockProject);
      expect(state.currentProjectId).toBe('proj-1');
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/shared/valid-token')
      );
    });

    it('clears shared state on 404', async () => {
      vi.mocked(global.fetch).mockResolvedValue({
        ok: false,
        status: 404,
      });

      await loadSharedProject('invalid-token');

      expect(state.isSharedView).toBe(false);
      expect(state.shareToken).toBeNull();
    });

    it('clears shared state on network error', async () => {
      vi.mocked(global.fetch).mockRejectedValue(new Error('Network error'));

      await loadSharedProject('token');

      expect(state.isSharedView).toBe(false);
      expect(state.shareToken).toBeNull();
    });

    it('sets partId and tab when provided', async () => {
      const mockProject = {
        id: 'p1',
        name: 'P',
        segmentation: { partes: [{ numero: 1 }, { numero: 2 }] },
      };
      vi.mocked(global.fetch).mockResolvedValue({
        ok: true,
        json: async () => mockProject,
      });

      await loadSharedProject('tok', 2, 'recorrido');

      expect(state.currentPartId).toBe(2);
      expect(state.activeTab).toBe('recorrido');
    });
  });
});
