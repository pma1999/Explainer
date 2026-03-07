/* ============================================================
   EXPLAINER — Projects List & Open
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, showView, formatDate, statusLabel, escHtml, toast } from './dom.js';
import { api } from './api.js';
import {
  loadLocalBackup,
  mergeProjects,
  syncProjectsToLocal,
  ensureProjectsFetched,
  invalidateProjectsCache,
  getCachedProject,
  getFirstIncompletePart,
  rehydrateProjectToServer,
} from './storage.js';
import {
  renderProjectView,
  selectPart,
  activateTab,
  syncProcessingUIWithState,
} from './projectView.js';
import { stopPolling, closeSSEIfDifferent, startSSE, startProjectsListPolling } from './sse.js';

function showProjectsLoading(isLoading) {
  const grid = $('projects-grid');
  const empty = $('projects-empty');
  const loading = $('projects-loading');
  if (!loading) return;
  if (isLoading) {
    hide(grid);
    hide(empty);
    show(loading);
  } else {
    hide(loading);
  }
}

function renderProjectsList(projects) {
  const grid = $('projects-grid');
  const empty = $('projects-empty');
  const count = $('projects-count');

  count.textContent = projects.length === 0
    ? ''
    : `${projects.length} proyecto${projects.length !== 1 ? 's' : ''}`;

  if (projects.length === 0) {
    hide(grid);
    show(empty);
    return;
  }

  show(grid);
  hide(empty);

  const isActive = (p) => ['uploading', 'segmenting', 'processing'].includes(p.status);
  const progress = (p) => {
    if (p.status === 'completed') return 100;
    if (p.status === 'uploading') return 10;
    if (p.status === 'segmenting') return 25;
    if (p.status === 'processing') return 60;
    return 0;
  };

  const numPartes = (p) => {
    if (p.segmentation && p.segmentation.partes) {
      return p.segmentation.partes.length;
    }
    return 0;
  };

  grid.innerHTML = projects.map(p => `
    <div class="project-card" data-id="${p.id}">
      <div class="card-meta">
        <span class="card-date">${formatDate(p.created_at)}</span>
        <span class="card-status-badge status-${p.status}">${statusLabel(p.status)}</span>
      </div>
      <div class="card-name">${escHtml(p.name)}</div>
      <div class="card-desc">${escHtml(p.description)}</div>
      ${isActive(p) ? `<div class="card-progress"><div class="card-progress-fill" style="width:${progress(p)}%"></div></div>` : ''}
      <div class="card-footer-info">
        ${numPartes(p) > 0 ? `<span class="card-parts">${numPartes(p)} partes</span>` : ''}
        ${p.usage && p.usage.total_cost > 0 ? `<span class="card-cost">$${p.usage.total_cost.toFixed(2)}</span>` : ''}
      </div>
    </div>
  `).join('');

  grid.querySelectorAll('.project-card').forEach(card => {
    card.addEventListener('click', () => {
      if (window.pushRoute) window.pushRoute({ view: 'project', projectId: card.dataset.id });
    });
  });

  const hasActive = projects.some((p) => ['pending', 'uploading', 'segmenting', 'processing'].includes(p.status));
  if (hasActive) startProjectsListPolling(renderProjectsList);
  else stopPolling();
}

export async function loadProjectsView() {
  showView('view-projects');
  showProjectsLoading(true);
  const localProjects = loadLocalBackup(state.user?.id).projects;

  try {
    const merged = await ensureProjectsFetched();
    renderProjectsList(merged);
  } catch (err) {
    if (localProjects.length > 0) {
      renderProjectsList(localProjects);
      toast('Servidor no disponible. Mostrando copia local de tus proyectos.', 'error');
    } else {
      toast('Error cargando proyectos: ' + err.message, 'error');
    }
  } finally {
    showProjectsLoading(false);
  }
}

export async function openProjectView(projectId) {
  state.currentProjectId = projectId;
  state.currentPartId = null;
  state.activeTab = 'explicacion';

  showView('view-project');

  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const refreshed = mergeProjects([project], loadLocalBackup(state.user?.id).projects);
    syncProjectsToLocal(refreshed, state.user?.id);

    renderProjectView(project);

    if (!state.currentPartId && project.status === 'completed') {
      const firstIncomplete = getFirstIncompletePart(project);
      if (firstIncomplete && window.pushRoute) {
        window.pushRoute({
          view: 'project',
          projectId,
          partId: firstIncomplete,
          tab: 'explicacion',
        });
      }
    }

    const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
    if (isProcessing) {
      if (state.sseProjectId === projectId && state.processingSSE) {
        if (state.processingSSE.readyState === EventSource.CLOSED) {
          startSSE(projectId, { forceReconnect: true });
        }
        syncProcessingUIWithState();
      } else {
        closeSSEIfDifferent(projectId);
        startSSE(projectId);
      }
    } else {
      if (state.processingSSE && state.sseProjectId === projectId) {
        state.processingSSE.close();
        state.processingSSE = null;
        state.sseProjectId = null;
      }
    }
  } catch (err) {
    const cachedProject = getCachedProject(projectId);

    if (cachedProject) {
      state.currentProject = cachedProject;
      renderProjectView(cachedProject);
      toast('Proyecto recuperado desde copia local. Intentando sincronizar en segundo plano…', 'success');

      rehydrateProjectToServer(cachedProject).catch(() => { });
      return;
    }

    toast('Error cargando proyecto: ' + err.message, 'error');
  }
}

export async function restoreProjectView(projectId, partId, activeTab) {
  state.currentProjectId = projectId;
  showView('view-project');
  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const refreshed = mergeProjects([project], loadLocalBackup(state.user?.id).projects);
    syncProjectsToLocal(refreshed, state.user?.id);

    renderProjectView(project);

    if (partId && project.segmentation?.partes?.some(p => p.numero === partId)) {
      state.currentPartId = partId;
      state.activeTab = activeTab;
      selectPart(partId);
      activateTab(activeTab);
    } else if (partId) {
      if (window.replaceRoute) window.replaceRoute({ view: 'project', projectId });
    } else if (project.status === 'completed') {
      const firstIncomplete = getFirstIncompletePart(project);
      if (firstIncomplete && window.pushRoute) {
        window.pushRoute({
          view: 'project',
          projectId,
          partId: firstIncomplete,
          tab: 'explicacion',
        });
      }
    }

    const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
    if (isProcessing) {
      if (state.sseProjectId === projectId && state.processingSSE) {
        if (state.processingSSE.readyState === EventSource.CLOSED) {
          startSSE(projectId, { forceReconnect: true });
        }
      } else {
        closeSSEIfDifferent(projectId);
        startSSE(projectId);
      }
    }
  } catch (err) {
    showView('view-projects');
    loadProjectsView();
    if (window.replaceRoute) window.replaceRoute({ view: 'projects' });
    toast('No se pudo restaurar la vista anterior', 'error');
  }
}

export { invalidateProjectsCache };
