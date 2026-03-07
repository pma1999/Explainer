/* ============================================================
   EXPLAINER — SSE, Polling & Visibility
   ============================================================ */

import {
  state,
  SSE_RECONNECT_MAX,
  SSE_RECONNECT_DELAY_MS,
  POLL_PROJECTS_MS,
  POLL_CURRENT_IF_IDLE_MS,
  VISIBILITY_RECONNECT_DELAY_MS,
} from './state.js';
import { $, show, hide, toast } from './dom.js';
import { api, API_BASE_URL, getAccessToken } from './api.js';
import { loadBackupAsync, mergeProjects, syncProjectsToBackup } from './storage.js';
import {
  renderProjectView,
  renderSidebarNav,
  renderTab,
  renderProcPartsGrid,
  updateProcPartCard,
  completeProcPartCard,
  updateUsageUI,
  showProcessingIndicator,
  hideProcessingIndicator,
  setProcPhase,
  selectPart,
  syncProcessingUIWithState,
} from './projectView.js';

export function stopPolling() {
  if (state.pollProjectsInterval) {
    clearInterval(state.pollProjectsInterval);
    state.pollProjectsInterval = null;
  }
  if (state.pollCurrentProjectInterval) {
    clearInterval(state.pollCurrentProjectInterval);
    state.pollCurrentProjectInterval = null;
  }
}

export function closeSSEIfDifferent(projectId) {
  if (state.processingSSE && state.sseProjectId !== projectId) {
    state.processingSSE.close();
    state.processingSSE = null;
    state.sseProjectId = null;
  }
}

export function startProjectsListPolling(renderProjectsList) {
  stopPolling();
  state.pollProjectsInterval = setInterval(async () => {
    const view = document.querySelector('.view.active');
    if (!view || view.id !== 'view-projects') return;
    try {
      const [serverProjects, local] = await Promise.all([
        api('/api/projects'),
        loadBackupAsync(state.user?.id),
      ]);
      const merged = mergeProjects(serverProjects, local.projects);
      const hasActive = merged.some((p) => ['pending', 'uploading', 'segmenting', 'processing'].includes(p.status));
      await syncProjectsToBackup(merged, state.user?.id);
      renderProjectsList(merged);
      if (!hasActive && state.pollProjectsInterval) {
        clearInterval(state.pollProjectsInterval);
        state.pollProjectsInterval = null;
      }
    } catch (_) { /* ignore */ }
  }, POLL_PROJECTS_MS);
}

export function startSSE(projectId, opts = {}) {
  if (state.processingSSE && state.sseProjectId === projectId && !opts.forceReconnect) {
    syncProcessingUIWithState();
    return;
  }

  if (state.processingSSE && state.sseProjectId !== projectId) {
    state.processingSSE.close();
  }

  state.sseProjectId = projectId;
  state.sseReconnectAttempts = 0;
  state.sseLastEventAt = Date.now();
  const procForge = $('proc-forge');
  const procGrid = $('proc-parts-grid');
  if (procForge) procForge.classList.remove('hidden');
  if (procGrid) { procGrid.classList.add('hidden'); procGrid.innerHTML = ''; }

  function connect() {
    const token = getAccessToken();
    const base = `${API_BASE_URL}/api/projects/${projectId}/events`;
    const url = token ? `${base}?token=${encodeURIComponent(token)}` : base;
    const evtSource = new EventSource(url);
    state.processingSSE = evtSource;

    evtSource.onmessage = async (e) => {
      state.sseLastEventAt = Date.now();
      let payload;
      try {
        payload = JSON.parse(e.data);
      } catch {
        return;
      }

      const project = state.currentProject;
      if (!project || state.currentProjectId !== projectId) return;

      switch (payload.type) {
        case 'ping':
          break;

        case 'usage_update':
          if (state.currentProject) {
            state.currentProject.usage = payload.usage;
            updateUsageUI(payload.usage);
          }
          break;

        case 'uploading':
          project.status = 'uploading';
          setProcPhase('uploading');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-uploading">Subiendo</span>`;
          break;

        case 'segmenting':
          project.status = 'segmenting';
          setProcPhase('segmenting');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-segmenting">Segmentando</span>`;
          break;

        case 'segmented': {
          project.status = 'processing';
          try {
            const fresh = await api(`/api/projects/${projectId}`);
            state.currentProject = fresh;
            Object.assign(project, { segmentation: fresh.segmentation, partes_contenido: fresh.partes_contenido || {} });
          } catch (_) { }
          renderSidebarNav(state.currentProject);
          setProcPhase('processing');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-processing">Procesando</span>`;
          renderProcPartsGrid(state.currentProject);
          break;
        }

        case 'part_started': {
          const psKey = String(payload.part_id);
          if (project.partes_contenido) {
            if (!project.partes_contenido[psKey]) {
              project.partes_contenido[psKey] = { status: 'processing', explainer: null, recorrido: null, resources: null };
            } else {
              project.partes_contenido[psKey].status = 'processing';
            }
            renderSidebarNav(state.currentProject);
          }
          const psCard = document.querySelector(`#proc-parts-grid .proc-part-card[data-part-id="${payload.part_id}"]`);
          if (psCard) {
            psCard.classList.remove('pending');
            psCard.classList.add('processing');
          }
          break;
        }

        case 'agent_completed': {
          const key = String(payload.part_id);
          const agent = payload.agent;
          updateProcPartCard(payload.part_id, agent);
          try {
            const fresh = await api(`/api/projects/${projectId}`);
            if (!state.currentProject) return;
            state.currentProject.usage = fresh.usage || state.currentProject.usage;
            if (fresh.partes_contenido && fresh.partes_contenido[key]) {
              if (!state.currentProject.partes_contenido[key]) state.currentProject.partes_contenido[key] = {};
              state.currentProject.partes_contenido[key][agent] = fresh.partes_contenido[key][agent];
              state.currentProject.partes_contenido[key].status = fresh.partes_contenido[key].status;
            }
            updateUsageUI(state.currentProject.usage);
            const contenido = state.currentProject.partes_contenido[key];
            if (state.currentPartId === payload.part_id && contenido) {
              renderTab('explicacion', contenido);
              renderTab('recorrido', contenido);
              renderTab('recursos', contenido);
            }
            renderSidebarNav(state.currentProject);
          } catch (_) { }
          break;
        }

        case 'part_completed': {
          const key = String(payload.part_id);
          if (project.partes_contenido && project.partes_contenido[key]) {
            project.partes_contenido[key].status = 'completed';
          }
          renderSidebarNav(state.currentProject);
          completeProcPartCard(payload.part_id);
          if (state.currentPartId === payload.part_id) {
            selectPart(payload.part_id);
          }
          break;
        }

        case 'completed':
          project.status = 'completed';
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-completed">Completado</span>`;
          if ($('proc-phase-orb')) $('proc-phase-orb').className = 'proc-phase-orb orb-done';
          if ($('proc-phase-label')) $('proc-phase-label').textContent = 'Análisis completo';
          if ($('proc-phase-sub')) $('proc-phase-sub').textContent = 'Todo el contenido está listo';
          document.querySelectorAll('.proc-step').forEach(el => { el.classList.remove('active'); el.classList.add('done'); });
          document.querySelectorAll('.proc-step-line').forEach(el => { el.classList.remove('active'); el.classList.add('done'); });
          setTimeout(() => hideProcessingIndicator(), 1200);
          toast('¡Análisis completo! Ya puedes estudiar todo el contenido.', 'success');
          evtSource.close();
          state.processingSSE = null;
          stopPolling();
          break;

        case 'error':
          project.status = 'error';
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-error">Error</span>`;
          toast('Error: ' + (payload.message || 'Error desconocido'), 'error');
          evtSource.close();
          state.processingSSE = null;
          stopPolling();
          break;

        case 'stream_end':
          evtSource.close();
          state.processingSSE = null;
          break;
      }
    };

    evtSource.onerror = () => {
      evtSource.close();
      state.processingSSE = null;
      if (state.currentProjectId !== projectId) return;
      const isActive = state.currentProject && ['pending', 'uploading', 'segmenting', 'processing'].includes(state.currentProject.status);
      if (!isActive) return;
      if (state.sseReconnectAttempts < SSE_RECONNECT_MAX) {
        state.sseReconnectAttempts += 1;
        setTimeout(connect, SSE_RECONNECT_DELAY_MS);
      } else {
        startCurrentProjectPolling(projectId);
      }
    };
  }

  connect();

  function startCurrentProjectPolling(pid) {
    if (state.pollCurrentProjectInterval) return;
    state.pollCurrentProjectInterval = setInterval(async () => {
      if (state.currentProjectId !== pid || !state.currentProject) return;
      const status = state.currentProject.status;
      if (!['pending', 'uploading', 'segmenting', 'processing'].includes(status)) {
        clearInterval(state.pollCurrentProjectInterval);
        state.pollCurrentProjectInterval = null;
        return;
      }
      try {
        const fresh = await api(`/api/projects/${pid}`);
        state.currentProject = fresh;
        renderProjectView(fresh);
        renderSidebarNav(fresh);
        updateUsageUI(fresh.usage);
        if (state.currentPartId) {
          const contenido = fresh.partes_contenido?.[String(state.currentPartId)];
          if (contenido) {
            renderTab('explicacion', contenido);
            renderTab('recorrido', contenido);
            renderTab('recursos', contenido);
          }
        }
        if (fresh.status === 'completed') {
          toast('¡Análisis completo!', 'success');
          stopPolling();
        } else if (fresh.status === 'error') {
          stopPolling();
        }
      } catch (_) { }
    }, POLL_CURRENT_IF_IDLE_MS);
  }

  if (state.sseLastEventAt > 0) {
    const checkIdle = setInterval(() => {
      if (!state.processingSSE || state.currentProjectId !== projectId) {
        clearInterval(checkIdle);
        return;
      }
      if (Date.now() - state.sseLastEventAt > POLL_CURRENT_IF_IDLE_MS) {
        startCurrentProjectPolling(projectId);
        clearInterval(checkIdle);
      }
    }, 4000);
  }
}

export function initVisibilityHandling() {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      state.ssePausedByVisibility = true;
    } else {
      const wasPaused = state.ssePausedByVisibility;
      state.ssePausedByVisibility = false;
      if (wasPaused && state.sseProjectId && state.currentProjectId === state.sseProjectId) {
        const idle = Date.now() - state.sseLastEventAt > 5000;
        const closed = !state.processingSSE || state.processingSSE.readyState === EventSource.CLOSED;
        if (idle || closed) {
          setTimeout(() => startSSE(state.sseProjectId, { forceReconnect: true }), VISIBILITY_RECONNECT_DELAY_MS);
        }
      }
    }
  });
}
