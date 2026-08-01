/**
 * Tests for the "Repaso Activo" tab (C2 — on-demand review).
 * Exercises renderTab('repaso'), generateReview and the delegated
 * click handling for reveal / generate / regenerate buttons.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = {
  user: { id: 'user-1' },
  currentProjectId: 'p1',
  currentPartId: 1,
  activeTab: 'repaso',
  currentProject: null,
  isSharedView: false,
  shareToken: null,
};

const api = vi.fn();
const toast = vi.fn();

vi.mock('../../frontend/js/state.js', () => ({ state }));
vi.mock('../../frontend/js/api.js', () => ({ api }));
vi.mock('../../frontend/js/landing.js', () => ({
  getTargetLanguage: vi.fn(() => 'es-ES'),
  getReviewProviderConfig: vi.fn(() => ({ explainer_provider: 'gemini' })),
}));
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

const SAMPLE_REVIEW = {
  preguntas: [
    { numero: 1, pregunta: '¿Cuál es la tesis central?', respuesta_razonada: 'La obra sostiene que…', referencia: 'págs. 12-14' },
    { numero: 2, pregunta: '¿Qué papel juega la autora?', respuesta_razonada: 'La autora contrasta…' },
    { numero: 3, pregunta: '¿Qué implica la noción de archivo?', respuesta_razonada: 'El archivo opera como…', referencia: 'Sección 2.3' },
    { numero: 4, pregunta: '¿Cómo cierra el argumento?', respuesta_razonada: 'El cierre retoma…' },
    { numero: 5, pregunta: '¿Qué preguntas quedan abiertas?', respuesta_razonada: 'Quedan abiertas…' },
  ],
  nota: 'Repasar el capítulo 2 antes de la siguiente sección.',
};

function resetDom() {
  document.body.innerHTML = `
    <div id="loading-repaso" class="hidden"></div>
    <div id="content-repaso"></div>
  `;
}

function resetState() {
  state.currentProjectId = 'p1';
  state.currentPartId = 1;
  state.activeTab = 'repaso';
  state.isSharedView = false;
  state.shareToken = null;
  state.currentProject = {
    id: 'p1',
    segmentation: { partes: [{ numero: 1, titulo: 'Parte 1' }] },
    partes_contenido: {
      1: { status: 'completed', review: null },
    },
  };
}

async function loadView() {
  return import('../../frontend/js/projectView.js');
}

describe('Repaso Activo tab (C2)', () => {
  let pv;

  // The delegated click listener is attached once; with vi.resetModules()
  // re-imports create fresh module instances, but all of them share the
  // same mocked api/state bindings, so a single listener is enough and
  // avoids duplicate handlers accumulating on document.
  beforeAll(async () => {
    pv = await loadView();
    pv.initReviewTabListeners();
  });

  beforeEach(async () => {
    vi.resetModules();
    resetDom();
    resetState();
    api.mockReset();
    toast.mockReset();
    api.mockResolvedValue({ ok: true, cached: false, review: SAMPLE_REVIEW });
  });

  it('shows the inviting empty state with a primary button when no review exists', () => {
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const content = document.getElementById('content-repaso');
    expect(content.querySelector('.review-empty')).toBeTruthy();
    expect(content.textContent).toContain('Repaso activo');
    expect(content.textContent).toContain('Pon a prueba tu comprensión de esta sección con 5 preguntas.');
    const btn = content.querySelector('.btn-generate-review');
    expect(btn).toBeTruthy();
    expect(btn.textContent).toContain('Repasar esta sección');
    expect(api).not.toHaveBeenCalled();
  });

  it('generates the review on click: POST with regenerate:false and renders questions', async () => {
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);
    document.querySelector('.btn-generate-review').click();

    // Button enters loading state while the request is in flight
    const btn = document.querySelector('.btn-generate-review');
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Generando…');

    await vi.waitFor(() => {
      expect(api).toHaveBeenCalledWith('/api/projects/p1/parts/1/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          regenerate: false,
          target_language: 'es-ES',
          explainer_provider: 'gemini',
        }),
      });
    });

    await vi.waitFor(() => {
      const content = document.getElementById('content-repaso');
      expect(content.querySelectorAll('.review-card')).toHaveLength(5);
      expect(content.textContent).toContain('Pregunta 1');
      expect(content.textContent).toContain('¿Cuál es la tesis central?');
      expect(content.textContent).toContain('págs. 12-14');
      expect(content.textContent).toContain('Nota de estudio');
    });

    // The generated review is cached in state for later visits
    expect(state.currentProject.partes_contenido[1].review).toEqual(SAMPLE_REVIEW);
  });

  it('renders existing review content directly without any API call', () => {
    state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;

    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const content = document.getElementById('content-repaso');
    expect(content.querySelectorAll('.review-card')).toHaveLength(5);
    expect(content.textContent).toContain('Pregunta 1');
    expect(content.textContent).toContain('Nota de estudio');
    expect(api).not.toHaveBeenCalled();
  });

  it('keeps answers hidden until the user asks for them', () => {
    state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const firstCard = document.querySelector('.review-card');
    const revealBtn = document.querySelector('.review-reveal');
    expect(firstCard.classList.contains('revealed')).toBe(false);
    expect(revealBtn.getAttribute('aria-expanded')).toBe('false');
    expect(revealBtn.textContent).toContain('Mostrar respuesta');
  });

  it('reveals the answer when "Mostrar respuesta" is clicked', () => {
    state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const revealBtn = document.querySelector('.review-reveal');
    revealBtn.click();

    const firstCard = document.querySelector('.review-card');
    expect(firstCard.classList.contains('revealed')).toBe(true);
    expect(revealBtn.getAttribute('aria-expanded')).toBe('true');
    expect(revealBtn.textContent).toContain('Ocultar respuesta');

    // Toggle back
    revealBtn.click();
    expect(firstCard.classList.contains('revealed')).toBe(false);
    expect(revealBtn.textContent).toContain('Mostrar respuesta');
  });

  it('regenerates only after confirmation, sending regenerate:true', async () => {
    state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    document.querySelector('.btn-regenerate-review').click();

    await vi.waitFor(() => {
      expect(api).toHaveBeenCalledWith('/api/projects/p1/parts/1/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          regenerate: true,
          target_language: 'es-ES',
          explainer_provider: 'gemini',
        }),
      });
    });
    expect(confirmSpy).toHaveBeenCalledWith('Regenerar consume crédito de tu API key. ¿Continuar?');

    await vi.waitFor(() => {
      const content = document.getElementById('content-repaso');
      expect(content.querySelectorAll('.review-card')).toHaveLength(5);
    });

    confirmSpy.mockRestore();
  });

  it('does not call the API when regeneration is cancelled', () => {
    state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;
    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    document.querySelector('.btn-regenerate-review').click();

    expect(api).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('shows the error message with a Reintentar button when generation fails', async () => {
    api.mockRejectedValueOnce(new Error('Saldo insuficiente en la API key'));

    pv.renderTab('repaso', state.currentProject.partes_contenido[1]);
    document.querySelector('.btn-generate-review').click();

    await vi.waitFor(() => {
      const content = document.getElementById('content-repaso');
      expect(content.textContent).toContain('Saldo insuficiente en la API key');
      const retry = content.querySelector('.btn-generate-review');
      expect(retry).toBeTruthy();
      expect(retry.textContent).toContain('Reintentar');
    });
    expect(toast).toHaveBeenCalledWith(
      'Error al generar el repaso: Saldo insuficiente en la API key',
      'error'
    );
  });

  it('shows the skeleton while the section pipeline is still starting', () => {
    const contenido = { status: 'processing', explainer: null, recorrido: null, resources: null };

    pv.renderTab('repaso', contenido);

    const loading = document.getElementById('loading-repaso');
    const content = document.getElementById('content-repaso');
    expect(loading.classList.contains('hidden')).toBe(false);
    expect(content.innerHTML).toBe('');
    expect(api).not.toHaveBeenCalled();
  });

  it('shows the standard error-state when the part pipeline failed', () => {
    const contenido = {
      status: 'failed',
      explainer: { error: 'El modelo se quedó sin contexto' },
      recorrido: null,
      resources: null,
      review: null,
    };

    pv.renderTab('repaso', contenido);

    const content = document.getElementById('content-repaso');
    expect(content.querySelector('.error-state')).toBeTruthy();
    expect(content.textContent).toContain('El modelo se quedó sin contexto');
    expect(content.querySelector('.btn-generate-review')).toBeFalsy();
  });

  describe('shared view', () => {
    beforeEach(() => {
      state.isSharedView = true;
    });

    it('shows review content without action buttons', () => {
      state.currentProject.partes_contenido[1].review = SAMPLE_REVIEW;
      pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

      const content = document.getElementById('content-repaso');
      expect(content.querySelectorAll('.review-card')).toHaveLength(5);
      expect(content.querySelector('.btn-regenerate-review')).toBeFalsy();
    });

    it('shows a neutral message without a generate button when no review exists', () => {
      pv.renderTab('repaso', state.currentProject.partes_contenido[1]);

      const content = document.getElementById('content-repaso');
      expect(content.querySelector('.review-shared-empty')).toBeTruthy();
      expect(content.querySelector('.btn-generate-review')).toBeFalsy();
    });
  });
});
