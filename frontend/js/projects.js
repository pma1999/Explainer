/* ============================================================
   EXPLAINER — Projects List & Open
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, showView, formatDate, statusLabel, escHtml, toast } from './dom.js';
import { api } from './api.js';
import {
  loadBackupAsync,
  mergeProjects,
  syncProjectsToBackup,
  ensureProjectsFetched,
  invalidateProjectsCache,
  getCachedProjectAsync,
  getFirstIncompletePart,
  rehydrateProjectToServer,
} from './storage.js';
import {
  renderProjectView,
  selectPart,
  activateTab,
  syncProcessingUIWithState,
  showProjectLoadingState,
  showSectionLoadingState,
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

  const userId = state.user?.id;
  let cached = { projects: [] };
  try {
    cached = await loadBackupAsync(userId);
    if (cached.projects.length > 0) {
      renderProjectsList(cached.projects);
      showProjectsLoading(false);
    }
  } catch (_) {}

  const onQuotaExceeded = () => {
    toast('Almacenamiento local lleno. Los proyectos se cargan desde el servidor; no se guardará copia offline.', 'warning');
  };

  try {
    const merged = await ensureProjectsFetched({ onQuotaExceeded });
    renderProjectsList(merged);
  } catch (err) {
    if (cached.projects.length > 0) {
      renderProjectsList(cached.projects);
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

  showProjectLoadingState();
  showView('view-project');

  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const local = (await loadBackupAsync(state.user?.id)).projects;
    const refreshed = mergeProjects([project], local);
    await syncProjectsToBackup(refreshed, state.user?.id);

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
    const cachedProject = await getCachedProjectAsync(projectId);

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

function setupSSEForProject(projectId, project) {
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
}

export async function restoreProjectView(projectId, partId, activeTab) {
  const resolvedTab = activeTab || 'explicacion';
  state.currentProjectId = projectId;
  state.currentPartId = null;
  state.activeTab = resolvedTab;

  if (partId) {
    showSectionLoadingState(partId);
  } else {
    showProjectLoadingState();
  }
  showView('view-project');

  let cached = null;
  if (partId) {
    try {
      cached = await getCachedProjectAsync(projectId);
    } catch (_) {
      cached = null;
    }
  }
  const cachedHasSection = cached?.segmentation?.partes?.some((p) => p.numero === partId);
  const cachedNotProcessing = cached && !['pending', 'uploading', 'segmenting', 'processing'].includes(cached.status);

  if (partId && cached && cachedHasSection && cachedNotProcessing) {
    state.currentProject = cached;
    state.currentPartId = partId;
    state.activeTab = resolvedTab;
    renderProjectView(cached);
    selectPart(partId);
    activateTab(resolvedTab);

    api(`/api/projects/${projectId}`)
      .then(async (project) => {
        state.currentProject = project;
        const local = (await loadBackupAsync(state.user?.id)).projects;
        const refreshed = mergeProjects([project], local);
        await syncProjectsToBackup(refreshed, state.user?.id);
        renderProjectView(project);
        selectPart(partId);
        activateTab(resolvedTab);
        setupSSEForProject(projectId, project);
      })
      .catch(() => {});
    return;
  }

  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const local = (await loadBackupAsync(state.user?.id)).projects;
    const refreshed = mergeProjects([project], local);
    await syncProjectsToBackup(refreshed, state.user?.id);

    state.currentPartId = partId && project.segmentation?.partes?.some((p) => p.numero === partId) ? partId : null;
    state.activeTab = resolvedTab;

    renderProjectView(project);

    if (state.currentPartId) {
      selectPart(state.currentPartId);
      activateTab(state.activeTab);
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

    setupSSEForProject(projectId, project);
  } catch (err) {
    showView('view-projects');
    loadProjectsView();
    if (window.replaceRoute) window.replaceRoute({ view: 'projects' });
    toast('No se pudo restaurar la vista anterior', 'error');
  }
}

export { invalidateProjectsCache };
