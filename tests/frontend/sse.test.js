/**
 * Tests for sse.js — fetch + ReadableStream transport (A4-FE).
 * Verifies that startSSE sends the JWT via the Authorization header
 * instead of the query string, parses SSE frames manually, keeps an
 * EventSource-compatible wrapper on state.processingSSE, and reconnects
 * with backoff on network errors.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  currentProjectId: null,
  currentProject: null,
  currentPartId: null,
  activeTab: 'explicacion',
  isSharedView: false,
  shareToken: null,
  processingSSE: null,
  sseProjectId: null,
  sseReconnectAttempts: 0,
  sseLastEventAt: 0,
  ssePausedByVisibility: false,
  pollProjectsInterval: null,
  pollCurrentProjectInterval: null,
  session: { access_token: 'test-token' },
  user: { id: 'user-1' },
  previousUserId: null,
  lastPartChangeAt: 0,
};

const toast = vi.fn();
const failProcPartCard = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({
  state,
  SSE_RECONNECT_MAX: 5,
  SSE_RECONNECT_DELAY_MS: 2000,
  POLL_PROJECTS_MS: 6000,
  POLL_CURRENT_IF_IDLE_MS: 12000,
  VISIBILITY_RECONNECT_DELAY_MS: 800,
}));
vi.mock('../../frontend/js/api.js', () => ({
  api: vi.fn(),
  API_BASE_URL: 'https://api.example.test',
  getAccessToken: () => state.session?.access_token || null,
}));
vi.mock('../../frontend/js/dom.js', () => ({
  $: (id) => document.getElementById(id),
  show: (el) => el?.classList.remove('hidden'),
  hide: (el) => el?.classList.add('hidden'),
  toast,
}));
vi.mock('../../frontend/js/pwa.js', () => ({ isOffline: () => false }));
vi.mock('../../frontend/js/auth.js', () => ({ refreshApiKeyStatus: vi.fn() }));
vi.mock('../../frontend/js/storage.js', () => ({
  loadBackupAsync: vi.fn().mockResolvedValue({ projects: [] }),
  mergeProjects: vi.fn((server) => server),
  syncProjectsToBackup: vi.fn(),
  invalidateProjectsCache: vi.fn(),
  ensureProjectsFetched: vi.fn(),
}));
vi.mock('../../frontend/js/projectView.js', () => ({
  renderProjectView: vi.fn(),
  renderSidebarNav: vi.fn(),
  renderTab: vi.fn(),
  renderProcPartsGrid: vi.fn(),
  updateProcPartCard: vi.fn(),
  completeProcPartCard: vi.fn(),
  failProcPartCard,
  updateUsageUI: vi.fn(),
  showProcessingIndicator: vi.fn(),
  hideProcessingIndicator: vi.fn(),
  setProcPhase: vi.fn(),
  selectPart: vi.fn(),
  syncProcessingUIWithState: vi.fn(),
}));

/** Builds a fetch Response-like object streaming SSE frames as data: lines. */
function sseResponse(frames, { delayLast = 0 } = {}) {
  const body = new ReadableStream({
    start(controller) {
      frames.forEach((f, i) => {
        const last = i === frames.length - 1;
        if (last && delayLast > 0) {
          setTimeout(() => {
            controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(f)}\n\n`));
            controller.close();
          }, delayLast);
        } else {
          controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(f)}\n\n`));
        }
      });
      if (delayLast === 0) controller.close();
    },
  });
  return { ok: true, status: 200, body };
}

describe('startSSE (fetch + ReadableStream)', () => {
  let sse;
  let fetchMock;

  beforeEach(async () => {
    vi.resetModules();
    document.body.innerHTML = '<div id="toast-container"></div>';
    state.currentProjectId = 'p1';
    state.currentProject = { status: 'processing' };
    state.currentPartId = null;
    state.sseReconnectAttempts = 0;
    state.sseLastEventAt = Date.now();
    state.processingSSE = null;
    state.sseProjectId = null;
    state.session = { access_token: 'test-token' };
    toast.mockReset();
    failProcPartCard.mockReset();
    fetchMock = vi.fn();
    global.fetch = fetchMock;
    sse = await import('../../frontend/js/sse.js');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllTimers();
  });

  it('calls fetch with the Authorization Bearer header and parses SSE frames', async () => {
    fetchMock.mockResolvedValue(sseResponse([
      { type: 'ping' },
      { type: 'part_failed', part_id: 9, message: 'El modelo falló' },
      { type: 'stream_end' },
    ]));

    sse.startSSE('p1');

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.example.test/api/projects/p1/events',
        expect.objectContaining({
          headers: { Authorization: 'Bearer test-token' },
        })
      );
    });

    // ping is ignored, part_failed flows through the (identical) handler logic
    await vi.waitFor(() => {
      expect(failProcPartCard).toHaveBeenCalledWith(9, 'El modelo falló');
      expect(toast).toHaveBeenCalledWith('Sección 9: El modelo falló', 'error');
    });

    // stream_end closes and cleans up like before
    await vi.waitFor(() => {
      expect(state.processingSSE).toBeNull();
    });
  });

  it('connects without a token (no Authorization header) and 401s are handled as errors', async () => {
    state.session = null;
    fetchMock.mockRejectedValueOnce(new TypeError('Network error'));
    fetchMock.mockResolvedValue(sseResponse([{ type: 'stream_end' }]));

    sse.startSSE('p1');

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.example.test/api/projects/p1/events',
        expect.objectContaining({ headers: {} })
      );
    });
  });

  it('shows an error toast when completed arrives with failed parts', async () => {
    fetchMock.mockResolvedValue(sseResponse([
      { type: 'completed', has_failed_parts: true, failed_parts: [{ part_id: 2 }, { part_id: 3 }, { part_id: 4 }] },
    ]));
    const { api } = await import('../../frontend/js/api.js');
    api.mockResolvedValue({
      id: 'p1',
      status: 'completed',
      usage: {},
      partes_contenido: {},
      segmentation: { partes: [] },
    });

    sse.startSSE('p1');

    await vi.waitFor(() => {
      expect(toast).toHaveBeenCalledWith('3 secciones fallaron — revisa las tarjetas en rojo', 'error');
    });
    expect(toast).not.toHaveBeenCalledWith('¡Análisis completo! Ya puedes estudiar todo el contenido.', 'success');
  });

  it('still shows the success toast when completed has no failed parts', async () => {
    fetchMock.mockResolvedValue(sseResponse([{ type: 'completed' }]));
    const { api } = await import('../../frontend/js/api.js');
    api.mockResolvedValue({
      id: 'p1',
      status: 'completed',
      usage: {},
      partes_contenido: {},
      segmentation: { partes: [] },
    });

    sse.startSSE('p1');

    await vi.waitFor(() => {
      expect(toast).toHaveBeenCalledWith('¡Análisis completo! Ya puedes estudiar todo el contenido.', 'success');
    });
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining('fallaron'), 'error');
  });

  it('exposes EventSource-compatible readyState and close() aborts the fetch', async () => {
    let capturedSignal;
    fetchMock.mockImplementation((url, opts) => {
      capturedSignal = opts.signal;
      return Promise.resolve(sseResponse([
        { type: 'ping' },
        { type: 'stream_end' },
      ], { delayLast: 100 }));
    });

    sse.startSSE('p1');
    const wrapper = state.processingSSE;
    expect(wrapper).not.toBeNull();
    expect(wrapper.readyState).toBe(0); // EventSource.CONNECTING

    await vi.waitFor(() => {
      expect(wrapper.readyState).toBe(1); // EventSource.OPEN while streaming
    });

    await vi.waitFor(() => {
      expect(wrapper.readyState).toBe(2); // EventSource.CLOSED after stream_end
      expect(capturedSignal.aborted).toBe(true);
    });

    // close() is idempotent
    wrapper.close();
    expect(wrapper.readyState).toBe(2);
  });

  it('reconnects with backoff after a network error', async () => {
    vi.useFakeTimers();
    state.currentProject = { status: 'processing' };
    fetchMock.mockRejectedValueOnce(new TypeError('Network error'));
    fetchMock.mockResolvedValueOnce(sseResponse([{ type: 'stream_end' }]));

    const { SSE_RECONNECT_DELAY_MS } = await import('../../frontend/js/state.js');

    sse.startSSE('p1');
    expect(state.sseReconnectAttempts).toBe(0);

    await vi.advanceTimersByTimeAsync(SSE_RECONNECT_DELAY_MS + 100);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer test-token');
    expect(state.processingSSE).toBeNull();
  });
});
