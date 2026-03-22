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
  pinProjectOffline,
  unpinProjectOffline,
  getOfflinePins,
  isProjectPinned,
} from './storage.js';
import { isOffline } from './pwa.js';
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

async function renderProjectsList(projects, pinnedIds) {
  const grid = $('projects-grid');
  const empty = $('projects-empty');
  const count = $('projects-count');

  // Load pinned IDs if not provided
  const pins = pinnedIds instanceof Set
    ? pinnedIds
    : new Set(await getOfflinePins().catch(() => []));

  const offline = isOffline();

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

  grid.innerHTML = projects.map(p => {
    const isPinned = pins.has(p.id);
    const pinTitle = isPinned ? 'Quitar acceso offline' : 'Guardar para uso offline';
    const pinAriaLabel = isPinned ? 'Disponible offline — haz clic para desactivar' : 'Activar acceso offline';
    return `
    <div class="project-card" data-id="${p.id}" data-pinned="${isPinned}">
      <div class="card-meta">
        <span class="card-date">${formatDate(p.created_at)}</span>
        <span class="card-status-badge status-${p.status}">${statusLabel(p.status)}</span>
        ${isPinned && offline ? `<span class="offline-badge" title="Disponible sin conexión">Offline</span>` : ''}
      </div>
      <div class="card-name">${escHtml(p.name)}</div>
      <div class="card-desc">${escHtml(p.description)}</div>
      ${isActive(p) ? `<div class="card-progress"><div class="card-progress-fill" style="width:${progress(p)}%"></div></div>` : ''}
      <div class="card-footer-info">
        ${numPartes(p) > 0 ? `<span class="card-parts">${numPartes(p)} partes</span>` : ''}
        ${p.usage && p.usage.total_cost > 0 ? `<span class="card-cost">$${p.usage.total_cost.toFixed(2)}</span>` : ''}
        <button
          class="offline-pin-btn${isPinned ? ' pinned' : ''}"
          data-project-id="${p.id}"
          title="${pinTitle}"
          aria-label="${pinAriaLabel}"
          aria-pressed="${isPinned}"
          type="button"
        >${isPinned ? '✓ Offline' : '☁'}</button>
      </div>
    </div>
  `;
  }).join('');

  // Card click → navigate (but NOT when clicking the pin button)
  grid.querySelectorAll('.project-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('.offline-pin-btn')) return;
      const projectId = card.dataset.id;
      if (offline && !pins.has(projectId)) {
        toast('Este proyecto no está disponible offline. Conéctate para abrirlo.', 'error');
        return;
      }
      if (window.pushRoute) window.pushRoute({ view: 'project', projectId });
    });
  });

  // Pin button click handler
  grid.querySelectorAll('.offline-pin-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const projectId = btn.dataset.projectId;
      const wasPinned = btn.classList.contains('pinned');
      try {
        if (wasPinned) {
          await unpinProjectOffline(projectId);
          pins.delete(projectId);
          toast('Proyecto eliminado del acceso offline', 'success');
        } else {
          await pinProjectOffline(projectId);
          pins.add(projectId);
          toast('Proyecto disponible offline ✓', 'success');
        }
        // Update the single button in place without full re-render
        const isPinnedNow = pins.has(projectId);
        btn.classList.toggle('pinned', isPinnedNow);
        btn.title = isPinnedNow ? 'Quitar acceso offline' : 'Guardar para uso offline';
        btn.setAttribute('aria-label', isPinnedNow ? 'Disponible offline — haz clic para desactivar' : 'Activar acceso offline');
        btn.setAttribute('aria-pressed', String(isPinnedNow));
        btn.textContent = isPinnedNow ? '✓ Offline' : '☁';

        // Also update the offline badge in the card meta
        const card = btn.closest('.project-card');
        if (card) card.dataset.pinned = String(isPinnedNow);
        const meta = card?.querySelector('.card-meta');
        if (meta) {
          const existingBadge = meta.querySelector('.offline-badge');
          if (existingBadge) existingBadge.remove();
          if (isPinnedNow && offline) {
            const badge = document.createElement('span');
            badge.className = 'offline-badge';
            badge.title = 'Disponible sin conexión';
            badge.textContent = 'Offline';
            meta.appendChild(badge);
          }
        }
      } catch (err) {
        toast('Error al actualizar el acceso offline', 'error');
      }
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
  // Pre-load pins so they're available for initial render
  const pins = new Set(await getOfflinePins().catch(() => []));

  try {
    cached = await loadBackupAsync(userId);
    if (cached.projects.length > 0) {
      await renderProjectsList(cached.projects, pins);
      showProjectsLoading(false);
    }
  } catch (_) {}

  const onQuotaExceeded = () => {
    toast('Almacenamiento local lleno. Los proyectos se cargan desde el servidor; no se guardará copia offline.', 'warning');
  };

  try {
    const merged = await ensureProjectsFetched({ onQuotaExceeded });
    await renderProjectsList(merged, pins);
  } catch (err) {
    if (cached.projects.length > 0) {
      await renderProjectsList(cached.projects, pins);
      toast('Sin conexión — mostrando proyectos guardados localmente', 'error');
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

  if (isOffline()) {
    const pinned = await isProjectPinned(projectId).catch(() => false);
    if (!pinned) {
      toast('Este proyecto no está disponible offline. Desactiva el modo offline o conéctate.', 'error');
      if (window.pushRoute) window.pushRoute({ view: 'projects' });
      return;
    }
    const cachedProject = await getCachedProjectAsync(projectId);
    if (!cachedProject) {
      toast('No hay copia local de este proyecto.', 'error');
      if (window.pushRoute) window.pushRoute({ view: 'projects' });
      return;
    }
    state.currentProject = cachedProject;
    renderProjectView(cachedProject);

    if (!state.currentPartId && cachedProject.status === 'completed') {
      const firstIncomplete = getFirstIncompletePart(cachedProject);
      if (firstIncomplete && window.pushRoute) {
        window.pushRoute({
          view: 'project',
          projectId,
          partId: firstIncomplete,
          tab: 'explicacion',
        });
      }
    }

    const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(cachedProject.status);
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
    } else if (state.processingSSE && state.sseProjectId === projectId) {
      state.processingSSE.close();
      state.processingSSE = null;
      state.sseProjectId = null;
    }
    return;
  }

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

      if (!isOffline()) {
        rehydrateProjectToServer(cachedProject).catch(() => {});
      }
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

  if (isOffline()) {
    const pinned = await isProjectPinned(projectId).catch(() => false);
    if (!pinned) {
      toast('Este proyecto no está disponible offline. Desactiva el modo offline o conéctate.', 'error');
      showView('view-projects');
      loadProjectsView();
      if (window.replaceRoute) window.replaceRoute({ view: 'projects' });
      return;
    }
    let localCached = null;
    try {
      localCached = await getCachedProjectAsync(projectId);
    } catch (_) {}
    if (!localCached) {
      toast('No hay copia local de este proyecto.', 'error');
      showView('view-projects');
      loadProjectsView();
      if (window.replaceRoute) window.replaceRoute({ view: 'projects' });
      return;
    }
    state.currentProject = localCached;
    state.currentPartId =
      partId && localCached.segmentation?.partes?.some((p) => p.numero === partId)
        ? partId
        : null;
    state.activeTab = resolvedTab;
    renderProjectView(localCached);
    if (state.currentPartId) {
      selectPart(state.currentPartId);
      activateTab(state.activeTab);
    } else if (partId) {
      if (window.replaceRoute) window.replaceRoute({ view: 'project', projectId });
    } else if (localCached.status === 'completed') {
      const firstIncomplete = getFirstIncompletePart(localCached);
      if (firstIncomplete && window.pushRoute) {
        window.pushRoute({
          view: 'project',
          projectId,
          partId: firstIncomplete,
          tab: 'explicacion',
        });
      }
    }
    setupSSEForProject(projectId, localCached);
    return;
  }

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

    if (!isOffline()) {
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
    }
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
