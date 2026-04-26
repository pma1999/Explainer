/* ============================================================
   EXPLAINER — Project Detail View, Sidebar, Proc-Stage, Renderers
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, formatDate, statusLabel, formatIconForResource, escHtml, nl2p, toast } from './dom.js';
import { api } from './api.js';
import { loadBackupAsync, syncProjectsToBackup } from './storage.js';
import { isOffline } from './pwa.js';

/**
 * Renders markdown text to HTML using marked.js.
 * Falls back to nl2p() if marked is not yet loaded (e.g. CDN failure).
 * Fully backward-compatible: plain text without markdown syntax renders
 * correctly via marked.parse just as it did through nl2p.
 */
function renderMd(text) {
  if (!text) return '';
  if (typeof window.marked !== 'undefined') {
    return window.marked.parse(String(text));
  }
  return nl2p(String(text));
}

let _saveViewState = null;
export function setSaveViewStateCallback(fn) {
  _saveViewState = fn;
}

// Tracks the partId actually rendered into panel-explicacion. Decoupled
// from state.currentPartId because most callers pre-assign state.currentPartId
// BEFORE calling selectPart — using state would make the idempotency guard
// see a "match" when the panel still shows the previous part.
let _renderedPartId = null;

const SHARED_CTA_FLOATING_DISMISSED_KEY = 'explainer.sharedCtaFloatingDismissed';

function isSidebarVisible() {
  const layout = document.querySelector('.project-layout');
  const sidebar = $('project-sidebar');
  if (!layout || !sidebar) return true;
  const isMobile = window.innerWidth <= 768;
  if (isMobile) {
    return sidebar.classList.contains('open');
  }
  return !layout.classList.contains('sidebar-hidden');
}

export function updateSharedCtaFloatingVisibility() {
  const floating = $('shared-cta-floating');
  if (!floating) return;
  if (!state.isSharedView) {
    floating.classList.remove('visible');
    floating.classList.add('hidden');
    return;
  }
  if (sessionStorage.getItem(SHARED_CTA_FLOATING_DISMISSED_KEY)) {
    floating.classList.remove('visible');
    floating.classList.add('hidden');
    return;
  }
  const sidebarVisible = isSidebarVisible();
  if (sidebarVisible) {
    floating.classList.remove('visible');
    floating.classList.add('hidden');
  } else {
    floating.classList.remove('hidden');
    floating.classList.add('visible');
  }
}

export function initSharedCtaListeners() {
  const sidebarClose = $('shared-cta-close');
  const floatingClose = $('shared-cta-floating-close');
  const sidebarCta = $('shared-cta-register');

  sidebarClose?.addEventListener('click', () => {
    if (sidebarCta) sidebarCta.classList.add('hidden');
  });

  floatingClose?.addEventListener('click', () => {
    sessionStorage.setItem(SHARED_CTA_FLOATING_DISMISSED_KEY, '1');
    const floating = $('shared-cta-floating');
    if (floating) {
      floating.classList.remove('visible');
      floating.classList.add('hidden');
    }
  });
}

function applySharedViewVisibility() {
  const layout = document.querySelector('.project-layout');
  const sidebar = $('project-sidebar');
  if (!layout && !sidebar) return;

  if (state.isSharedView) {
    layout?.classList.add('shared-mode');
    sidebar?.classList.add('shared-mode');
    document.querySelectorAll('[data-shared-hide]').forEach((el) => { el.style.display = 'none'; });
    const cta = $('shared-cta-register');
    if (cta) cta.classList.remove('hidden');
    updateSharedCtaFloatingVisibility();
    const backBtn = $('btn-back-to-projects');
    if (backBtn) {
      backBtn.textContent = 'Iniciar sesión';
      backBtn.dataset.sharedBack = 'true';
    }
  } else {
    layout?.classList.remove('shared-mode');
    sidebar?.classList.remove('shared-mode');
    document.querySelectorAll('[data-shared-hide]').forEach((el) => { el.style.display = ''; });
    const cta = $('shared-cta-register');
    if (cta) cta.classList.add('hidden');
    const floating = $('shared-cta-floating');
    if (floating) {
      floating.classList.remove('visible');
      floating.classList.add('hidden');
    }
    sessionStorage.removeItem(SHARED_CTA_FLOATING_DISMISSED_KEY);
    const backBtn = $('btn-back-to-projects');
    if (backBtn?.dataset.sharedBack === 'true') {
      backBtn.textContent = 'Proyectos';
      delete backBtn.dataset.sharedBack;
    }
  }
}

function saveViewState() {
  if (_saveViewState) _saveViewState();
}

/** Mark a section as read. Fire-and-forget. */
export async function markSectionComplete(partId) {
  if (!state.currentProjectId || !state.currentProject || !state.user?.id) return;
  const project = state.currentProject;
  const contenido = project.partes_contenido?.[String(partId)];
  if (!contenido || contenido.status !== 'completed') return;
  const completed = new Set(project?.reading_progress?.completed_parts || []);
  if (completed.has(partId)) return;

  try {
    const updated = await api(`/api/projects/${state.currentProjectId}/progress`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_id: partId }),
    });
    if (updated?.reading_progress) {
      state.currentProject.reading_progress = updated.reading_progress;
      renderSidebarNav(state.currentProject);
    }
  } catch (_) {}
}

const _toggleInProgress = new Set();

/** Toggle section read status manually. Optimistic UI: updates immediately, syncs in background. */
export async function toggleSectionComplete(partId, completed) {
  if (!state.currentProjectId || !state.currentProject || !state.user?.id) return;
  const project = state.currentProject;
  const contenido = project.partes_contenido?.[String(partId)];
  if (!contenido || contenido.status !== 'completed') return;
  const completedSet = new Set(project?.reading_progress?.completed_parts || []);
  if (completed && completedSet.has(partId)) return;
  if (!completed && !completedSet.has(partId)) return;
  if (_toggleInProgress.has(partId)) return;

  const prevCompleted = [...(project?.reading_progress?.completed_parts || [])];

  // Optimistic update: apply immediately for instant feedback
  if (completed) {
    const next = new Set(prevCompleted);
    next.add(partId);
    state.currentProject.reading_progress = {
      ...state.currentProject.reading_progress,
      completed_parts: [...next].sort((a, b) => a - b),
    };
  } else {
    state.currentProject.reading_progress = {
      ...state.currentProject.reading_progress,
      completed_parts: prevCompleted.filter((p) => p !== partId),
    };
  }
  renderSidebarNav(state.currentProject);
  updateToggleCompleteButton();
  setToggleDisabledForPart(partId, true);
  _toggleInProgress.add(partId);

  try {
    const updated = await api(`/api/projects/${state.currentProjectId}/progress`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ part_id: partId, completed }),
    });
    if (updated?.reading_progress) {
      state.currentProject.reading_progress = updated.reading_progress;
      renderSidebarNav(state.currentProject);
      updateToggleCompleteButton();
    }
  } catch (_) {
    state.currentProject.reading_progress = {
      ...state.currentProject.reading_progress,
      completed_parts: prevCompleted,
    };
    renderSidebarNav(state.currentProject);
    updateToggleCompleteButton();
    toast('Error al actualizar el progreso', 'error');
  } finally {
    _toggleInProgress.delete(partId);
    setToggleDisabledForPart(partId, false);
  }
}

function setToggleDisabledForPart(partId, disabled) {
  const btn = $('btn-toggle-complete');
  if (btn && state.currentPartId === partId) btn.disabled = disabled;
  document.querySelectorAll(`.part-read-toggle[data-part-id="${partId}"]`).forEach((el) => {
    el.disabled = disabled;
  });
}

export function showProcessingIndicator(status) {
  const stage = $('proc-stage');
  if (!stage) return;
  stage.classList.remove('hidden');
  setProcPhase(status);
}

export function hideProcessingIndicator() {
  const stage = $('proc-stage');
  if (stage) stage.classList.add('hidden');
}

function setBootShellKicker(text) {
  const kicker = $('project-boot-kicker');
  if (kicker) kicker.textContent = text;
}

function primeProjectChrome(projectName = 'Cargando proyecto...') {
  const sidebarName = $('sidebar-project-name');
  const sidebarStatus = $('sidebar-status');
  const sidebarNav = $('sidebar-nav');
  const mobileProjectName = $('mobile-project-name');

  if (sidebarName) sidebarName.textContent = projectName;
  if (sidebarStatus) sidebarStatus.textContent = '';
  if (sidebarNav) sidebarNav.innerHTML = '';
  if (mobileProjectName) mobileProjectName.textContent = projectName;
}

function hideProjectBootShell() {
  hide($('project-boot-shell'));
}

function resetProjectSurface() {
  hide($('part-content'));
  hide($('main-welcome'));
  hide($('proc-stage'));
  hideProjectBootShell();
}

export function showProjectLoadingState() {
  resetProjectSurface();
  setBootShellKicker('Cargando proyecto');
  primeProjectChrome();
  show($('project-boot-shell'));
}

/**
 * Show loading state when restoring a specific section from URL and project is not yet loaded.
 * Avoids showing "Selecciona una sección" when the user intent is to load a concrete section.
 */
export function showSectionLoadingState(partId) {
  resetProjectSurface();
  setBootShellKicker(partId ? `Cargando sección ${partId}` : 'Cargando sección');
  primeProjectChrome();
  show($('project-boot-shell'));
}

export function showProjectIdleState(hasPartes) {
  resetProjectSurface();
  const titleEl = $('welcome-title');
  const subEl = $('welcome-sub');

  if (titleEl) titleEl.textContent = hasPartes ? 'Selecciona una sección' : 'Sin contenido';
  if (subEl) {
    subEl.textContent = hasPartes
      ? 'Haz clic en cualquier sección para ver su contenido.'
      : 'No hay secciones disponibles.';
  }
  show($('main-welcome'));
}

export function setProcPhase(status) {
  const labelMap = {
    pending: 'Iniciando',
    uploading: 'Subiendo archivo',
    segmenting: 'Segmentando',
    processing: 'Generando contenido',
  };
  const subMap = {
    pending: 'Preparando el análisis...',
    uploading: 'Enviando el documento a la IA',
    segmenting: 'El Segmentador está dividiendo el texto en secciones',
    processing: 'Los agentes están trabajando en paralelo',
  };
  const orbMap = {
    pending: '',
    uploading: 'orb-upload',
    segmenting: 'orb-segment',
    processing: 'orb-generate',
  };

  const label = $('proc-phase-label');
  const sub = $('proc-phase-sub');
  const orb = $('proc-phase-orb');
  const hint = $('forge-hint');

  if (label) label.textContent = labelMap[status] || 'Procesando';
  if (sub) sub.textContent = subMap[status] || '';
  if (orb) orb.className = 'proc-phase-orb ' + (orbMap[status] || '');
  if (hint) hint.textContent = subMap[status] || 'Procesando...';

  const steps = ['pstep-upload', 'pstep-segment', 'pstep-generate'];
  const lines = document.querySelectorAll('.proc-step-line');
  const phaseIndex = { pending: -1, uploading: 0, segmenting: 1, processing: 2 }[status] ?? -1;

  steps.forEach((id, i) => {
    const el = $(id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (i < phaseIndex) el.classList.add('done');
    else if (i === phaseIndex) el.classList.add('active');
  });

  lines.forEach((line, i) => {
    line.classList.remove('active', 'done');
    if (i < phaseIndex - 1) line.classList.add('done');
    else if (i === phaseIndex - 1) line.classList.add('active');
  });
}

export function renderProcPartsGrid(project) {
  const grid = $('proc-parts-grid');
  const forge = $('proc-forge');
  if (!grid) return;

  const partes = project.segmentation?.partes || [];
  const contenido = project.partes_contenido || {};

  grid.innerHTML = `<div class="proc-grid-header">${partes.length} sección${partes.length !== 1 ? 'es' : ''} · En progreso</div>`;

  partes.forEach((parte, idx) => {
    const partId = parte.numero;
    const c = contenido[String(partId)];
    const status = c ? c.status : 'pending';

    const doneAgents = {
      explainer: c && c.explainer && !c.explainer.error,
      recorrido: c && c.recorrido && !c.recorrido.error,
      resources: c && c.resources && !c.resources.error,
    };

    const card = document.createElement('div');
    card.className = `proc-part-card ${status}`;
    card.dataset.partId = partId;
    card.style.animationDelay = `${idx * 60}ms`;

    card.innerHTML = `
      <div class="proc-card-num">
        <span>Sección ${partId}</span>
        <span class="proc-card-status-dot"></span>
      </div>
      <div class="proc-card-title">${escHtml(parte.titulo)}</div>
      <div class="proc-agent-row">
        <span class="proc-agent-badge${doneAgents.explainer ? ' done' : (status === 'processing' ? ' active' : '')}" data-agent="explainer">
          <span class="badge-icon">📖</span> Explicación
        </span>
        <span class="proc-agent-badge${doneAgents.recorrido ? ' done' : (status === 'processing' ? ' active' : '')}" data-agent="recorrido">
          <span class="badge-icon">✍</span> Recorrido
        </span>
        <span class="proc-agent-badge${doneAgents.resources ? ' done' : (status === 'processing' ? ' active' : '')}" data-agent="resources">
          <span class="badge-icon">🗺️</span> Recursos
        </span>
      </div>
      <div class="proc-card-cta">Abrir →</div>
    `;

    if (status === 'completed') {
      card.addEventListener('click', () => {
        if (window.pushRoute) {
          window.pushRoute({
            view: 'project',
            projectId: state.currentProjectId,
            partId,
            tab: 'explicacion',
          });
        }
      });
    }

    grid.appendChild(card);
  });

  grid.classList.remove('hidden');
  if (forge) forge.classList.add('hidden');
}

export function updateProcPartCard(partId, agentName) {
  const card = document.querySelector(`#proc-parts-grid .proc-part-card[data-part-id="${partId}"]`);
  if (!card) return;

  card.classList.remove('pending');
  card.classList.add('processing');

  const badge = card.querySelector(`.proc-agent-badge[data-agent="${agentName}"]`);
  if (badge) {
    badge.classList.remove('active');
    badge.classList.add('done');
  }
}

export function completeProcPartCard(partId) {
  const card = document.querySelector(`#proc-parts-grid .proc-part-card[data-part-id="${partId}"]`);
  if (!card) return;

  card.classList.remove('pending', 'processing');
  card.classList.add('completed');

  card.querySelectorAll('.proc-agent-badge').forEach(b => {
    b.classList.remove('active');
    b.classList.add('done');
  });

  card.style.cursor = 'pointer';
  card.addEventListener('click', () => {
    if (window.pushRoute) {
      window.pushRoute({
        view: 'project',
        projectId: state.currentProjectId,
        partId,
        tab: 'explicacion',
      });
    }
  });
}

export function updateUsageUI(usage) {
  if (!usage) return;

  const cost = usage.total_cost || 0;
  const prompt = usage.prompt_tokens || 0;
  const candidates = usage.candidates_tokens || 0;
  const thoughts = usage.thoughts_tokens || 0;
  const total = usage.total_tokens || 0;

  if ($('mini-total-cost')) $('mini-total-cost').textContent = `$${cost.toFixed(2)}`;
  if ($('usage-total-cost')) $('usage-total-cost').textContent = `$${cost.toFixed(2)}`;
  if ($('usage-prompt-tokens')) $('usage-prompt-tokens').textContent = prompt.toLocaleString();
  if ($('usage-output-tokens')) $('usage-output-tokens').textContent = candidates.toLocaleString();
  if ($('usage-thought-tokens')) $('usage-thought-tokens').textContent = thoughts.toLocaleString();
  if ($('usage-total-tokens')) $('usage-total-tokens').textContent = total.toLocaleString();

  if ($('proc-cost-badge')) $('proc-cost-badge').textContent = `$${cost.toFixed(4)}`;

  // Formatter cost row (only visible when formatter has been applied)
  const fmtCost = usage.formatter_cost || 0;
  if ($('usage-formatter-cost')) {
    $('usage-formatter-cost').textContent = `$${fmtCost.toFixed(4)}`;
  }
  const fmtRow = $('usage-formatter-row');
  if (fmtRow) fmtRow.style.display = fmtCost > 0 ? '' : 'none';

  const card = $('project-usage-card');
  if (card) {
    card.classList.remove('pulse-highlight');
    void card.offsetWidth;
    card.classList.add('pulse-highlight');
  }
}

export function renderSidebarNav(project) {
  const nav = $('sidebar-nav');
  nav.innerHTML = '';

  if (!project.segmentation || !project.segmentation.partes) return;

  const projectId = state.currentProjectId;
  const isShared = state.isSharedView && state.shareToken;
  const completedParts = new Set(project?.reading_progress?.completed_parts || []);
  const contenidoRaw = project.partes_contenido || {};

  project.segmentation.partes.forEach(parte => {
    const partId = parte.numero;
    const contenido = contenidoRaw[String(partId)];
    const status = contenido ? (contenido.status || (contenido.explainer || contenido.recorrido || contenido.resources ? 'completed' : 'pending')) : 'pending';
    const isRead = completedParts.has(partId);
    const canToggle = !isShared && status === 'completed';

    const dotClass = {
      pending: 'dot-pending',
      processing: 'dot-processing',
      completed: 'dot-completed',
      error: 'dot-error',
    }[status] || 'dot-pending';

    let href = '#';
    if (typeof window.buildHash === 'function') {
      if (isShared) {
        href = window.buildHash({ view: 'shared', shareToken: state.shareToken, partId, tab: state.activeTab });
      } else if (projectId) {
        href = window.buildHash({ view: 'project', projectId, partId, tab: state.activeTab });
      }
    }

    const toggleBtnHtml = canToggle
      ? `<button type="button" class="part-read-toggle${isRead ? ' is-read' : ''}" data-part-id="${partId}" aria-label="${isRead ? 'Marcar como no leída' : 'Marcar como leída'}" title="${isRead ? 'Marcar como no leída' : 'Marcar como leída'}">${isRead ? '✓' : '○'}</button>`
      : '';

    const el = document.createElement('a');
    el.className = `sidebar-part${state.currentPartId === partId ? ' active' : ''}${isRead ? ' part-read' : ''}`;
    el.dataset.partId = partId;
    el.href = href;
    el.innerHTML = `
      <span class="part-num">P${partId}</span>
      <span class="part-label">${escHtml(parte.titulo)}</span>
      <span class="part-status-dot ${dotClass}"></span>
      ${toggleBtnHtml}
    `;
    nav.appendChild(el);

    if (canToggle) {
      const toggleBtn = el.querySelector('.part-read-toggle');
      if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          toggleSectionComplete(partId, !isRead);
        });
      }
    }
  });
}

function renderExplainer(data, partId) {
  if (data._format === 'markdown') {
    return `<div class="explainer-content">${renderMd(data.content || '')}</div>`;
  }
  let html = '';
  if (data.introduccion) {
    html += `<div class="explainer-intro">${renderMd(data.introduccion)}</div>`;
  }
  if (data.desarrollo && data.desarrollo.length > 0) {
    data.desarrollo.forEach((section, sectionIndex) => {
      html += `<div class="explainer-section">`;
      html += `<h3 class="explainer-section-title">${escHtml(section.titulo_seccion)}</h3>`;
      if (section.explicacion_introductoria) {
        html += `<div class="explainer-section-intro">${renderMd(section.explicacion_introductoria)}</div>`;
      }
      if (section.subsecciones && section.subsecciones.length > 0) {
        section.subsecciones.forEach((sub, subIndex) => {
          const subsectionId = `subsec-${partId}-${sectionIndex}-${subIndex}`;
          html += `<div class="explainer-subsection">`;
          html += `<h4 class="explainer-subsection-title" id="${subsectionId}">${escHtml(sub.titulo_subseccion)}</h4>`;
          html += `<div class="explainer-text">${renderMd(sub.explicacion_detallada)}</div>`;
          html += `</div>`;
        });
      }
      html += `</div>`;
    });
  }
  if (data.conclusion) {
    html += `
      <div class="explainer-conclusion">
        <div class="explainer-conclusion-label">Conclusión</div>
        ${renderMd(data.conclusion)}
      </div>`;
  }
  if (data.conexiones_contextuales && data.conexiones_contextuales.length > 0) {
    html += `<div class="explainer-section"><h3 class="explainer-section-title">Conexiones contextuales</h3>`;
    data.conexiones_contextuales.forEach((cx, cxIndex) => {
      // Use a distinct section index for conexiones to avoid collisions
      const subsectionId = `subsec-${partId}-cx-${cxIndex}`;
      html += `<div class="explainer-subsection">
        <h4 class="explainer-subsection-title" id="${subsectionId}">${escHtml(cx.seccion_temario_relacionada)}</h4>
        <div class="explainer-text">${renderMd(cx.descripcion_conexion)}</div>
      </div>`;
    });
    html += `</div>`;
  }
  return html;
}

function renderGhostRail(partId, explainerData) {
  const panel = document.getElementById('panel-explicacion');
  if (!panel) return;

  // Remove existing rail (idempotent re-render)
  const existing = panel.querySelector('.ghost-rail');
  if (existing) existing.remove();

  if (!explainerData || explainerData._format === 'markdown') return;

  // Build flat list of subsections in DOM order
  const subsections = [];
  if (Array.isArray(explainerData.desarrollo)) {
    explainerData.desarrollo.forEach((section, sIdx) => {
      if (Array.isArray(section.subsecciones)) {
        section.subsecciones.forEach((sub, subIdx) => {
          subsections.push({
            id: `subsec-${partId}-${sIdx}-${subIdx}`,
            title: sub.titulo_subseccion || '',
          });
        });
      }
    });
  }
  if (Array.isArray(explainerData.conexiones_contextuales)) {
    explainerData.conexiones_contextuales.forEach((cx, cxIdx) => {
      subsections.push({
        id: `subsec-${partId}-cx-${cxIdx}`,
        title: cx.seccion_temario_relacionada || '',
      });
    });
  }
  if (subsections.length === 0) return;

  const rail = document.createElement('div');
  rail.className = 'ghost-rail';
  rail.setAttribute('aria-label', 'Navegación de subsecciones');

  const line = document.createElement('div');
  line.className = 'ghost-rail-line';
  rail.appendChild(line);

  const completed = new Set(state.currentProject?.reading_progress?.completed_subsections || []);

  subsections.forEach((sub, i) => {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = 'ghost-rail-node';
    if (completed.has(sub.id)) {
      node.classList.add('is-read');
    }
    node.dataset.subsectionId = sub.id;
    node.setAttribute('aria-label', `Subsección ${i + 1}: ${sub.title}`);
    node.style.animationDelay = `${i * 40}ms`;

    const label = document.createElement('span');
    label.className = 'ghost-rail-label';
    label.textContent = sub.title;
    node.appendChild(label);

    node.addEventListener('click', () => {
      const target = document.getElementById(sub.id);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });

    rail.appendChild(node);
  });

  // Insert rail at the end of panel so it overlays content (CSS in Task 8)
  panel.appendChild(rail);
}

export function positionGhostRailNodes() {
  const rail = document.querySelector('.ghost-rail');
  const panel = document.getElementById('panel-explicacion');
  if (!rail || !panel) return;

  const panelRect = panel.getBoundingClientRect();
  rail.querySelectorAll('.ghost-rail-node').forEach(node => {
    const target = document.getElementById(node.dataset.subsectionId);
    if (!target) return;
    const targetRect = target.getBoundingClientRect();
    const top = targetRect.top - panelRect.top + panel.scrollTop;
    node.style.top = top + 'px';
  });
}

export function updateGhostRailActive(subsectionId) {
  const rail = document.querySelector('.ghost-rail');
  if (!rail) return;
  rail.querySelectorAll('.ghost-rail-node').forEach((node) => {
    const isActive = node.dataset.subsectionId === subsectionId;
    node.classList.toggle('active', isActive);
    const label = node.querySelector('.ghost-rail-label');
    if (label) label.classList.toggle('active', isActive);
  });
}

/**
 * Refreshes only the .is-read class on existing rail nodes from the current
 * reading_progress.completed_subsections. Does NOT rebuild the rail and does
 * NOT touch any other DOM — safe to call from a background server refetch
 * without disturbing scroll position or active subsection.
 */
export function refreshGhostRailReadState() {
  const rail = document.querySelector('.ghost-rail');
  if (!rail) return;
  const completed = new Set(
    state.currentProject?.reading_progress?.completed_subsections || [],
  );
  rail.querySelectorAll('.ghost-rail-node').forEach((node) => {
    const id = node.dataset.subsectionId;
    if (!id) return;
    node.classList.toggle('is-read', completed.has(id));
  });
}

function renderSmartBar(partId, explainerData) {
  const content = document.getElementById('part-content');
  if (!content) return;

  // Remove existing
  const existing = content.querySelector('.smart-bar');
  if (existing) existing.remove();

  if (!explainerData || explainerData._format === 'markdown') return;

  // Build flat list (same logic as rail)
  const subsections = [];
  if (Array.isArray(explainerData.desarrollo)) {
    explainerData.desarrollo.forEach((section, sIdx) => {
      if (Array.isArray(section.subsecciones)) {
        section.subsecciones.forEach((sub, subIdx) => {
          subsections.push({
            id: `subsec-${partId}-${sIdx}-${subIdx}`,
            title: sub.titulo_subseccion || '',
          });
        });
      }
    });
  }
  if (Array.isArray(explainerData.conexiones_contextuales)) {
    explainerData.conexiones_contextuales.forEach((cx, cxIdx) => {
      subsections.push({
        id: `subsec-${partId}-cx-${cxIdx}`,
        title: cx.seccion_temario_relacionada || '',
      });
    });
  }
  if (subsections.length === 0) return;

  const bar = document.createElement('div');
  bar.className = 'smart-bar';
  bar.setAttribute('role', 'navigation');
  bar.setAttribute('aria-label', 'Navegación de subsección');
  bar.dataset.count = String(subsections.length);
  bar.innerHTML = `
    <div class="smart-bar-progress"></div>
    <button type="button" class="smart-bar-peek-hitarea" aria-label="Mostrar navegación de subsecciones"></button>
    <button type="button" class="smart-bar-prev" aria-label="Subsección anterior">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    </button>
    <button type="button" class="smart-bar-title" aria-label="Abrir índice de subsecciones">
      <span class="smart-bar-title-text">—</span>
    </button>
    <button type="button" class="smart-bar-next" aria-label="Subsección siguiente">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M6 3L11 8L6 13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    </button>
  `;

  const prevBtn = bar.querySelector('.smart-bar-prev');
  const nextBtn = bar.querySelector('.smart-bar-next');
  const titleBtn = bar.querySelector('.smart-bar-title');
  const peekBtn = bar.querySelector('.smart-bar-peek-hitarea');

  prevBtn.addEventListener('click', () => navigateSubsection(-1));
  nextBtn.addEventListener('click', () => navigateSubsection(1));
  titleBtn.addEventListener('click', () => openSubsectionSheet(subsections));
  peekBtn.addEventListener('click', () => {
    bar.classList.remove('retracted');
    bar.dataset.manualExpandedUntil = String(Date.now() + 1200);
  });

  content.appendChild(bar);
  updateSmartBarText(state.currentSubsectionId);
}

export function updateSmartBarText(subsectionId) {
  const bar = document.querySelector('.smart-bar');
  if (!bar) return;
  const titleText = bar.querySelector('.smart-bar-title-text');
  const prevBtn = bar.querySelector('.smart-bar-prev');
  const nextBtn = bar.querySelector('.smart-bar-next');

  const subsections = [];
  const rail = document.querySelector('.ghost-rail');
  if (rail) {
    rail.querySelectorAll('.ghost-rail-node').forEach((n) => {
      subsections.push({
        id: n.dataset.subsectionId,
        title: n.querySelector('.ghost-rail-label')?.textContent || '',
      });
    });
  }

  const idx = subsections.findIndex((s) => s.id === subsectionId);
  if (titleText) {
    titleText.textContent = idx !== -1 ? subsections[idx].title : '—';
  }
  if (prevBtn) prevBtn.disabled = idx <= 0;
  if (nextBtn) nextBtn.disabled = idx === -1 || idx >= subsections.length - 1;

  // Update progress hairline
  const progress = bar.querySelector('.smart-bar-progress');
  if (progress && subsections.length > 0) {
    const pct = idx >= 0 ? ((idx + 1) / subsections.length) * 100 : 0;
    progress.style.width = pct + '%';
  }
}

function navigateSubsection(delta) {
  const subsections = [];
  document.querySelectorAll('.ghost-rail-node').forEach((n) => {
    subsections.push(n.dataset.subsectionId);
  });
  const idx = subsections.findIndex((id) => id === state.currentSubsectionId);
  const next = subsections[idx + delta];
  if (next) {
    const target = document.getElementById(next);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function openSubsectionSheet(subsections) {
  // Simple sheet using existing modal/overlay patterns in the app
  const overlay = document.createElement('div');
  overlay.className = 'subsection-sheet-overlay';
  const sheet = document.createElement('div');
  sheet.className = 'subsection-sheet';
  sheet.innerHTML = `<div class="subsection-sheet-handle"></div><div class="subsection-sheet-list"></div>`;
  const list = sheet.querySelector('.subsection-sheet-list');

  subsections.forEach((sub, i) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'subsection-sheet-item';
    if (sub.id === state.currentSubsectionId) item.classList.add('active');
    item.innerHTML = `<span class="subsection-sheet-num">${i + 1}</span><span class="subsection-sheet-label">${escHtml(sub.title)}</span>`;
    item.addEventListener('click', () => {
      const target = document.getElementById(sub.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      overlay.remove();
    });
    list.appendChild(item);
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });

  overlay.appendChild(sheet);
  document.body.appendChild(overlay);
}

function renderRecorrido(data) {
  let html = '';
  if (data.recorrido_anotado && data.recorrido_anotado.length > 0) {
    data.recorrido_anotado.forEach((entry, i) => {
      const delay = Math.min(i * 30, 300);
      html += `<div class="recorrido-entry" style="animation-delay:${delay}ms">`;
      html += `<div class="recorrido-header">
        <span class="recorrido-ubicacion">${escHtml(entry.ubicacion)}</span>
        <span class="recorrido-tipo">${entry.tipo_entrada === 'cita_anotada' ? 'Cita anotada' : 'Contenido'}</span>
      </div>`;
      html += `<div class="recorrido-body">`;
      if (entry.cita_textual) {
        html += `<blockquote class="recorrido-cita">${escHtml(entry.cita_textual)}</blockquote>`;
      }
      if (entry.traduccion) {
        html += `<div class="recorrido-traduccion">
          <div class="recorrido-traduccion-label">Traducción</div>
          ${nl2p(entry.traduccion)}
        </div>`;
      }
      if (entry.apuntes_traductologicos) {
        html += `<div class="recorrido-apuntes">${escHtml(entry.apuntes_traductologicos)}</div>`;
      }
      if (entry.anotacion) {
        html += `<div class="recorrido-anotacion">
          <div class="recorrido-anotacion-label">Anotación</div>
          ${nl2p(entry.anotacion)}
        </div>`;
      }
      html += `</div></div>`;
    });
  }
  if (data.sintesis_de_cobertura) {
    const s = data.sintesis_de_cobertura;
    html += `<div class="recorrido-sintesis">
      <h4>Síntesis de cobertura</h4>`;
    const fields = [
      ['Secciones procesadas', s.secciones_procesadas],
      ['Alcance', s.alcance],
      ['Contenido excluido', s.contenido_excluido],
      ['Idioma original', s.idioma_original],
      ['Observaciones globales', s.observaciones_globales],
    ];
    fields.forEach(([label, value]) => {
      if (value) {
        html += `<div class="sintesis-field">
          <div class="sintesis-field-label">${label}</div>
          <div class="sintesis-field-value">${escHtml(value)}</div>
        </div>`;
      }
    });
    html += `</div>`;
  }
  return html;
}

function renderResources(data) {
  let html = '';
  html += `<div class="resources-header">
    <h3 class="resources-title">${escHtml(data.titulo_mapa || 'Mapa de Recursos')}</h3>`;
  if (data.vision_general) {
    html += `<div class="resources-vision">${nl2p(data.vision_general)}</div>`;
  }
  html += `</div>`;

  if (data.ejes_tematicos && data.ejes_tematicos.length > 0) {
    data.ejes_tematicos.forEach(eje => {
      html += `<div class="resources-eje">
        <h4 class="resources-eje-title">${escHtml(eje.nombre_eje)}</h4>`;
      if (eje.recursos && eje.recursos.length > 0) {
        eje.recursos.forEach(r => {
          html += `<div class="resource-card">
            <div class="resource-top">
              <span class="resource-format-icon">${formatIconForResource(r.formato)}</span>
              <div class="resource-info">
                <div class="resource-title">${escHtml(r.titulo)}</div>
                <div class="resource-author">${escHtml(r.autor_creador)}</div>
                <div class="resource-datos">${escHtml(r.tipo_y_datos || '')}</div>
              </div>
            </div>`;
          if (r.conexion_con_texto) {
            html += `<div class="resource-conexion">${escHtml(r.conexion_con_texto)}</div>`;
          }
          html += `<div class="resource-meta">
            <span class="resource-nivel">${escHtml(r.nivel_y_accesibilidad || '')}</span>
            ${r.idioma ? `<span class="resource-idioma">${escHtml(r.idioma)}</span>` : ''}
            ${r.nota ? `<span class="resource-nota">⚠ ${escHtml(r.nota)}</span>` : ''}
          </div>`;
          html += `</div>`;
        });
      }
      html += `</div>`;
    });
  }
  if (data.nota_de_integridad) {
    html += `<div class="resources-integridad">
      <strong>Nota de integridad:</strong> ${escHtml(data.nota_de_integridad)}
    </div>`;
  }
  return html;
}

export function renderTab(tabName, contenido) {
  const loadingId = `loading-${tabName}`;
  const contentId = `content-${tabName}`;
  const loading = $(loadingId);
  const contentEl = $(contentId);

  if (!contenido) {
    hide(loading);
    contentEl.innerHTML = '';
    return;
  }

  const agentKey = tabName === 'explicacion' ? 'explainer' : tabName === 'recorrido' ? 'recorrido' : 'resources';
  const data = contenido[agentKey];

  if (contenido.status === 'processing') {
    show(loading);
    contentEl.innerHTML = '';
    return;
  }

  hide(loading);

  if (!data) {
    contentEl.innerHTML = '';
    return;
  }

  if (data.error) {
    contentEl.innerHTML = `<div class="error-state"><div class="error-state-title">Error en la generación</div>${escHtml(data.error)}</div>`;
    return;
  }

  if (tabName === 'explicacion') {
    contentEl.innerHTML = renderExplainer(data, state.currentPartId);
    renderGhostRail(state.currentPartId, data);
    renderSmartBar(state.currentPartId, data);
    // Defer positioning until DOM is laid out
    requestAnimationFrame(() => requestAnimationFrame(positionGhostRailNodes));
  } else if (tabName === 'recorrido') {
    contentEl.innerHTML = renderRecorrido(data);
  } else {
    contentEl.innerHTML = renderResources(data);
  }
}

export function activateTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    const isActive = panel.id === `panel-${tabName}`;
    panel.classList.toggle('active', isActive);
    panel.classList.toggle('hidden', !isActive);
  });
  saveViewState();
}

export function selectPart(partId) {
  // Idempotent: if THIS exact partId is already rendered into panel-explicacion,
  // bail out. Re-running selectPart for the same part would otherwise wipe
  // scrollTop, currentSubsectionId, the ghost rail / smart-bar, and re-fire
  // the observer — destroying any restored scroll position. We track the
  // rendered partId in a module variable instead of state.currentPartId
  // because most callers pre-assign state.currentPartId before calling here,
  // which would defeat a state-based guard.
  if (
    _renderedPartId === partId
    && state.currentProject
    && document.querySelector('#panel-explicacion .explainer-content, #panel-explicacion .explainer-section')
  ) {
    return;
  }

  // Clean up subsection UI from previous part
  document.querySelector('.ghost-rail')?.remove();
  document.querySelector('.smart-bar')?.remove();
  state.currentSubsectionId = null;

  state.lastPartChangeAt = Date.now();
  state.currentPartId = partId;

  const partContent = $('part-content');
  if (!partContent) return;

  document.querySelectorAll('.sidebar-part').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.partId) === partId);
  });

  hideProjectBootShell();
  hide($('proc-stage'));
  hide($('main-welcome'));
  show(partContent);

  const project = state.currentProject;
  const parte = project.segmentation.partes.find(p => p.numero === partId);
  const contenido = project.partes_contenido ? project.partes_contenido[String(partId)] : null;

  const titleEl = $('content-part-title');
  const descEl = $('content-part-description');
  const metaEl = $('content-part-meta');
  if (titleEl) titleEl.textContent = parte?.titulo ?? '';
  if (descEl) descEl.textContent = parte?.contenido ?? '';
  if (metaEl) {
    if (state.isSharedView) {
      metaEl.textContent = '';
      metaEl.closest('.part-header-row')?.classList.add('meta-hidden');
    } else {
      metaEl.closest('.part-header-row')?.classList.remove('meta-hidden');
      metaEl.textContent = [parte?.extension_estimada, parte?.complejidad].filter(Boolean).join(' · ');
    }
  }
  resetDescriptionExpand();
  const expandBtn = $('btn-description-expand');
  const wrap = document.querySelector('.part-description-wrap');
  if (expandBtn && wrap) {
    const hasDescription = parte?.contenido && parte.contenido.trim().length > 0;
    wrap.classList.toggle('has-description', !!hasDescription);
  }

  renderTab('explicacion', contenido);
  renderTab('recorrido', contenido);
  renderTab('recursos', contenido);

  activateTab(state.activeTab);

  const main = $('project-main');
  if (main) {
    // Use instant scroll to avoid intermediate scroll events during navigation
    // that would incorrectly mark the new section as read (smooth scroll fires
    // events with high pct before reaching top)
    main.scrollTop = 0;
  }

  updateReadingToolbar();
  updateMobileHeader();
  updateToggleCompleteButton();

  // Trigger observer setup after content is rendered
  if (typeof window.initSubsectionObserver === 'function') {
    setTimeout(window.initSubsectionObserver, 0);
  }

  _renderedPartId = partId;
  saveViewState();
}

/**
 * Shows or hides the reformat banner based on whether the project has
 * any completed parts that haven't gone through the formatting pass yet.
 * The banner is hidden for shared views (read-only).
 */
export function updateReformatBanner(project) {
  const banner = $('reformat-banner');
  if (!banner) return;

  // Never show in shared / read-only view
  if (state.isSharedView) {
    banner.classList.add('hidden');
    return;
  }

  if (project?.status !== 'completed') {
    banner.classList.add('hidden');
    return;
  }

  // The reformat action requires a live API connection — hide while offline.
  if (isOffline()) {
    banner.classList.add('hidden');
    return;
  }

  const partes = project?.partes_contenido || {};
  const needsReformat = Object.values(partes).some(
    p =>
      p.status === 'completed' &&
      p.explainer &&
      !p.formatter_version
  );

  banner.classList.toggle('hidden', !needsReformat);
}

/**
 * Handles click on the "Mejorar formato" button.
 * Calls POST /api/projects/{id}/reformat, waits for completion, then
 * reloads project data and re-renders the active tab.
 */
export async function handleReformat() {
  const btn = $('btn-reformat');
  const label = $('btn-reformat-label');
  if (!btn || !state.currentProjectId) return;

  // Prevent double-click
  if (btn.disabled) return;

  btn.disabled = true;
  if (label) label.textContent = 'Reformateando…';

  try {
    const reformatResult = await api(`/api/projects/${state.currentProjectId}/reformat`, {
      method: 'POST',
    });

    // Reload project with fresh formatted data
    const fresh = await api(`/api/projects/${state.currentProjectId}`);
    state.currentProject = fresh;

    // Persist formatted content to IndexedDB for offline access
    try {
      const backup = await loadBackupAsync(state.user?.id);
      const updatedProjects = backup.projects.map(p => p.id === fresh.id ? fresh : p);
      await syncProjectsToBackup(updatedProjects, state.user?.id);
    } catch (_) { /* non-fatal: cache update failure doesn't break the UI */ }

    // Update usage display with new formatter cost
    if (fresh.usage) updateUsageUI(fresh.usage);

    // Update banner (should disappear now)
    updateReformatBanner(fresh);

    // Re-render the active tab for the currently visible section
    if (state.currentPartId) {
      const contenido = fresh.partes_contenido?.[String(state.currentPartId)];
      if (contenido) {
        renderTab('explicacion', contenido);
        renderTab('recorrido', contenido);
        renderTab('recursos', contenido);
      }
    }

    const fmtCost = reformatResult?.formatter_cost;
    const costStr = fmtCost > 0 ? ` (coste: $${fmtCost.toFixed(4)})` : '';
    toast(`¡Formato mejorado aplicado correctamente!${costStr}`, 'success');
  } catch (err) {
    toast(
      'Error al aplicar el formato: ' + (err?.message || 'Error desconocido'),
      'error'
    );
    btn.disabled = false;
    if (label) label.textContent = 'Mejorar formato';
  }
}

export function renderProjectView(project) {
  // Any time we (re-)render a project's layout, force the next selectPart()
  // call to do a full render — the panel-explicacion may still hold content
  // from a previous project (renderProjectView itself does not clear it).
  _renderedPartId = null;

  $('sidebar-project-name').textContent = project.name;
  $('sidebar-status').innerHTML = `<span class="card-status-badge status-${project.status}">${statusLabel(project.status)}</span>`;

  hideProjectBootShell();
  renderSidebarNav(project);
  if (!state.isSharedView) {
    updateUsageUI(project.usage);
  }
  updateMobileHeader();
  applySharedViewVisibility();
  updateReformatBanner(project);

  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);

  if (!state.currentPartId) {
    if (isProcessing) {
      hide($('part-content'));
      hide($('main-welcome'));
      showProcessingIndicator(project.status);
      if (project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0) {
        renderProcPartsGrid(project);
      }
    } else {
      const hasPartes = project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0;
      showProjectIdleState(hasPartes);
    }
  }
}

export function syncProcessingUIWithState() {
  const project = state.currentProject;
  if (!project) return;
  hideProjectBootShell();
  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
  if (isProcessing) {
    hide($('part-content'));
    hide($('main-welcome'));
    showProcessingIndicator(project.status);
    if (project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0) {
      renderProcPartsGrid(project);
    }
  } else {
    hideProcessingIndicator();
  }
  renderSidebarNav(project);
  updateUsageUI(project.usage);
}

export function updateReadingToolbar() {
  const prevBtn = $('btn-part-prev');
  const nextBtn = $('btn-part-next');
  const label = $('toolbar-part-num');
  if (!prevBtn || !nextBtn || !label) return;

  const partes = state.currentProject?.segmentation?.partes || [];
  const idx = partes.findIndex(p => p.numero === state.currentPartId);

  prevBtn.disabled = idx <= 0;
  nextBtn.disabled = idx === -1 || idx >= partes.length - 1;

  if (idx !== -1) {
    label.textContent = `Sección ${idx + 1} de ${partes.length}`;
  } else {
    label.textContent = '–';
  }
}

export function updateToggleCompleteButton() {
  if (state.isSharedView) return;
  const btn = $('btn-toggle-complete');
  const project = state.currentProject;
  const partId = state.currentPartId;
  const contenido = project?.partes_contenido?.[String(partId)];
  const showToggle = project && partId && (contenido?.status === 'completed' || (contenido && (contenido.explainer || contenido.recorrido || contenido.resources)));

  document.querySelectorAll('.part-action-toggle-complete').forEach((el) => {
    el.style.display = showToggle ? '' : 'none';
  });

  if (!btn) return;
  if (!showToggle) return;

  const isRead = new Set(project?.reading_progress?.completed_parts || []).has(partId);
  btn.title = isRead ? 'Marcar como no leída' : 'Marcar como leída';
  btn.dataset.completed = isRead ? 'true' : 'false';
  const textEl = btn.querySelector('.btn-toggle-complete-text');
  const iconEl = btn.querySelector('.toggle-complete-icon');
  if (textEl) textEl.textContent = isRead ? 'Marcar como no leída' : 'Marcar como leída';
  if (iconEl) {
    iconEl.innerHTML = isRead
      ? '<path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />'
      : '<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="2" fill="none" />';
  }
  btn.classList.toggle('is-read', isRead);

  document.querySelectorAll('.part-actions-dropdown .part-action-toggle-complete').forEach((item) => {
    const textEl = item.querySelector('.part-action-item-text');
    if (textEl) textEl.textContent = isRead ? 'Marcar como no leída' : 'Marcar como leída';
  });
}

export function updateMobileHeader() {
  const el = $('mobile-project-name');
  if (el && state.currentProject) {
    el.textContent = state.currentProject.name || '';
  }
}

export function resetDescriptionExpand() {
  const wrap = document.querySelector('.part-description-wrap');
  const btn = $('btn-description-expand');
  if (wrap) wrap.classList.remove('expanded');
  if (btn) {
    btn.textContent = 'Ver más';
    btn.setAttribute('aria-label', 'Ver más');
  }
}
