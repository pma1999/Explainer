/**
 * Unit tests for renderGhostRail / updateGhostRailActive in projectView.js.
 *
 * renderGhostRail is module-private; we exercise it through renderTab which
 * calls it after injecting the explainer HTML for the 'explicacion' tab.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderTab, updateGhostRailActive } from '../../frontend/js/projectView.js';
import { state } from '../../frontend/js/state.js';

function setupExplicacionPanel() {
  // Clean any stale rail/markup from previous tests
  document.body.querySelectorAll('#panel-explicacion').forEach((n) => n.remove());
  document.body.querySelectorAll('#loading-explicacion').forEach((n) => n.remove());
  document.body.querySelectorAll('#content-explicacion').forEach((n) => n.remove());

  const panel = document.createElement('div');
  panel.id = 'panel-explicacion';

  const loading = document.createElement('div');
  loading.id = 'loading-explicacion';

  const content = document.createElement('div');
  content.id = 'content-explicacion';

  panel.appendChild(loading);
  panel.appendChild(content);
  document.body.appendChild(panel);

  return { panel, content };
}

const sampleData = {
  status: 'completed',
  explainer: {
    introduccion: 'intro',
    desarrollo: [
      {
        titulo_seccion: 'Sección uno',
        subsecciones: [
          { titulo_subseccion: 'Sub A', explicacion_detallada: 'a' },
          { titulo_subseccion: 'Sub B', explicacion_detallada: 'b' },
        ],
      },
      {
        titulo_seccion: 'Sección dos',
        subsecciones: [
          { titulo_subseccion: 'Sub C', explicacion_detallada: 'c' },
        ],
      },
    ],
    conexiones_contextuales: [
      { seccion_temario_relacionada: 'Conexión X', descripcion_conexion: 'x' },
    ],
  },
};

describe('renderGhostRail (via renderTab)', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    setupExplicacionPanel();
  });

  it('appends .ghost-rail to #panel-explicacion with one node per subsection', () => {
    renderTab('explicacion', sampleData);

    const panel = document.getElementById('panel-explicacion');
    const rail = panel.querySelector('.ghost-rail');
    expect(rail).not.toBeNull();
    expect(rail.getAttribute('aria-label')).toBe('Navegación de subsecciones');
    expect(rail.querySelector('.ghost-rail-line')).not.toBeNull();

    const nodes = rail.querySelectorAll('.ghost-rail-node');
    // 2 subs in section 0 + 1 sub in section 1 + 1 conexion = 4
    expect(nodes.length).toBe(4);
  });

  it('uses deterministic data-subsection-id format matching renderExplainer', () => {
    renderTab('explicacion', sampleData);
    const ids = Array.from(
      document.querySelectorAll('.ghost-rail-node')
    ).map((n) => n.dataset.subsectionId);

    expect(ids).toEqual([
      'subsec-1-0-0',
      'subsec-1-0-1',
      'subsec-1-1-0',
      'subsec-1-cx-0',
    ]);
  });

  it('sets staggered animation-delay and per-node aria-label', () => {
    renderTab('explicacion', sampleData);
    const nodes = document.querySelectorAll('.ghost-rail-node');
    expect(nodes[0].style.animationDelay).toBe('0ms');
    expect(nodes[1].style.animationDelay).toBe('40ms');
    expect(nodes[2].style.animationDelay).toBe('80ms');
    expect(nodes[3].style.animationDelay).toBe('120ms');

    expect(nodes[0].getAttribute('aria-label')).toBe('Subsección 1: Sub A');
    expect(nodes[3].getAttribute('aria-label')).toBe('Subsección 4: Conexión X');
  });

  it('returns early when explainer has no subsections and no conexiones', () => {
    const empty = {
      status: 'completed',
      explainer: { introduccion: 'only intro', desarrollo: [], conexiones_contextuales: [] },
    };
    renderTab('explicacion', empty);
    const panel = document.getElementById('panel-explicacion');
    expect(panel.querySelector('.ghost-rail')).toBeNull();
  });

  it('skips rail rendering when explainer is markdown fallback', () => {
    const md = {
      status: 'completed',
      explainer: { _format: 'markdown', content: '# only md' },
    };
    renderTab('explicacion', md);
    const panel = document.getElementById('panel-explicacion');
    expect(panel.querySelector('.ghost-rail')).toBeNull();
  });

  it('is idempotent — re-rendering replaces the existing rail', () => {
    renderTab('explicacion', sampleData);
    renderTab('explicacion', sampleData);
    const rails = document.querySelectorAll('.ghost-rail');
    expect(rails.length).toBe(1);
    expect(rails[0].querySelectorAll('.ghost-rail-node').length).toBe(4);
  });
});

describe('updateGhostRailActive', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    setupExplicacionPanel();
    renderTab('explicacion', sampleData);
  });

  it('toggles .active on the matching node and its label only', () => {
    updateGhostRailActive('subsec-1-1-0');

    const nodes = document.querySelectorAll('.ghost-rail-node');
    const active = Array.from(nodes).filter((n) => n.classList.contains('active'));
    expect(active.length).toBe(1);
    expect(active[0].dataset.subsectionId).toBe('subsec-1-1-0');
    expect(active[0].querySelector('.ghost-rail-label').classList.contains('active')).toBe(true);

    // others have no .active on label
    nodes.forEach((n) => {
      if (n.dataset.subsectionId !== 'subsec-1-1-0') {
        expect(n.classList.contains('active')).toBe(false);
        expect(n.querySelector('.ghost-rail-label').classList.contains('active')).toBe(false);
      }
    });
  });

  it('clears active when called with an unknown id', () => {
    updateGhostRailActive('subsec-1-0-0');
    updateGhostRailActive('does-not-exist');
    const active = document.querySelectorAll('.ghost-rail-node.active');
    expect(active.length).toBe(0);
  });

  it('is a no-op when no rail is mounted', () => {
    // Tear down rail
    document.querySelectorAll('.ghost-rail').forEach((n) => n.remove());
    expect(() => updateGhostRailActive('subsec-1-0-0')).not.toThrow();
  });
});
