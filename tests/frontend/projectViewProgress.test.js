import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  user: { id: 'user-1' },
  currentProjectId: 'p1',
  currentPartId: 1,
  activeTab: 'explicacion',
  currentProject: null,
  isSharedView: false,
  shareToken: null,
};

const api = vi.fn();
const toast = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({ state }));
vi.mock('../../frontend/js/api.js', () => ({ api }));
vi.mock('../../frontend/js/dom.js', () => ({
  $: (id) => document.getElementById(id),
  show: (el) => el?.classList.remove('hidden'),
  hide: (el) => el?.classList.add('hidden'),
  formatDate: vi.fn(() => ''),
  statusLabel: vi.fn((status) => status),
  formatIconForResource: vi.fn(() => ''),
  escHtml: vi.fn((value) => value ?? ''),
  nl2p: vi.fn((value) => value ?? ''),
  toast,
}));
vi.mock('../../frontend/js/storage.js', () => ({
  loadBackupAsync: vi.fn(),
  syncProjectsToBackup: vi.fn(),
}));
vi.mock('../../frontend/js/pwa.js', () => ({
  isOffline: vi.fn(() => false),
}));

function resetDom() {
  document.body.innerHTML = `
    <div id="sidebar-nav"></div>
    <button id="btn-toggle-complete">
      <span class="btn-toggle-complete-text"></span>
      <span class="toggle-complete-icon"></span>
    </button>
    <div id="toast-container"></div>
  `;
}

function resetProject(readingProgress = { completed_parts: [] }) {
  state.user = { id: 'user-1' };
  state.currentProjectId = 'p1';
  state.currentPartId = 1;
  state.activeTab = 'explicacion';
  state.isSharedView = false;
  state.shareToken = null;
  state.currentProject = {
    id: 'p1',
    updated_at: '2024-01-01T00:00:00Z',
    segmentation: {
      partes: [{ numero: 1, titulo: 'Parte 1' }],
    },
    partes_contenido: {
      1: { status: 'completed' },
    },
    reading_progress: readingProgress,
  };
}

describe('projectView section progress sync', () => {
  let projectView;

  beforeEach(async () => {
    vi.resetModules();
    resetDom();
    resetProject();
    api.mockReset();
    api.mockResolvedValue({ ok: true });
    toast.mockReset();
    projectView = await import('../../frontend/js/projectView.js');
  });

  it('marks a section complete locally when the API returns compact ok', async () => {
    await projectView.markSectionComplete(1);

    expect(api).toHaveBeenCalledWith('/api/projects/p1/progress', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_id: 1 }),
    });
    expect(state.currentProject.reading_progress.completed_parts).toEqual([1]);
    expect(state.currentProject.reading_progress.last_read_at).toBeTruthy();
    expect(state.currentProject.updated_at).not.toBe('2024-01-01T00:00:00Z');
  });

  it('keeps optimistic toggle changes when the API returns compact ok', async () => {
    resetProject({ completed_parts: [1] });

    await projectView.toggleSectionComplete(1, false);

    expect(api).toHaveBeenCalledWith('/api/projects/p1/progress', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_id: 1, completed: false }),
    });
    expect(state.currentProject.reading_progress.completed_parts).toEqual([]);
    expect(toast).not.toHaveBeenCalled();
  });

  it('rolls back optimistic toggle changes when the API fails', async () => {
    resetProject({ completed_parts: [1], last_read_at: '2024-01-01T00:00:00Z' });
    api.mockRejectedValueOnce(new Error('network'));

    await projectView.toggleSectionComplete(1, false);

    expect(state.currentProject.reading_progress.completed_parts).toEqual([1]);
    expect(state.currentProject.reading_progress.last_read_at).toBe('2024-01-01T00:00:00Z');
    expect(state.currentProject.updated_at).toBe('2024-01-01T00:00:00Z');
    expect(toast).toHaveBeenCalledWith('Error al actualizar el progreso', 'error');
  });
});
