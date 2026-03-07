/* ============================================================
   EXPLAINER — Main Entry & Bootstrap
   ============================================================ */

import { state, supabaseClient } from './state.js';
import { $, show, hide, showView, setViewChangeCallback, toast } from './dom.js';
import { api } from './api.js';
import {
  loadLocalBackup,
  syncProjectsToLocal,
  migrateLegacyBackupIfNeeded,
  ensureProjectsFetched,
  invalidateProjectsCache,
} from './storage.js';
import { initAuth, initSettings, refreshApiKeyStatus } from './auth.js';
import { initLanding } from './landing.js';
import { loadProjectsView, openProjectView, restoreProjectView } from './projects.js';
import { stopPolling } from './sse.js';
import { initVisibilityHandling } from './sse.js';
import { initObsidianExport, initFullProjectExport, exportProjectsBackup, importProjectsBackup } from './export.js';
import { selectPart, activateTab, markSectionComplete, toggleSectionComplete } from './projectView.js';

function saveViewState() {
  if (!state.user?.id) return;

  const activeView = document.querySelector('.view.active')?.id || 'view-landing';
  const viewState = {
    userId: state.user.id,
    view: activeView,
    projectId: state.currentProjectId,
    partId: state.currentPartId,
    activeTab: state.activeTab,
    savedAt: new Date().toISOString(),
  };
  sessionStorage.setItem('explainer.viewState', JSON.stringify(viewState));
}

function navigateFromRoute(route) {
  if (!route) return;

  if (route.view === 'landing') {
    showView('view-landing');
    refreshApiKeyStatus();
    initLanding();
    return;
  }

  if (route.view === 'projects') {
    showView('view-projects');
    loadProjectsView();
    return;
  }

  if (route.view === 'project' && route.projectId) {
    if (route.partId) {
      const projectId = route.projectId;
      const partId = route.partId;
      const tab = route.tab || 'explicacion';

      if (state.currentProjectId === projectId && state.currentProject) {
        const parteExists = state.currentProject.segmentation?.partes?.some(p => p.numero === partId);
        if (parteExists) {
          state.currentPartId = partId;
          state.activeTab = tab;
          selectPart(partId);
          activateTab(tab);
          return;
        }
        if (window.replaceRoute) window.replaceRoute({ view: 'project', projectId });
        openProjectView(projectId);
        return;
      }
      restoreProjectView(projectId, partId, tab).catch(() => {});
      return;
    }

    openProjectView(route.projectId);
  }
}

async function initApp() {
  if (!supabaseClient) {
    showView('view-auth');
    document.querySelector('.auth-subtitle').textContent = 'Supabase no configurado. Define EXPLAINER_SUPABASE_URL y EXPLAINER_SUPABASE_ANON_KEY.';
    initAuth(navigateFromRoute, initLanding);
    return;
  }

  const { data: { session } } = await supabaseClient.auth.getSession();
  state.session = session;
  state.user = session?.user ?? null;

  if (typeof window.initRouter === 'function') {
    window.initRouter(navigateFromRoute);
  }

  supabaseClient.auth.onAuthStateChange((_event, newSession) => {
    const prevUserId = state.user?.id ?? null;
    const newUserId = newSession?.user?.id ?? null;

    state.session = newSession;
    state.user = newSession?.user ?? null;

    if (!prevUserId && newUserId) {
      refreshApiKeyStatus();
      const route = window.parseRoute ? window.parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        navigateFromRoute(route);
      } else {
        if (window.pushRoute) window.pushRoute({ view: 'landing' });
        showView('view-landing');
        initLanding();
      }
    } else if (prevUserId && !newUserId) {
      if (state.processingSSE) {
        state.processingSSE.close();
        state.processingSSE = null;
        state.sseProjectId = null;
      }
      stopPolling();
      showView('view-auth');
    } else if (prevUserId && newUserId && prevUserId !== newUserId) {
      invalidateProjectsCache();
      state.apiKeyStatus = 'loading';
      if (state.processingSSE) {
        state.processingSSE.close();
        state.processingSSE = null;
        state.sseProjectId = null;
      }
      stopPolling();
      state.currentProjectId = null;
      state.currentProject = null;
      state.currentPartId = null;
      sessionStorage.removeItem('explainer.viewState');
      showView('view-landing');
      refreshApiKeyStatus();
      initLanding();
    } else if (newUserId) {
      refreshApiKeyStatus();
    }
  });

  if (!state.session) {
    showView('view-auth');
    initAuth(navigateFromRoute, initLanding);
    return;
  }

  migrateLegacyBackupIfNeeded(state.user?.id);
  ensureProjectsFetched();
  refreshApiKeyStatus();

  const route = window.parseRoute ? window.parseRoute() : null;
  if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
    await navigateFromRoute(route);
    return;
  }

  const savedState = sessionStorage.getItem('explainer.viewState');
  if (savedState) {
    try {
      const viewState = JSON.parse(savedState);
      if (viewState.userId === state.user?.id) {
        if (viewState.view === 'view-project' && viewState.projectId) {
          state.currentProjectId = viewState.projectId;
          state.currentPartId = viewState.partId || null;
          state.activeTab = viewState.activeTab || 'explicacion';
          await restoreProjectView(viewState.projectId, viewState.partId, viewState.activeTab);
          if (window.replaceRoute) {
            window.replaceRoute({
              view: 'project',
              projectId: viewState.projectId,
              partId: viewState.partId,
              tab: viewState.activeTab || 'explicacion',
            });
          }
          return;
        } else if (viewState.view === 'view-projects') {
          showView('view-projects');
          loadProjectsView();
          if (window.replaceRoute) window.replaceRoute({ view: 'projects' });
          return;
        } else if (viewState.view === 'view-landing') {
          showView('view-landing');
          initLanding();
          await refreshApiKeyStatus();
          return;
        }
      }
    } catch (_) {}
  }

  if (window.pushRoute) window.pushRoute({ view: 'landing' });
  showView('view-landing');
  initLanding();
  await refreshApiKeyStatus();
}

const NAVIGATION_COOLDOWN_MS = 400;

function initReadingProgressBar() {
  const scrollMarkedParts = new Set();
  let scrollCompleteDebounce = null;

  function getScrollPct(el) {
    if (!el) return 0;
    const { scrollTop, scrollHeight, clientHeight } = el;
    if (scrollHeight <= clientHeight) return 0;
    return (scrollTop / (scrollHeight - clientHeight)) * 100;
  }

  function handleScrollForProgress(ev) {
    const main = $('project-main');
    const bar = $('reading-progress-bar');
    if (!bar) return;

    const target = ev.target;
    let pct = 0;
    if (target === main && main.scrollHeight > main.clientHeight) {
      pct = getScrollPct(main);
    } else if (target === document.documentElement || target === document.body || target === document) {
      pct = getScrollPct(document.documentElement);
    } else if (main && main.scrollHeight > main.clientHeight) {
      pct = getScrollPct(main);
    }

    bar.style.width = pct + '%';

    const partId = state.currentPartId;
    if (partId && pct >= 80 && !scrollMarkedParts.has(partId)) {
      if (Date.now() - state.lastPartChangeAt < NAVIGATION_COOLDOWN_MS) return;
      if (scrollCompleteDebounce) clearTimeout(scrollCompleteDebounce);
      scrollCompleteDebounce = setTimeout(() => {
        scrollCompleteDebounce = null;
        scrollMarkedParts.add(partId);
        markSectionComplete(partId);
      }, 500);
    }
  }

  const bar = $('reading-progress-bar');
  const main = $('project-main');
  if (!bar || !main) return;

  main.addEventListener('scroll', handleScrollForProgress, { passive: true });
  window.addEventListener('scroll', handleScrollForProgress, { passive: true });
}

function initSidebarMobile() {
  const sidebar = $('project-sidebar');
  const overlay = $('sidebar-overlay');
  const openBtn = $('btn-sidebar-open');

  if (!sidebar || !overlay || !openBtn) return;

  openBtn.addEventListener('click', () => {
    sidebar.classList.add('open');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
  });

  overlay.addEventListener('click', closeMobileSidebar);

  sidebar.addEventListener('click', (e) => {
    if (e.target.closest('.sidebar-part') && window.innerWidth <= 768) {
      closeMobileSidebar();
    }
  });

  function closeMobileSidebar() {
    sidebar.classList.remove('open');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
  }
}

function initSidebarCollapse() {
  const sidebar = $('project-sidebar');
  const collapseBtn = $('btn-sidebar-collapse');
  const expandBtn = $('btn-sidebar-expand');
  const layout = document.querySelector('.project-layout');

  if (!sidebar || !collapseBtn) return;

  function toggleSidebar() {
    const collapsed = sidebar.classList.toggle('collapsed');
    collapseBtn.style.transform = collapsed ? 'rotate(180deg)' : '';
    if (layout) layout.classList.toggle('sidebar-hidden', collapsed);
  }

  collapseBtn.addEventListener('click', toggleSidebar);
  if (expandBtn) expandBtn.addEventListener('click', toggleSidebar);
}

function initPartNavigation() {
  const prevBtn = $('btn-part-prev');
  const nextBtn = $('btn-part-next');

  if (!prevBtn || !nextBtn) return;

  prevBtn.addEventListener('click', () => navigateToPart(-1));
  nextBtn.addEventListener('click', () => navigateToPart(1));
}

function navigateToPart(delta) {
  const partes = state.currentProject?.segmentation?.partes;
  if (!partes) return;
  const idx = partes.findIndex(p => p.numero === state.currentPartId);
  if (idx === -1) return;
  const next = partes[idx + delta];
  if (next && window.pushRoute) {
    if (delta === 1 && state.currentPartId) {
      markSectionComplete(state.currentPartId);
    }
    window.pushRoute({
      view: 'project',
      projectId: state.currentProjectId,
      partId: next.numero,
      tab: state.activeTab,
    });
  }
}

function initCopyLink() {
  const btn = $('btn-copy-link');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    if (!state.currentProjectId || !state.currentPartId) return;
    const url = location.origin + location.pathname + (typeof window.buildHash === 'function'
      ? window.buildHash({
          view: 'project',
          projectId: state.currentProjectId,
          partId: state.currentPartId,
          tab: state.activeTab,
        })
      : location.hash || '#/');
    try {
      await navigator.clipboard.writeText(url);
      toast('Enlace copiado al portapapeles', 'success');
    } catch (_) {
      toast('No se pudo copiar el enlace', 'error');
    }
  });
}

function initToggleComplete() {
  const btn = $('btn-toggle-complete');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    if (!state.currentProjectId || !state.currentPartId) return;
    const isRead = btn.dataset.completed === 'true';
    await toggleSectionComplete(state.currentPartId, !isRead);
  });
}

function initPartActionsOverflow() {
  const overflow = $('part-actions-overflow');
  if (!overflow) return;

  overflow.querySelectorAll('.part-action-item').forEach((item) => {
    item.addEventListener('click', () => {
      const targetId = item.dataset.trigger;
      const target = targetId ? $(targetId) : null;
      if (target) {
        target.click();
        overflow.removeAttribute('open');
      }
    });
  });

  document.addEventListener('click', (e) => {
    if (overflow.open && !overflow.contains(e.target)) {
      overflow.removeAttribute('open');
    }
  });
}

function initDescriptionExpand() {
  const btn = $('btn-description-expand');
  const wrap = document.querySelector('.part-description-wrap');
  const desc = $('content-part-description');
  if (!btn || !wrap || !desc) return;

  btn.addEventListener('click', () => {
    const expanded = wrap.classList.toggle('expanded');
    btn.textContent = expanded ? 'Ver menos' : 'Ver más';
    btn.setAttribute('aria-label', expanded ? 'Ver menos' : 'Ver más');
  });
}

function bootstrap() {
  setViewChangeCallback(saveViewState);

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      if (state.currentProjectId && state.currentPartId && window.pushRoute) {
        window.pushRoute({
          view: 'project',
          projectId: state.currentProjectId,
          partId: state.currentPartId,
          tab,
        });
      } else {
        activateTab(tab);
      }
    });
  });

  $('btn-home-from-projects').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'landing' });
  });

  $('btn-new-project').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'landing' });
  });
  $('btn-new-project-2').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'landing' });
  });

  $('btn-export-projects').addEventListener('click', exportProjectsBackup);
  $('import-projects-input').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) importProjectsBackup(file);
    e.target.value = '';
  });

  $('btn-back-to-projects').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'projects' });
  });

  $('btn-delete-project').addEventListener('click', async () => {
    if (!state.currentProjectId) return;
    if (!confirm('¿Eliminar este proyecto y todo su contenido? Esta acción no se puede deshacer.')) return;
    try {
      await api(`/api/projects/${state.currentProjectId}`, { method: 'DELETE' });
      invalidateProjectsCache();
      const remaining = loadLocalBackup(state.user?.id).projects.filter((p) => p.id !== state.currentProjectId);
      syncProjectsToLocal(remaining, state.user?.id);
      toast('Proyecto eliminado.', 'success');
      if (state.processingSSE) { state.processingSSE.close(); state.processingSSE = null; }
      if (window.pushRoute) window.pushRoute({ view: 'projects' });
    } catch (err) {
      toast('Error al eliminar: ' + err.message, 'error');
    }
  });

  initSettings();
  initVisibilityHandling();
  initObsidianExport();
  initFullProjectExport();
  initReadingProgressBar();
  initSidebarMobile();
  initSidebarCollapse();
  initPartNavigation();
  initCopyLink();
  initToggleComplete();
  initPartActionsOverflow();
  initDescriptionExpand();
  initApp();
}

import { setSaveViewStateCallback } from './projectView.js';

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    setSaveViewStateCallback(saveViewState);
    bootstrap();
  });
} else {
  setSaveViewStateCallback(saveViewState);
  bootstrap();
}
