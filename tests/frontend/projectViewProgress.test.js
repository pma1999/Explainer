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

  describe('proc parts grid (failed states + progressive unlock)', () => {
    async function renderGrid(partesContenido) {
      resetDom();
      document.body.insertAdjacentHTML('beforeend', '<div id="proc-parts-grid"></div>');
      state.currentProject = {
        id: 'p1',
        segmentation: { partes: [{ numero: 1, titulo: 'Parte 1' }] },
        partes_contenido: partesContenido,
      };
      const pv = await import('../../frontend/js/projectView.js');
      pv.renderProcPartsGrid(state.currentProject);
      return pv;
    }

    it('makes the card clickable when the explainer is valid even if still processing', async () => {
      await renderGrid({
        1: { status: 'processing', explainer: { content: 'x' } },
      });

      const card = document.querySelector('#proc-parts-grid .proc-part-card');
      expect(card.classList.contains('processing')).toBe(true);
      expect(card.classList.contains('clickable')).toBe(true);

      const route = [];
      const origPushRoute = window.pushRoute;
      window.pushRoute = (r) => route.push(r);
      try {
        card.click();
        expect(route).toHaveLength(1);
        expect(route[0].partId).toBe(1);
        expect(route[0].tab).toBe('explicacion');
      } finally {
        window.pushRoute = origPushRoute;
      }
    });

    it('renders failed parts with a failed class, error message and no opening click', async () => {
      await renderGrid({
        1: { status: 'failed', error_message: 'El modelo se quedó sin contexto' },
      });

      const card = document.querySelector('#proc-parts-grid .proc-part-card');
      expect(card.classList.contains('failed')).toBe(true);
      expect(card.textContent).toContain('El modelo se quedó sin contexto');
      expect(card.classList.contains('clickable')).toBe(false);

      const route = [];
      const origPushRoute = window.pushRoute;
      window.pushRoute = (r) => route.push(r);
      try {
        card.click();
        expect(route).toHaveLength(0);
      } finally {
        window.pushRoute = origPushRoute;
      }
    });

    it('failProcPartCard flags a live card as failed with the error message', async () => {
      const pv = await renderGrid({
        1: { status: 'processing', explainer: { content: 'x' } },
      });

      const card = document.querySelector('#proc-parts-grid .proc-part-card');
      pv.failProcPartCard(1, 'El agente explicador falló');

      expect(card.classList.contains('failed')).toBe(true);
      expect(card.classList.contains('processing')).toBe(false);
      expect(card.classList.contains('completed')).toBe(false);
      expect(card.classList.contains('clickable')).toBe(false);
      expect(card.textContent).toContain('El agente explicador falló');
    });

    it('completeProcPartCard does not convert a failed card to completed', async () => {
      const pv = await renderGrid({
        1: { status: 'failed', error_message: 'boom' },
      });

      const card = document.querySelector('#proc-parts-grid .proc-part-card');
      pv.completeProcPartCard(1);

      expect(card.classList.contains('failed')).toBe(true);
      expect(card.classList.contains('completed')).toBe(false);
    });

    it('shows a preparing placeholder when some agents are ready but the tab has no data', async () => {
      resetDom();
      document.body.insertAdjacentHTML('beforeend', `
        <div id="loading-explicacion"></div>
        <div id="content-explicacion"></div>
      `);
      const pv = await import('../../frontend/js/projectView.js');
      pv.renderTab('explicacion', {
        status: 'processing',
        formatter_version: 'v1',
        explainer: null,
        recorrido: null,
        resources: null,
      });

      const content = document.getElementById('content-explicacion');
      expect(content.innerHTML).toContain('panel-preparing');
      expect(content.innerHTML).toContain('Esta sección se está generando…');
    });

    it('renders an actionable URL in resource cards', async () => {
      resetDom();
      document.body.insertAdjacentHTML('beforeend', `
        <div id="loading-recursos"></div>
        <div id="content-recursos"></div>
      `);
      const pv = await import('../../frontend/js/projectView.js');
      pv.renderTab('recursos', {
        status: 'completed',
        resources: {
          titulo_mapa: 'Mapa',
          ejes_tematicos: [{
            nombre_eje: 'Contexto',
            recursos: [{
              titulo: 'Artículo',
              autor_creador: 'Autor',
              url: 'https://example.com/articulo',
            }],
          }],
        },
      });

      const content = document.getElementById('content-recursos');
      expect(content.innerHTML).toContain('Abrir');
      expect(content.innerHTML).toContain('example.com');
      expect(content.innerHTML).toContain('target="_blank"');
      expect(content.innerHTML).toContain('rel="noopener noreferrer"');
      expect(content.innerHTML).toContain('href="https://example.com/articulo"');
    });
  });
});
