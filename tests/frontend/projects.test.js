/**
 * Unit tests for project boot/loading behavior.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const state = {
  user: { id: 'user-1' },
  currentProjectId: null,
  currentPartId: null,
  activeTab: 'explicacion',
  currentProject: null,
  processingSSE: null,
  sseProjectId: null,
};

const showView = vi.fn();
const toast = vi.fn();
const api = vi.fn();
const showProjectLoadingState = vi.fn();
const showSectionLoadingState = vi.fn();
const renderProjectView = vi.fn();
const selectPart = vi.fn();
const activateTab = vi.fn();
const syncProcessingUIWithState = vi.fn();
const loadBackupAsync = vi.fn(async () => ({ projects: [] }));
const syncProjectsToBackup = vi.fn(async () => ({ ok: true }));
const ensureProjectsFetched = vi.fn(async () => []);
const getCachedProjectAsync = vi.fn();
const getFirstIncompletePart = vi.fn(() => null);
const mergeProjects = vi.fn((serverProjects, localProjects) => [...serverProjects, ...localProjects]);
const invalidateProjectsCache = vi.fn();
const rehydrateProjectToServer = vi.fn();
const startSSE = vi.fn();
const stopPolling = vi.fn();
const closeSSEIfDifferent = vi.fn();
const startProjectsListPolling = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({ state }));
vi.mock('../../frontend/js/dom.js', () => ({
  $: vi.fn(),
  show: vi.fn(),
  hide: vi.fn(),
  showView,
  formatDate: vi.fn(() => ''),
  statusLabel: vi.fn(() => ''),
  escHtml: vi.fn((value) => value ?? ''),
  toast,
}));
vi.mock('../../frontend/js/api.js', () => ({ api }));
vi.mock('../../frontend/js/storage.js', () => ({
  loadBackupAsync,
  mergeProjects,
  syncProjectsToBackup,
  ensureProjectsFetched,
  invalidateProjectsCache,
  getCachedProjectAsync,
  getFirstIncompletePart,
  rehydrateProjectToServer,
}));
vi.mock('../../frontend/js/projectView.js', () => ({
  renderProjectView,
  selectPart,
  activateTab,
  syncProcessingUIWithState,
  showProjectLoadingState,
  showSectionLoadingState,
}));
vi.mock('../../frontend/js/sse.js', () => ({
  stopPolling,
  closeSSEIfDifferent,
  startSSE,
  startProjectsListPolling,
}));

describe('projects.js boot behavior', () => {
  beforeEach(() => {
    vi.resetModules();
    showView.mockReset();
    toast.mockReset();
    api.mockReset();
    showProjectLoadingState.mockReset();
    showSectionLoadingState.mockReset();
    renderProjectView.mockReset();
    selectPart.mockReset();
    activateTab.mockReset();
    syncProcessingUIWithState.mockReset();
    loadBackupAsync.mockReset();
    loadBackupAsync.mockResolvedValue({ projects: [] });
    syncProjectsToBackup.mockReset();
    syncProjectsToBackup.mockResolvedValue({ ok: true });
    ensureProjectsFetched.mockReset();
    ensureProjectsFetched.mockResolvedValue([]);
    getCachedProjectAsync.mockReset();
    getFirstIncompletePart.mockReset();
    getFirstIncompletePart.mockReturnValue(null);
    mergeProjects.mockClear();
    invalidateProjectsCache.mockReset();
    rehydrateProjectToServer.mockReset();
    startSSE.mockReset();
    stopPolling.mockReset();
    closeSSEIfDifferent.mockReset();
    startProjectsListPolling.mockReset();

    state.user = { id: 'user-1' };
    state.currentProjectId = null;
    state.currentPartId = null;
    state.activeTab = 'explicacion';
    state.currentProject = null;
    state.processingSSE = null;
    state.sseProjectId = null;

    global.window = {
      replaceRoute: vi.fn(),
      pushRoute: vi.fn(),
    };
  });

  it('primes section loading UI before awaiting cache lookup on deep links', async () => {
    const project = {
      id: 'p1',
      status: 'completed',
      segmentation: { partes: [{ numero: 4 }] },
    };

    let resolveCache;
    getCachedProjectAsync.mockReturnValue(new Promise((resolve) => {
      resolveCache = resolve;
    }));
    api.mockResolvedValue(project);

    const { restoreProjectView } = await import('../../frontend/js/projects.js');
    const restorePromise = restoreProjectView('p1', 4, 'explicacion');

    expect(showSectionLoadingState).toHaveBeenCalledWith(4);
    expect(showView).toHaveBeenCalledWith('view-project');
    expect(showSectionLoadingState.mock.invocationCallOrder[0]).toBeLessThan(showView.mock.invocationCallOrder[0]);
    expect(api).not.toHaveBeenCalled();

    resolveCache(null);
    await restorePromise;

    expect(api).toHaveBeenCalledWith('/api/projects/p1');
  });

  it('primes generic project loading UI before fetching the project', async () => {
    const project = {
      id: 'p1',
      status: 'completed',
      segmentation: { partes: [{ numero: 1 }] },
    };
    api.mockResolvedValue(project);

    const { openProjectView } = await import('../../frontend/js/projects.js');
    await openProjectView('p1');

    expect(showProjectLoadingState).toHaveBeenCalledTimes(1);
    expect(showView).toHaveBeenCalledWith('view-project');
    expect(api).toHaveBeenCalledWith('/api/projects/p1');
    expect(showProjectLoadingState.mock.invocationCallOrder[0]).toBeLessThan(showView.mock.invocationCallOrder[0]);
    expect(showView.mock.invocationCallOrder[0]).toBeLessThan(api.mock.invocationCallOrder[0]);
  });

  it('renders the cached section immediately on warm cache deep links', async () => {
    const cachedProject = {
      id: 'p1',
      status: 'completed',
      segmentation: { partes: [{ numero: 4 }] },
    };

    getCachedProjectAsync.mockResolvedValue(cachedProject);
    api.mockResolvedValue(cachedProject);

    const { restoreProjectView } = await import('../../frontend/js/projects.js');
    await restoreProjectView('p1', 4, 'explicacion');

    expect(showSectionLoadingState).toHaveBeenCalledWith(4);
    expect(renderProjectView).toHaveBeenCalledWith(cachedProject);
    expect(selectPart).toHaveBeenCalledWith(4);
    expect(activateTab).toHaveBeenCalledWith('explicacion');
    expect(api).toHaveBeenCalledWith('/api/projects/p1');
  });

  it('normalizes invalid part ids back to the project route after loading', async () => {
    const project = {
      id: 'p1',
      status: 'completed',
      segmentation: { partes: [{ numero: 1 }] },
    };

    getCachedProjectAsync.mockResolvedValue(null);
    api.mockResolvedValue(project);

    const { restoreProjectView } = await import('../../frontend/js/projects.js');
    await restoreProjectView('p1', 99, 'explicacion');

    expect(global.window.replaceRoute).toHaveBeenCalledWith({ view: 'project', projectId: 'p1' });
  });

  it('keeps processing projects on the SSE path', async () => {
    const project = {
      id: 'p1',
      status: 'processing',
      segmentation: { partes: [{ numero: 1 }] },
    };
    api.mockResolvedValue(project);

    const { openProjectView } = await import('../../frontend/js/projects.js');
    await openProjectView('p1');

    expect(closeSSEIfDifferent).toHaveBeenCalledWith('p1');
    expect(startSSE).toHaveBeenCalledWith('p1');
  });
});
