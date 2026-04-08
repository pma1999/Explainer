/**
 * Unit tests for storage.js.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getLocalBackupKey,
  mergeProjects,
  mergePairProjects,
  loadLocalBackup,
  loadBackupAsync,
  syncProjectsToBackup,
  getCachedApiKeyStatus,
  setCachedApiKeyStatus,
  getFirstIncompletePart,
} from '../../frontend/js/storage.js';
import { API_KEY_CACHE_KEY_PREFIX } from '../../frontend/js/state.js';

describe('storage.js', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe('getLocalBackupKey', () => {
    it('returns null for null/undefined userId', () => {
      expect(getLocalBackupKey(null)).toBeNull();
      expect(getLocalBackupKey(undefined)).toBeNull();
    });

    it('returns key with userId suffix', () => {
      expect(getLocalBackupKey('user-123')).toBe('explainer.projects.backup.v1.user-123');
    });
  });

  describe('mergeProjects', () => {
    it('merges server and local, preferring newer by updated_at', () => {
      const server = [
        { id: '1', name: 'Server', updated_at: '2024-01-02' },
        { id: '2', name: 'Server2', updated_at: '2024-01-03' },
      ];
      const local = [
        { id: '1', name: 'Local', updated_at: '2024-01-01' },
        { id: '3', name: 'LocalOnly', updated_at: '2024-01-01' },
      ];
      const merged = mergeProjects(server, local);
      expect(merged).toHaveLength(3);
      const p1 = merged.find((p) => p.id === '1');
      expect(p1.name).toBe('Server');
      const p3 = merged.find((p) => p.id === '3');
      expect(p3.name).toBe('LocalOnly');
    });

    it('ignores null/invalid projects', () => {
      const result = mergeProjects([{ id: '1' }, null, {}], []);
      expect(result).toHaveLength(1);
    });

    it('sorts by created_at descending', () => {
      const projects = [
        { id: '1', created_at: '2024-01-01' },
        { id: '2', created_at: '2024-01-03' },
        { id: '3', created_at: '2024-01-02' },
      ];
      const merged = mergeProjects(projects, []);
      expect(merged[0].id).toBe('2');
      expect(merged[1].id).toBe('3');
      expect(merged[2].id).toBe('1');
    });

    it('when newer server is list_summary, keeps local partes_contenido and drops list_summary', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-01T00:00:00Z',
        partes_contenido: { 1: { explainer: { foo: 'bar' } } },
        source_text: 'cached',
      };
      const server = {
        id: '1',
        name: 'Renamed',
        status: 'completed',
        updated_at: '2024-01-05T00:00:00Z',
        list_summary: true,
        segmentation: { partes: [{ numero: 1 }] },
      };
      const merged = mergeProjects([server], [local]);
      expect(merged).toHaveLength(1);
      const p = merged[0];
      expect(p.name).toBe('Renamed');
      expect(p.list_summary).toBeUndefined();
      expect(p.partes_contenido).toEqual({ 1: { explainer: { foo: 'bar' } } });
      expect(p.source_text).toBe('cached');
    });

    it('when local is newer, keeps local unchanged', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-10T00:00:00Z',
        partes_contenido: { 1: {} },
      };
      const server = {
        id: '1',
        name: 'Server',
        updated_at: '2024-01-05T00:00:00Z',
        list_summary: true,
      };
      const merged = mergeProjects([server], [local]);
      expect(merged[0].name).toBe('Local');
      expect(merged[0].partes_contenido).toEqual({ 1: {} });
    });

    it('when newer server is full object, server wins entire record', () => {
      const local = {
        id: '1',
        name: 'Local',
        updated_at: '2024-01-01T00:00:00Z',
        partes_contenido: { 1: { old: true } },
      };
      const server = {
        id: '1',
        name: 'Server',
        updated_at: '2024-01-08T00:00:00Z',
        partes_contenido: { 1: { new: true } },
      };
      const merged = mergeProjects([server], [local]);
      expect(merged[0].partes_contenido).toEqual({ 1: { new: true } });
    });
  });

  describe('mergePairProjects', () => {
    it('on equal updated_at, returns second argument', () => {
      const a = { id: '1', updated_at: '2024-01-01T00:00:00Z', name: 'A' };
      const b = { id: '1', updated_at: '2024-01-01T00:00:00Z', name: 'B' };
      expect(mergePairProjects(a, b).name).toBe('B');
    });
  });

  describe('loadLocalBackup', () => {
    it('returns empty backup for null userId', () => {
      const result = loadLocalBackup(null);
      expect(result).toEqual({ version: 1, projects: [] });
    });

    it('returns empty backup when no key exists', () => {
      const result = loadLocalBackup('user-123');
      expect(result).toEqual({ version: 1, projects: [] });
    });

    it('loads stored backup', () => {
      const key = getLocalBackupKey('user-123');
      localStorage.setItem(key, JSON.stringify({ version: 1, projects: [{ id: '1', name: 'Test' }] }));
      const result = loadLocalBackup('user-123');
      expect(result.projects).toHaveLength(1);
      expect(result.projects[0].name).toBe('Test');
    });
  });

  describe('loadBackupAsync', () => {
    it('returns empty backup for null userId', async () => {
      const result = await loadBackupAsync(null);
      expect(result).toEqual({ version: 1, projects: [] });
    });

    it('loads from localStorage fallback when IndexedDB unavailable', async () => {
      const key = getLocalBackupKey('user-123');
      localStorage.setItem(key, JSON.stringify({ version: 1, projects: [{ id: '1', name: 'Test' }] }));
      const result = await loadBackupAsync('user-123');
      expect(result.projects).toHaveLength(1);
      expect(result.projects[0].name).toBe('Test');
    });
  });

  describe('syncProjectsToBackup', () => {
    it('does not throw on QuotaExceededError, falls back to lite or returns ok: false', async () => {
      const origIndexedDB = globalThis.indexedDB;
      vi.stubGlobal('indexedDB', undefined);

      const origSetItem = localStorage.setItem.bind(localStorage);
      localStorage.setItem = vi.fn((key, value) => {
        if (key?.includes('backup') && typeof value === 'string' && value.length > 100) {
          const err = new DOMException('Quota exceeded', 'QuotaExceededError');
          err.code = 22;
          throw err;
        }
        origSetItem(key, value);
      });

      try {
        const projects = [{ id: '1', name: 'Test', status: 'completed' }];
        const result = await syncProjectsToBackup(projects, 'user-123');
        expect(result).toBeDefined();
        expect(typeof result.ok).toBe('boolean');
      } finally {
        vi.stubGlobal('indexedDB', origIndexedDB);
      }
    });

    it('saves projects to backup storage', async () => {
      const projects = [{ id: '1', name: 'Test', status: 'completed' }];
      const result = await syncProjectsToBackup(projects, 'user-123');
      expect(result.ok).toBe(true);

      const loaded = await loadBackupAsync('user-123');
      expect(loaded.projects).toHaveLength(1);
      expect(loaded.projects[0].name).toBe('Test');
    });
  });

  describe('getCachedApiKeyStatus / setCachedApiKeyStatus', () => {
    it('returns null when no cache', () => {
      expect(getCachedApiKeyStatus('user-1')).toBeNull();
    });

    it('stores and retrieves status', () => {
      setCachedApiKeyStatus('user-1', true);
      expect(getCachedApiKeyStatus('user-1')).toBe(true);
      setCachedApiKeyStatus('user-1', false);
      expect(getCachedApiKeyStatus('user-1')).toBe(false);
    });
  });

  describe('getFirstIncompletePart', () => {
    it('returns null for empty project', () => {
      expect(getFirstIncompletePart({})).toBeNull();
      expect(getFirstIncompletePart({ segmentation: { partes: [] } })).toBeNull();
    });

    it('returns first unread part number', () => {
      const project = {
        segmentation: { partes: [{ numero: 1 }, { numero: 2 }, { numero: 3 }] },
        reading_progress: { completed_parts: [1] },
      };
      expect(getFirstIncompletePart(project)).toBe(2);
    });

    it('returns first part when none read', () => {
      const project = {
        segmentation: { partes: [{ numero: 1 }, { numero: 2 }] },
      };
      expect(getFirstIncompletePart(project)).toBe(1);
    });

    it('returns null when all read', () => {
      const project = {
        segmentation: { partes: [{ numero: 1 }] },
        reading_progress: { completed_parts: [1] },
      };
      expect(getFirstIncompletePart(project)).toBeNull();
    });
  });
});
