/* ============================================================
   EXPLAINER — Shared Project View (unauthenticated)
   Load and display shared projects for guests
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, showView, toast } from './dom.js';
import {
  renderProjectView,
  selectPart,
  activateTab,
  showSectionLoadingState,
} from './projectView.js';

const API_BASE_URL = window.EXPLAINER_API_BASE_URL || '';

export async function loadSharedProject(shareToken, partId, tab) {
  state.isSharedView = true;
  state.shareToken = shareToken;
  state.currentProjectId = null;
  state.currentPartId = partId || null;
  state.activeTab = tab || 'explicacion';

  showView('view-project');

  if (partId) {
    showSectionLoadingState(partId);
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/shared/${encodeURIComponent(shareToken)}`);
    if (!res.ok) {
      if (res.status === 404) {
        toast('Enlace no válido o expirado', 'error');
      } else {
        toast('Error al cargar el proyecto compartido', 'error');
      }
      state.isSharedView = false;
      state.shareToken = null;
      return;
    }

    const project = await res.json();
    state.currentProject = project;
    state.currentProjectId = project.id;

    renderProjectView(project);

    if (state.currentPartId && project.segmentation?.partes?.some((p) => p.numero === state.currentPartId)) {
      selectPart(state.currentPartId);
      activateTab(state.activeTab);
      if (window.replaceRoute) {
        window.replaceRoute({
          view: 'shared',
          shareToken,
          partId: state.currentPartId,
          tab: state.activeTab,
        });
      }
    } else if (partId) {
      if (window.replaceRoute) {
        window.replaceRoute({ view: 'shared', shareToken });
      }
    } else if (project.segmentation?.partes?.length > 0) {
      const firstPart = project.segmentation.partes[0].numero;
      state.currentPartId = firstPart;
      if (window.pushRoute) {
        window.pushRoute({
          view: 'shared',
          shareToken,
          partId: firstPart,
          tab: 'explicacion',
        });
      }
      selectPart(firstPart);
      activateTab('explicacion');
    }
  } catch (err) {
    toast('Error al cargar el proyecto compartido: ' + err.message, 'error');
    state.isSharedView = false;
    state.shareToken = null;
  }
}

export function exitSharedView() {
  state.isSharedView = false;
  state.shareToken = null;
  state.currentProjectId = null;
  state.currentProject = null;
  state.currentPartId = null;
}
