import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  user: { id: 'user-1' },
  currentProjectId: 'p1',
  currentProject: null,
  isSharedView: false,
};

const api = vi.fn();
const loadBackupAsync = vi.fn();
const syncProjectsToBackup = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({ state }));
vi.mock('../../frontend/js/api.js', () => ({ api }));
vi.mock('../../frontend/js/storage.js', () => ({
  loadBackupAsync,
  syncProjectsToBackup,
}));

function resetProject() {
  state.user = { id: 'user-1' };
  state.currentProjectId = 'p1';
  state.currentProject = {
    id: 'p1',
    updated_at: '2024-01-01T00:00:00Z',
    reading_progress: {},
  };
  state.isSharedView = false;
}

describe('progressSync', () => {
  let progressSync;

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.resetModules();
    resetProject();
    api.mockReset();
    api.mockResolvedValue({ ok: true });
    loadBackupAsync.mockReset();
    loadBackupAsync.mockResolvedValue({ projects: [state.currentProject] });
    syncProjectsToBackup.mockReset();
    syncProjectsToBackup.mockResolvedValue({ ok: true });
    progressSync = await import('../../frontend/js/progressSync.js');
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('updates last_subsection locally without an immediate network call', () => {
    const changed = progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    expect(changed).toBe(true);
    expect(api).not.toHaveBeenCalled();
    expect(state.currentProject.reading_progress.last_subsection).toEqual({
      part_id: 1,
      subsection_id: 'subsec-1-0-0',
      tab: 'explicacion',
    });
    expect(state.currentProject.reading_progress.last_read_at).toBeTruthy();
    expect(state.currentProject.updated_at).not.toBe('2024-01-01T00:00:00Z');
  });

  it('batches rapid subsection changes into one flush', async () => {
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-1',
      part_id: 1,
      tab: 'explicacion',
      completed: true,
    });
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-1',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    await vi.advanceTimersByTimeAsync(progressSync.SUBSECTION_PROGRESS_FLUSH_DEBOUNCE_MS);

    expect(api).toHaveBeenCalledTimes(1);
    expect(api.mock.calls[0][0]).toBe('/api/projects/p1/progress/subsection');
    const body = JSON.parse(api.mock.calls[0][1].body);
    expect(body).toEqual({
      part_id: 1,
      tab: 'explicacion',
      last_subsection_id: 'subsec-1-0-1',
      completed_subsection_ids: ['subsec-1-0-1'],
    });
  });

  it('does not queue remote sync for shared views', async () => {
    state.isSharedView = true;
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    await progressSync.flushSubsectionProgress({ force: true });

    expect(state.currentProject.reading_progress.last_subsection.subsection_id).toBe('subsec-1-0-0');
    expect(api).not.toHaveBeenCalled();
  });

  it('flushes pending progress when the document becomes hidden', async () => {
    progressSync.initProgressSyncLifecycle();
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      configurable: true,
    });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(api).toHaveBeenCalledTimes(1);
    expect(JSON.parse(api.mock.calls[0][1].body).last_subsection_id).toBe('subsec-1-0-0');
  });

  it('keeps progress recorded during an in-flight flush scheduled', async () => {
    let resolveFirst;
    api.mockImplementationOnce(() => new Promise((resolve) => {
      resolveFirst = resolve;
    }));

    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });
    const firstFlush = progressSync.flushSubsectionProgress({ force: true });

    expect(api).toHaveBeenCalledTimes(1);

    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-1',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    await vi.advanceTimersByTimeAsync(progressSync.SUBSECTION_PROGRESS_FLUSH_DEBOUNCE_MS);
    expect(api).toHaveBeenCalledTimes(1);

    resolveFirst({
      reading_progress: {},
      updated_at: '2024-01-02T00:00:00Z',
    });
    await firstFlush;

    await vi.advanceTimersByTimeAsync(
      progressSync.SUBSECTION_PROGRESS_FLUSH_DEBOUNCE_MS +
      progressSync.SUBSECTION_PROGRESS_MIN_FLUSH_INTERVAL_MS,
    );

    expect(api).toHaveBeenCalledTimes(2);
    expect(JSON.parse(api.mock.calls[1][1].body).last_subsection_id).toBe('subsec-1-0-1');
  });

  it('keeps local progress when the server returns a compact ok response', async () => {
    progressSync.recordSubsectionProgress({
      subsection_id: 'subsec-1-0-0',
      part_id: 1,
      tab: 'explicacion',
      is_last_read: true,
    });

    await progressSync.flushSubsectionProgress({ force: true });

    expect(api).toHaveBeenCalledTimes(1);
    expect(state.currentProject.reading_progress.last_subsection.subsection_id).toBe('subsec-1-0-0');
    expect(state.currentProject.reading_progress.last_read_at).toBeTruthy();
  });
});
