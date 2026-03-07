/* ============================================================
   EXPLAINER — Project Detail View, Sidebar, Proc-Stage, Renderers
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, formatDate, statusLabel, formatIconForResource, escHtml, nl2p, toast } from './dom.js';
import { api } from './api.js';

let _saveViewState = null;
export function setSaveViewStateCallback(fn) {
  _saveViewState = fn;
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

/** Toggle section read status manually. */
export async function toggleSectionComplete(partId, completed) {
  if (!state.currentProjectId || !state.currentProject || !state.user?.id) return;
  const project = state.currentProject;
  const contenido = project.partes_contenido?.[String(partId)];
  if (!contenido || contenido.status !== 'completed') return;
  const completedSet = new Set(project?.reading_progress?.completed_parts || []);
  if (completed && completedSet.has(partId)) return;
  if (!completed && !completedSet.has(partId)) return;

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
      toast(completed ? 'Marcada como leída' : 'Marcada como no leída', 'success');
    }
  } catch (_) {
    toast('Error al actualizar el progreso', 'error');
  }
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
  const completedParts = new Set(project?.reading_progress?.completed_parts || []);

  project.segmentation.partes.forEach(parte => {
    const partId = parte.numero;
    const contenido = project.partes_contenido ? project.partes_contenido[String(partId)] : null;
    const status = contenido ? contenido.status : 'pending';
    const isRead = completedParts.has(partId);
    const canToggle = status === 'completed';

    const dotClass = {
      pending: 'dot-pending',
      processing: 'dot-processing',
      completed: 'dot-completed',
      error: 'dot-error',
    }[status] || 'dot-pending';

    const href = (typeof window.buildHash === 'function' && projectId)
      ? window.buildHash({
          view: 'project',
          projectId,
          partId,
          tab: state.activeTab,
        })
      : '#';

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

function renderExplainer(data) {
  let html = '';
  if (data.introduccion) {
    html += `<div class="explainer-intro">${nl2p(data.introduccion)}</div>`;
  }
  if (data.desarrollo && data.desarrollo.length > 0) {
    data.desarrollo.forEach(section => {
      html += `<div class="explainer-section">`;
      html += `<h3 class="explainer-section-title">${escHtml(section.titulo_seccion)}</h3>`;
      if (section.explicacion_introductoria) {
        html += `<p class="explainer-section-intro">${escHtml(section.explicacion_introductoria)}</p>`;
      }
      if (section.subsecciones && section.subsecciones.length > 0) {
        section.subsecciones.forEach(sub => {
          html += `<div class="explainer-subsection">`;
          html += `<h4 class="explainer-subsection-title">${escHtml(sub.titulo_subseccion)}</h4>`;
          html += `<div class="explainer-text">${nl2p(sub.explicacion_detallada)}</div>`;
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
        ${nl2p(data.conclusion)}
      </div>`;
  }
  if (data.conexiones_contextuales && data.conexiones_contextuales.length > 0) {
    html += `<div class="explainer-section"><h3 class="explainer-section-title">Conexiones contextuales</h3>`;
    data.conexiones_contextuales.forEach(cx => {
      html += `<div class="explainer-subsection">
        <h4 class="explainer-subsection-title">${escHtml(cx.seccion_temario_relacionada)}</h4>
        <div class="explainer-text"><p>${escHtml(cx.descripcion_conexion)}</p></div>
      </div>`;
    });
    html += `</div>`;
  }
  return html;
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
    contentEl.innerHTML = renderExplainer(data);
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
  state.lastPartChangeAt = Date.now();
  state.currentPartId = partId;

  const partContent = $('part-content');
  if (!partContent) return;

  document.querySelectorAll('.sidebar-part').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.partId) === partId);
  });

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
  if (metaEl) metaEl.textContent = [parte?.extension_estimada, parte?.complejidad].filter(Boolean).join(' · ');
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
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' });

  updateReadingToolbar();
  updateMobileHeader();
  updateToggleCompleteButton();

  saveViewState();
}

export function renderProjectView(project) {
  $('sidebar-project-name').textContent = project.name;
  $('sidebar-status').innerHTML = `<span class="card-status-badge status-${project.status}">${statusLabel(project.status)}</span>`;

  renderSidebarNav(project);
  updateUsageUI(project.usage);
  updateMobileHeader();

  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);

  if (!state.currentPartId) {
    hide($('part-content'));
    if (isProcessing) {
      showProcessingIndicator(project.status);
      hide($('main-welcome'));
      if (project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0) {
        renderProcPartsGrid(project);
      }
    } else {
      hideProcessingIndicator();
      show($('main-welcome'));
      const hasPartes = project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0;
      $('welcome-title').textContent = hasPartes ? 'Selecciona una sección' : 'Sin contenido';
      $('welcome-sub').textContent = hasPartes
        ? 'Haz clic en cualquier sección para ver su contenido.'
        : 'No hay secciones disponibles.';
    }
  }
}

export function syncProcessingUIWithState() {
  const project = state.currentProject;
  if (!project) return;
  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
  if (isProcessing) {
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
  const btn = $('btn-toggle-complete');
  const project = state.currentProject;
  const partId = state.currentPartId;
  const showToggle = project && partId && project.partes_contenido?.[String(partId)]?.status === 'completed';

  document.querySelectorAll('.part-action-toggle-complete').forEach((el) => {
    el.style.display = showToggle ? '' : 'none';
  });

  if (!btn) return;
  if (!showToggle) return;

  const contenido = project.partes_contenido[String(partId)];
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

