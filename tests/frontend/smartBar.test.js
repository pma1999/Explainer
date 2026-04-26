/**
 * Unit tests for Smart Bar in projectView.js.
 *
 * renderSmartBar / navigateSubsection / openSubsectionSheet are module-private
 * and exercised indirectly through renderTab and DOM events. updateSmartBarText
 * is exported and tested directly.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderTab, updateSmartBarText } from '../../frontend/js/projectView.js';
import { state } from '../../frontend/js/state.js';

function setupExplicacionPanel() {
  // Tear down everything that smart-bar / ghost-rail tests touch
  document.body.querySelectorAll('#panel-explicacion').forEach((n) => n.remove());
  document.body.querySelectorAll('#loading-explicacion').forEach((n) => n.remove());
  document.body.querySelectorAll('#content-explicacion').forEach((n) => n.remove());
  document.body.querySelectorAll('#part-content').forEach((n) => n.remove());
  document.body.querySelectorAll('.subsection-sheet-overlay').forEach((n) => n.remove());

  // Outer #part-content where the smart bar lives
  const outer = document.createElement('div');
  outer.id = 'part-content';

  // Inner panels for renderTab
  const panel = document.createElement('div');
  panel.id = 'panel-explicacion';
  const loading = document.createElement('div');
  loading.id = 'loading-explicacion';
  const content = document.createElement('div');
  content.id = 'content-explicacion';

  panel.appendChild(loading);
  panel.appendChild(content);
  outer.appendChild(panel);
  document.body.appendChild(outer);

  return { outer, panel, content };
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

describe('renderSmartBar (via renderTab)', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    state.currentSubsectionId = null;
    setupExplicacionPanel();
  });

  it('appends .smart-bar to #part-content with prev/next/title/progress', () => {
    renderTab('explicacion', sampleData);

    const outer = document.getElementById('part-content');
    const bar = outer.querySelector('.smart-bar');
    expect(bar).not.toBeNull();
    expect(bar.getAttribute('role')).toBe('navigation');
    expect(bar.getAttribute('aria-label')).toBe('Navegación de subsección');
    expect(bar.dataset.count).toBe('4'); // 2 + 1 + 1
    expect(bar.querySelector('.smart-bar-progress')).not.toBeNull();
    expect(bar.querySelector('.smart-bar-peek-hitarea')).toBeNull();
    expect(bar.querySelector('.smart-bar-prev')).not.toBeNull();
    expect(bar.querySelector('.smart-bar-next')).not.toBeNull();
    expect(bar.querySelector('.smart-bar-title')).not.toBeNull();
    expect(bar.querySelector('.smart-bar-title-text')).not.toBeNull();
    expect(outer.classList.contains('has-mobile-subsection-nav')).toBe(true);
  });

  it('returns early when explainer has no subsections and no conexiones', () => {
    const empty = {
      status: 'completed',
      explainer: { introduccion: 'only intro', desarrollo: [], conexiones_contextuales: [] },
    };
    renderTab('explicacion', empty);
    expect(document.querySelector('.smart-bar')).toBeNull();
    expect(document.getElementById('part-content').classList.contains('has-mobile-subsection-nav')).toBe(false);
  });

  it('returns early when explainer is markdown fallback', () => {
    const md = {
      status: 'completed',
      explainer: { _format: 'markdown', content: '# only md' },
    };
    renderTab('explicacion', md);
    expect(document.querySelector('.smart-bar')).toBeNull();
  });

  it('is idempotent — re-rendering replaces the existing bar', () => {
    renderTab('explicacion', sampleData);
    renderTab('explicacion', sampleData);
    const bars = document.querySelectorAll('.smart-bar');
    expect(bars.length).toBe(1);
  });

  it('keeps the dock actionable when no current subsection is known yet', () => {
    renderTab('explicacion', sampleData);
    const bar = document.querySelector('.smart-bar');
    const prev = bar.querySelector('.smart-bar-prev');
    const next = bar.querySelector('.smart-bar-next');
    const text = bar.querySelector('.smart-bar-title-text');
    expect(prev.disabled).toBe(true);
    expect(next.disabled).toBe(false);
    expect(text.textContent).toBe('Índice de subsecciones');
  });
});

describe('updateSmartBarText', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    state.currentSubsectionId = null;
    setupExplicacionPanel();
    renderTab('explicacion', sampleData);
  });

  it('sets title to the matching subsection label', () => {
    updateSmartBarText('subsec-1-1-0');
    const text = document.querySelector('.smart-bar-title-text');
    expect(text.textContent).toBe('Sub C');
  });

  it('disables prev when at index 0', () => {
    updateSmartBarText('subsec-1-0-0');
    const bar = document.querySelector('.smart-bar');
    expect(bar.querySelector('.smart-bar-prev').disabled).toBe(true);
    expect(bar.querySelector('.smart-bar-next').disabled).toBe(false);
  });

  it('disables next when at last index', () => {
    updateSmartBarText('subsec-1-cx-0'); // last of 4
    const bar = document.querySelector('.smart-bar');
    expect(bar.querySelector('.smart-bar-prev').disabled).toBe(false);
    expect(bar.querySelector('.smart-bar-next').disabled).toBe(true);
  });

  it('sets progress width % to (idx+1)/total*100', () => {
    updateSmartBarText('subsec-1-0-1'); // index 1 of 4
    const progress = document.querySelector('.smart-bar-progress');
    expect(progress.style.width).toBe('50%'); // 2/4 = 50%
  });

  it('progress is 0% and title opens the index when subsection is unknown', () => {
    updateSmartBarText('not-found');
    const progress = document.querySelector('.smart-bar-progress');
    const text = document.querySelector('.smart-bar-title-text');
    expect(progress.style.width).toBe('0%');
    expect(text.textContent).toBe('Índice de subsecciones');
  });

  it('is a no-op when smart bar is not mounted', () => {
    document.querySelectorAll('.smart-bar').forEach((n) => n.remove());
    expect(() => updateSmartBarText('subsec-1-0-0')).not.toThrow();
  });
});

describe('navigateSubsection (via prev/next click)', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    state.currentSubsectionId = null;
    setupExplicacionPanel();
    renderTab('explicacion', sampleData);

    // jsdom doesn't implement scrollIntoView
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('clicking next from currentSubsectionId scrolls to the following subsection', () => {
    state.currentSubsectionId = 'subsec-1-0-0';
    updateSmartBarText('subsec-1-0-0');

    const target = document.getElementById('subsec-1-0-1');
    expect(target).not.toBeNull();
    const spy = vi.spyOn(target, 'scrollIntoView');

    document.querySelector('.smart-bar-next').click();
    expect(spy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
  });

  it('clicking prev from currentSubsectionId scrolls to the previous subsection', () => {
    state.currentSubsectionId = 'subsec-1-0-1';
    updateSmartBarText('subsec-1-0-1');

    const target = document.getElementById('subsec-1-0-0');
    expect(target).not.toBeNull();
    const spy = vi.spyOn(target, 'scrollIntoView');

    document.querySelector('.smart-bar-prev').click();
    expect(spy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
  });

  it('clicking next without a current subsection scrolls to the first subsection', () => {
    const target = document.getElementById('subsec-1-0-0');
    expect(target).not.toBeNull();
    const spy = vi.spyOn(target, 'scrollIntoView');

    document.querySelector('.smart-bar-next').click();
    expect(spy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
  });

  it('clicking next at last subsection does nothing', () => {
    state.currentSubsectionId = 'subsec-1-cx-0';
    updateSmartBarText('subsec-1-cx-0');

    // No element should be scrolled — last is end of list
    const all = ['subsec-1-0-0', 'subsec-1-0-1', 'subsec-1-1-0', 'subsec-1-cx-0']
      .map((id) => document.getElementById(id))
      .filter(Boolean);
    const spies = all.map((el) => vi.spyOn(el, 'scrollIntoView'));

    document.querySelector('.smart-bar-next').click();
    spies.forEach((s) => expect(s).not.toHaveBeenCalled());
  });
});

describe('openSubsectionSheet (via title click)', () => {
  beforeEach(() => {
    state.currentPartId = 1;
    state.currentSubsectionId = null;
    setupExplicacionPanel();
    renderTab('explicacion', sampleData);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('appends .subsection-sheet-overlay with one item per subsection', () => {
    document.querySelector('.smart-bar-title').click();

    const overlay = document.querySelector('.subsection-sheet-overlay');
    expect(overlay).not.toBeNull();
    const sheet = overlay.querySelector('.subsection-sheet');
    expect(sheet).not.toBeNull();
    expect(sheet.getAttribute('role')).toBe('dialog');
    expect(sheet.getAttribute('aria-modal')).toBe('true');
    expect(sheet.querySelector('.subsection-sheet-handle')).not.toBeNull();
    expect(sheet.querySelector('.subsection-sheet-title').textContent).toBe('Subsecciones');
    expect(sheet.querySelector('.subsection-sheet-close')).not.toBeNull();

    const items = overlay.querySelectorAll('.subsection-sheet-item');
    expect(items.length).toBe(4);

    // Numbered 1..4
    items.forEach((item, i) => {
      expect(item.querySelector('.subsection-sheet-num').textContent).toBe(String(i + 1));
    });
  });

  it('marks the active item matching state.currentSubsectionId', () => {
    state.currentSubsectionId = 'subsec-1-1-0';
    document.querySelector('.smart-bar-title').click();

    const items = document.querySelectorAll('.subsection-sheet-item');
    const active = Array.from(items).filter((it) => it.classList.contains('active'));
    expect(active.length).toBe(1);
    expect(active[0].querySelector('.subsection-sheet-label').textContent).toBe('Sub C');
  });

  it('clicking a sheet item scrolls to its target and closes the overlay', () => {
    document.querySelector('.smart-bar-title').click();
    const target = document.getElementById('subsec-1-0-1');
    const spy = vi.spyOn(target, 'scrollIntoView');

    const items = document.querySelectorAll('.subsection-sheet-item');
    items[1].click(); // second item -> subsec-1-0-1

    expect(spy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    expect(document.querySelector('.subsection-sheet-overlay')).toBeNull();
  });

  it('clicking the backdrop (overlay itself) closes the sheet', () => {
    document.querySelector('.smart-bar-title').click();
    const overlay = document.querySelector('.subsection-sheet-overlay');
    expect(overlay).not.toBeNull();

    // Simulate a click whose target IS the overlay (not a child)
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(document.querySelector('.subsection-sheet-overlay')).toBeNull();
  });

  it('clicking the close button closes the sheet', () => {
    document.querySelector('.smart-bar-title').click();
    document.querySelector('.subsection-sheet-close').click();

    expect(document.querySelector('.subsection-sheet-overlay')).toBeNull();
  });

  it('pressing Escape closes the sheet', () => {
    document.querySelector('.smart-bar-title').click();
    expect(document.querySelector('.subsection-sheet-overlay')).not.toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

    expect(document.querySelector('.subsection-sheet-overlay')).toBeNull();
  });

  it('clicking on the sheet (a non-overlay child) does NOT close', () => {
    document.querySelector('.smart-bar-title').click();
    const sheet = document.querySelector('.subsection-sheet');
    sheet.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    // Overlay should still be present (event target is sheet, not overlay)
    expect(document.querySelector('.subsection-sheet-overlay')).not.toBeNull();
  });

  it('escapes HTML in subsection titles to avoid XSS', () => {
    const malicious = {
      status: 'completed',
      explainer: {
        desarrollo: [
          {
            titulo_seccion: 'S',
            subsecciones: [
              { titulo_subseccion: '<img src=x onerror=alert(1)>', explicacion_detallada: 'x' },
            ],
          },
        ],
      },
    };
    renderTab('explicacion', malicious);
    document.querySelector('.smart-bar-title').click();

    const label = document.querySelector('.subsection-sheet-label');
    // After escHtml, no <img> child should exist; raw text remains
    expect(label.querySelector('img')).toBeNull();
    expect(label.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
