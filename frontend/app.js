/* ============================================================
   EXPLAINER — Frontend SPA con Supabase Auth
   ============================================================ */

const SUPABASE_URL = window.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || '';
const supabaseClient = (SUPABASE_URL && SUPABASE_ANON_KEY && window.supabase)
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;

// ── State ──────────────────────────────────────────────────
const state = {
  currentProjectId: null,
  currentProject: null,
  currentPartId: null,
  activeTab: 'explicacion',
  processingSSE: null,              // EventSource activo
  sseProjectId: null,               // projectId al que está conectado el SSE
  sseReconnectAttempts: 0,
  sseLastEventAt: 0,
  ssePausedByVisibility: false,     // true cuando pestaña oculta
  pollProjectsInterval: null,
  pollCurrentProjectInterval: null,
  hasApiKey: false,
  session: null,
  user: null,
  previousUserId: null,             // Para detectar cambios de usuario vs refresh de sesión
};

const SSE_RECONNECT_MAX = 5;
const SSE_RECONNECT_DELAY_MS = 2000;
const POLL_PROJECTS_MS = 6000;
const POLL_CURRENT_IF_IDLE_MS = 12000;
const VISIBILITY_RECONNECT_DELAY_MS = 800;

const LOCAL_BACKUP_KEY = 'explainer.projects.backup.v1';
const SESSION_VIEW_KEY = 'explainer.current_view.v1';

function loadLocalBackup() {
  try {
    const raw = localStorage.getItem(LOCAL_BACKUP_KEY);
    if (!raw) return { version: 1, projects: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.projects)) return { version: 1, projects: [] };
    return parsed;
  } catch (_) {
    return { version: 1, projects: [] };
  }
}

function saveLocalBackup(payload) {
  const safePayload = {
    version: 1,
    exported_at: new Date().toISOString(),
    projects: Array.isArray(payload?.projects) ? payload.projects : [],
  };
  localStorage.setItem(LOCAL_BACKUP_KEY, JSON.stringify(safePayload));
}

function mergeProjects(serverProjects = [], localProjects = []) {
  const byId = new Map();
  [...localProjects, ...serverProjects].forEach((project) => {
    if (!project || !project.id) return;
    const current = byId.get(project.id);
    if (!current) {
      byId.set(project.id, project);
      return;
    }

    const currentUpdated = new Date(current.updated_at || current.created_at || 0).getTime();
    const candidateUpdated = new Date(project.updated_at || project.created_at || 0).getTime();
    byId.set(project.id, candidateUpdated >= currentUpdated ? project : current);
  });

  return Array.from(byId.values()).sort((a, b) =>
    new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
  );
}

function syncProjectsToLocal(projects) {
  saveLocalBackup({ projects });
}

function getCachedProject(projectId) {
  const backup = loadLocalBackup();
  return backup.projects.find((p) => p.id === projectId) || null;
}

function payloadToJsonFile(payload, filename = 'explainer-sync.json') {
  return new File([JSON.stringify(payload, null, 2)], filename, { type: 'application/json' });
}

async function rehydrateProjectToServer(project) {
  const fd = new FormData();
  fd.append('file', payloadToJsonFile({ version: 1, projects: [project] }));
  await api('/api/projects/import', { method: 'POST', body: fd });
}


// ── Helpers ────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const show = (el) => el && el.classList.remove('hidden');
const hide = (el) => el && el.classList.add('hidden');

function showView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  $(viewId).classList.add('active');
  // Save view state for tab restore
  saveViewState();
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function statusLabel(status) {
  const map = {
    pending: 'Pendiente', uploading: 'Subiendo', segmenting: 'Segmentando',
    processing: 'Procesando', completed: 'Completado', error: 'Error',
  };
  return map[status] || status;
}

function formatIconForResource(format) {
  const map = {
    libro_texto_articulo: '📖',
    documental_pelicula_serie: '🎬',
    sitio_web_recurso_digital: '🌐',
    podcast_audio: '🎧',
    curso_conferencia_material_educativo: '🎓',
  };
  return map[format] || '📌';
}

// ── Toast ──────────────────────────────────────────────────
function toast(msg, type = '') {
  const container = $('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 3000);
  setTimeout(() => el.remove(), 3400);
}

// ── API ────────────────────────────────────────────────────
const API_BASE_URL = window.EXPLAINER_API_BASE_URL || '';

function getAccessToken() {
  return state.session?.access_token || null;
}

async function api(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers = { ...(options.headers || {}) };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    if (supabaseClient) {
      await supabaseClient.auth.signOut();
      state.session = null;
      state.user = null;
      showView('view-auth');
      toast('Sesión expirada. Inicia sesión de nuevo.', 'error');
    }
    const err = await res.json().catch(() => ({ detail: 'No autorizado' }));
    throw new Error(err.detail || 'No autorizado');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Error desconocido' }));
    throw new Error(err.detail || 'Error en el servidor');
  }

  return res.json();
}

// ── ROUTER ─────────────────────────────────────────────────
let router = null;

function navigateFromRoute(route) {
  if (!route) return;

  if (route.view === 'landing') {
    showView('view-landing');
    initLanding();
    refreshApiKeyStatus();
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
        if (typeof replaceRoute === 'function') replaceRoute({ view: 'project', projectId });
        openProjectView(projectId);
        return;
      }
      restoreProjectView(projectId, partId, tab).catch(() => {});
      return;
    }

    openProjectView(route.projectId);
  }
}

// ── APP INIT ───────────────────────────────────────────────
async function initApp() {
  if (!supabaseClient) {
    showView('view-auth');
    document.querySelector('.auth-subtitle').textContent = 'Supabase no configurado. Define EXPLAINER_SUPABASE_URL y EXPLAINER_SUPABASE_ANON_KEY.';
    initAuth();
    return;
  }

  const { data: { session } } = await supabaseClient.auth.getSession();
  state.session = session;
  state.user = session?.user ?? null;

  if (typeof initRouter === 'function') {
    router = initRouter(navigateFromRoute);
  }

  supabaseClient.auth.onAuthStateChange((_event, newSession) => {
    const prevUserId = state.user?.id ?? null;
    const newUserId = newSession?.user?.id ?? null;

    // Update state
    state.session = newSession;
    state.user = newSession?.user ?? null;

    // Smart navigation: only redirect on meaningful state changes
    if (!prevUserId && newUserId) {
      // Fresh login (was logged out, now logged in) — navigate from URL if present
      const route = typeof parseRoute === 'function' ? parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        navigateFromRoute(route);
      } else {
        if (router) router.pushRoute({ view: 'landing' });
        showView('view-landing');
        initLanding();
      }
      refreshApiKeyStatus();
    } else if (prevUserId && !newUserId) {
      // Logout (was logged in, now logged out)
      // Close SSE and clean up
      if (state.processingSSE) {
        state.processingSSE.close();
        state.processingSSE = null;
        state.sseProjectId = null;
      }
      stopPolling();
      showView('view-auth');
    } else if (prevUserId && newUserId && prevUserId !== newUserId) {
      // User switched (different user logged in)
      // Clear project state and close SSE
      if (state.processingSSE) {
        state.processingSSE.close();
        state.processingSSE = null;
        state.sseProjectId = null;
      }
      stopPolling();
      state.currentProjectId = null;
      state.currentProject = null;
      state.currentPartId = null;
      // Clear session storage for previous user
      sessionStorage.removeItem('explainer.viewState');
      showView('view-landing');
      initLanding();
      refreshApiKeyStatus();
    } else if (newUserId) {
      // Session continued or refreshed - same user
      // DO NOT navigate - let user stay on current view
      // Just refresh API key status in background
      refreshApiKeyStatus();
    }
  });

  if (!state.session) {
    showView('view-auth');
    initAuth();
    return;
  }

  // 1. URL takes precedence — if hash has a route, navigate there
  const route = typeof parseRoute === 'function' ? parseRoute() : null;
  if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
    await navigateFromRoute(route);
    return;
  }

  // 2. Fallback: restore from sessionStorage (tab discard/recovery)
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
          if (typeof replaceRoute === 'function') {
            replaceRoute({
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
          if (typeof replaceRoute === 'function') replaceRoute({ view: 'projects' });
          return;
        } else if (viewState.view === 'view-landing') {
          showView('view-landing');
          initLanding();
          await refreshApiKeyStatus();
          return;
        }
      }
    } catch (_) {
      // If parsing fails, fall through to default landing
    }
  }

  // 3. Default: go to landing
  if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
  showView('view-landing');
  initLanding();
  await refreshApiKeyStatus();
}

// Helper to restore project view on init
async function restoreProjectView(projectId, partId, activeTab) {
  showView('view-project');
  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const refreshed = mergeProjects([project], loadLocalBackup().projects);
    syncProjectsToLocal(refreshed);

    renderProjectView(project);

    // Restore part selection if specified
    if (partId && project.segmentation?.partes?.some(p => p.numero === partId)) {
      state.currentPartId = partId;
      state.activeTab = activeTab;
      selectPart(partId);
      activateTab(activeTab);
    } else if (partId) {
      // Invalid partId — redirect to project overview
      if (typeof replaceRoute === 'function') replaceRoute({ view: 'project', projectId });
    }

    // Restart SSE if project is still processing
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
    if (typeof replaceRoute === 'function') replaceRoute({ view: 'projects' });
    toast('No se pudo restaurar la vista anterior', 'error');
  }
}

// Save current view state to sessionStorage
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

async function refreshApiKeyStatus() {
  try {
    const status = await api('/api/settings/api-key/status');
    state.hasApiKey = Boolean(status.has_api_key);
  } catch (_) {
    state.hasApiKey = false;
  }
  if (typeof updateApiKeyUI === 'function') updateApiKeyUI();
}

// ── SETTINGS / API KEY ─────────────────────────────────────
function initSettings() {
  // Inicializa el modal de settings.
  // Open buttons
  $('btn-settings').addEventListener('click', showSettings);
  $('btn-settings-projects').addEventListener('click', showSettings);
  $('btn-configure-api-key').addEventListener('click', showSettings);

  // Close button
  $('btn-close-settings').addEventListener('click', hideSettings);

  // Close on overlay click
  $('modal-settings').addEventListener('click', (e) => {
    if (e.target === $('modal-settings')) {
      hideSettings();
    }
  });

  // API Key form
  $('form-api-key').addEventListener('submit', async (e) => {
    e.preventDefault();
    const apiKey = $('api-key-input').value.trim();

    if (!apiKey) {
      $('api-key-error').textContent = 'Ingresa una API key';
      return;
    }

    const btn = $('btn-save-api-key');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('.btn-text');

    btn.disabled = true;
    show(spinner);
    btnText.textContent = 'Guardando...';
    $('api-key-error').textContent = '';
    $('api-key-success').textContent = '';

    try {
      const formData = new FormData();
      formData.append('api_key', apiKey);

      await api('/api/settings/api-key', {
        method: 'POST',
        body: formData,
      });

      state.hasApiKey = true;
      $('api-key-input').value = '';
      $('api-key-success').textContent = 'API key guardada correctamente';
      updateApiKeyUI();
      toast('API key guardada', 'success');

    } catch (err) {
      $('api-key-error').textContent = err.message;
    } finally {
      btn.disabled = false;
      hide(spinner);
      btnText.textContent = 'Guardar API Key';
    }
  });

  // Delete API Key
  $('btn-delete-api-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key guardada?')) return;

    try {
      await api('/api/settings/api-key', { method: 'DELETE' });
      state.hasApiKey = false;
      updateApiKeyUI();
      toast('API key eliminada', 'success');
    } catch (err) {
      $('api-key-error').textContent = err.message;
    }
  });
}

async function showSettings() {
  $('settings-email').textContent = state.user?.email || '—';
  updateApiKeyUI();
  show($('modal-settings'));
}

// ── AUTH (login / register) ───────────────────────────────
function initAuth() {
  const formLogin = $('form-login');
  const formRegister = $('form-register');
  const loginError = $('auth-login-error');
  const registerError = $('auth-register-error');

  document.querySelectorAll('.auth-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.authTab;
      document.querySelectorAll('.auth-tab').forEach((t) => t.classList.toggle('active', t.dataset.authTab === target));
      if (target === 'login') {
        show(formLogin);
        hide(formRegister);
        loginError.textContent = '';
      } else {
        hide(formLogin);
        show(formRegister);
        registerError.textContent = '';
      }
    });
  });

  formLogin.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.textContent = '';
    const email = $('login-email').value.trim();
    const password = $('login-password').value;
    if (!email || !password) {
      loginError.textContent = 'Completa email y contraseña';
      return;
    }
    const btn = $('btn-login');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = 'Entrando...';
    try {
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
      if (error) throw error;
      state.session = data.session;
      state.user = data.user;
      const route = typeof parseRoute === 'function' ? parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        navigateFromRoute(route);
      } else {
        if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
        showView('view-landing');
        initLanding();
      }
      await refreshApiKeyStatus();
      toast('Sesión iniciada', 'success');
    } catch (err) {
      loginError.textContent = err.message || 'Error al iniciar sesión';
    } finally {
      btn.disabled = false;
      btn.querySelector('.btn-text').textContent = 'Iniciar sesión';
    }
  });

  formRegister.addEventListener('submit', async (e) => {
    e.preventDefault();
    registerError.textContent = '';
    const email = $('register-email').value.trim();
    const password = $('register-password').value;
    const confirm = $('register-password-confirm').value;
    if (!email || !password) {
      registerError.textContent = 'Completa email y contraseña';
      return;
    }
    if (password !== confirm) {
      registerError.textContent = 'Las contraseñas no coinciden';
      return;
    }
    if (password.length < 6) {
      registerError.textContent = 'La contraseña debe tener al menos 6 caracteres';
      return;
    }
    const btn = $('btn-register');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = 'Creando cuenta...';
    try {
      const { data, error } = await supabaseClient.auth.signUp({ email, password });
      if (error) throw error;
      state.session = data.session;
      state.user = data.user;
      const route = typeof parseRoute === 'function' ? parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        navigateFromRoute(route);
      } else {
        if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
        showView('view-landing');
        initLanding();
      }
      await refreshApiKeyStatus();
      toast('Cuenta creada. Ya puedes usar Explainer.', 'success');
    } catch (err) {
      registerError.textContent = err.message || 'Error al registrarse';
    } finally {
      btn.disabled = false;
      btn.querySelector('.btn-text').textContent = 'Crear cuenta';
    }
  });

  $('btn-logout').addEventListener('click', async () => {
    if (state.processingSSE) {
      state.processingSSE.close();
      state.processingSSE = null;
    }
    await supabaseClient.auth.signOut();
    state.session = null;
    state.user = null;
    hide($('modal-settings'));
    showView('view-auth');
    toast('Sesión cerrada', 'success');
  });
}

function hideSettings() {
  hide($('modal-settings'));
  $('api-key-error').textContent = '';
  $('api-key-success').textContent = '';
  $('api-key-input').value = '';
}

function updateApiKeyUI() {
  // Actualiza la UI según el estado de la API key.
  if (state.hasApiKey) {
    hide($('api-key-not-set'));
    show($('api-key-set'));
    $('btn-delete-api-key').style.display = 'inline-block';
  } else {
    show($('api-key-not-set'));
    hide($('api-key-set'));
    $('btn-delete-api-key').style.display = 'none';
  }

  // Update warning in landing
  if (state.hasApiKey) {
    hide($('api-key-warning'));
  } else {
    show($('api-key-warning'));
  }
}

// ── LANDING VIEW ───────────────────────────────────────────
let selectedFile = null;
let currentSourceType = 'pdf'; // 'pdf' or 'youtube'
let selectedModel = 'gemini-3-flash-preview'; // 'gemini-3-flash-preview' or 'gemini-3.1-pro-preview'

function extractYouTubeVideoId(url) {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
    /^([a-zA-Z0-9_-]{11})$/
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

function isValidYouTubeUrl(url) {
  if (!url || url.trim().length === 0) return false;
  return extractYouTubeVideoId(url) !== null;
}

function initLanding() {
  updateApiKeyUI();

  const zone = $('upload-zone');
  const fileInput = $('file-input');
  const btnUpload = $('btn-upload');
  const nameInput = $('project-name');
  const descInput = $('project-description');
  const youtubeUrlInput = $('youtube-url');

  // Source tabs handling
  const tabPdf = $('tab-pdf');
  const tabYoutube = $('tab-youtube');
  const panelPdf = $('panel-pdf');
  const panelYoutube = $('panel-youtube');

  function switchSourceType(type) {
    currentSourceType = type;

    // Update tab styles
    tabPdf.classList.toggle('active', type === 'pdf');
    tabYoutube.classList.toggle('active', type === 'youtube');

    // Show/hide panels
    if (type === 'pdf') {
      show(panelPdf);
      hide(panelYoutube);
    } else {
      hide(panelPdf);
      show(panelYoutube);
    }

    // Clear errors
    $('upload-error').textContent = '';
    $('youtube-url-error').textContent = '';
    hide($('youtube-url-error'));

    validateForm();
  }

  tabPdf.addEventListener('click', () => switchSourceType('pdf'));
  tabYoutube.addEventListener('click', () => switchSourceType('youtube'));

  function checkReady() {
    const hasName = nameInput.value.trim();

    if (currentSourceType === 'pdf') {
      const ready = selectedFile && hasName;
      btnUpload.disabled = !ready;
    } else {
      const url = youtubeUrlInput.value.trim();
      const ready = isValidYouTubeUrl(url) && hasName;
      btnUpload.disabled = !ready;
    }
  }

  // PDF upload handling
  zone.addEventListener('click', () => fileInput.click());
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f && f.type === 'application/pdf') setFile(f);
    else toast('Por favor, sube un archivo PDF.', 'error');
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  $('btn-remove-file').addEventListener('click', (e) => {
    e.stopPropagation();
    clearFile();
  });

  // YouTube URL handling
  youtubeUrlInput.addEventListener('input', () => {
    const url = youtubeUrlInput.value.trim();
    const urlError = $('youtube-url-error');

    if (url && !isValidYouTubeUrl(url)) {
      urlError.textContent = 'URL de YouTube inválida. Usa formato: https://www.youtube.com/watch?v=VIDEO_ID';
      show(urlError);
    } else {
      urlError.textContent = '';
      hide(urlError);
    }
    checkReady();
  });

  nameInput.addEventListener('input', checkReady);
  descInput.addEventListener('input', checkReady);

  document.querySelectorAll('input[name="model-choice"]').forEach(radio => {
    radio.addEventListener('change', (e) => { selectedModel = e.target.value; });
  });

  btnUpload.addEventListener('click', handleUpload);
  $('btn-go-projects').addEventListener('click', () => {
    if (typeof pushRoute === 'function') pushRoute({ view: 'projects' });
  });
}

function setFile(f) {
  selectedFile = f;
  $('file-name-display').textContent = f.name;
  $('file-size-display').textContent = formatBytes(f.size);
  hide($('upload-zone'));
  show($('file-preview'));
  validateForm();
}

function clearFile() {
  selectedFile = null;
  $('file-input').value = '';
  show($('upload-zone'));
  hide($('file-preview'));
  validateForm();
}

function validateForm() {
  const nameInput = $('project-name');
  const youtubeUrlInput = $('youtube-url');
  const hasName = nameInput.value.trim();

  if (currentSourceType === 'pdf') {
    const ready = selectedFile && hasName;
    $('btn-upload').disabled = !ready;
  } else {
    const url = youtubeUrlInput.value.trim();
    const ready = isValidYouTubeUrl(url) && hasName;
    $('btn-upload').disabled = !ready;
  }
}

async function handleUpload() {
  const name = $('project-name').value.trim();
  const description = $('project-description').value.trim();
  const errEl = $('upload-error');
  errEl.textContent = '';

  // Verificar que tenga API key
  if (!state.hasApiKey) {
    errEl.textContent = 'Necesitas configurar tu API key de Gemini primero. Ve a Ajustes.';
    showSettings();
    return;
  }

  const btn = $('btn-upload');
  btn.disabled = true;

  try {
    const fd = new FormData();
    fd.append('name', name);
    fd.append('description', description);

    if (currentSourceType === 'pdf') {
      if (!selectedFile) {
        errEl.textContent = 'Selecciona un archivo PDF.';
        btn.disabled = false;
        return;
      }
      btn.querySelector('.btn-text').textContent = 'Creando proyecto...';
      fd.append('file', selectedFile);
    } else {
      const youtubeUrl = $('youtube-url').value.trim();
      if (!isValidYouTubeUrl(youtubeUrl)) {
        errEl.textContent = 'URL de YouTube inválida.';
        btn.disabled = false;
        return;
      }
      btn.querySelector('.btn-text').textContent = 'Creando proyecto...';
      fd.append('youtube_url', youtubeUrl);
    }

    const project = await api('/api/projects', { method: 'POST', body: fd });
    const mergedAfterCreate = mergeProjects([project], loadLocalBackup().projects);
    syncProjectsToLocal(mergedAfterCreate);
    toast('Proyecto creado. Iniciando análisis...', 'success');

    // Reset form
    clearFile();
    $('project-name').value = '';
    $('project-description').value = '';
    $('youtube-url').value = '';
    document.querySelectorAll('input[name="model-choice"]').forEach(r => {
      r.checked = r.value === 'gemini-3-flash-preview';
    });
    const modelForProcess = selectedModel;
    selectedModel = 'gemini-3-flash-preview';

    // Start processing
    await api(`/api/projects/${project.id}/process?model=${encodeURIComponent(modelForProcess)}`, { method: 'POST' });

    // Navigate to project (router will trigger openProjectView via hashchange)
    if (typeof pushRoute === 'function') pushRoute({ view: 'project', projectId: project.id });

  } catch (err) {
    errEl.textContent = err.message;
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = 'Iniciar análisis';
  }
}

// ── PROJECTS LIST VIEW ─────────────────────────────────────
async function loadProjectsView() {
  showView('view-projects');
  const localProjects = loadLocalBackup().projects;

  try {
    const serverProjects = await api('/api/projects');
    const merged = mergeProjects(serverProjects, localProjects);
    syncProjectsToLocal(merged);
    renderProjectsList(merged);
  } catch (err) {
    if (localProjects.length > 0) {
      renderProjectsList(localProjects);
      toast('Servidor no disponible. Mostrando copia local de tus proyectos.', 'error');
      return;
    }
    toast('Error cargando proyectos: ' + err.message, 'error');
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
      if (typeof pushRoute === 'function') pushRoute({ view: 'project', projectId: card.dataset.id });
    });
  });

  const hasActive = projects.some((p) => ['pending', 'uploading', 'segmenting', 'processing'].includes(p.status));
  if (hasActive) startProjectsListPolling();
  else stopPolling();
}

function updateUsageUI(usage) {
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

  // Live cost in proc-stage banner
  if ($('proc-cost-badge')) $('proc-cost-badge').textContent = `$${cost.toFixed(4)}`;

  const card = $('project-usage-card');
  if (card) {
    card.classList.remove('pulse-highlight');
    void card.offsetWidth;
    card.classList.add('pulse-highlight');
  }
}

// ── PROJECT DETAIL VIEW ────────────────────────────────────
async function openProjectView(projectId) {
  state.currentProjectId = projectId;
  state.currentPartId = null;
  state.activeTab = 'explicacion';

  showView('view-project');

  try {
    const project = await api(`/api/projects/${projectId}`);
    state.currentProject = project;

    const refreshed = mergeProjects([project], loadLocalBackup().projects);
    syncProjectsToLocal(refreshed);

    renderProjectView(project);

    const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
    if (isProcessing) {
      // Si ya hay SSE para este proyecto, no recrear; si es de otro, cerrar y crear nuevo
      if (state.sseProjectId === projectId && state.processingSSE) {
        // Reconectar si estaba cerrado por error
        if (state.processingSSE.readyState === EventSource.CLOSED) {
          startSSE(projectId, { forceReconnect: true });
        }
        // Sincronizar UI con estado actual
        syncProcessingUIWithState();
      } else {
        closeSSEIfDifferent(projectId);
        startSSE(projectId);
      }
    } else {
      // Proyecto completado: cerrar SSE si estaba abierto para este proyecto
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

function syncProcessingUIWithState() {
  const project = state.currentProject;
  if (!project) return;
  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
  if (isProcessing) {
    showProcessingIndicator(project.status);
    // Restore parts grid if segmentation already happened
    if (project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0) {
      renderProcPartsGrid(project);
    }
  } else {
    hideProcessingIndicator();
  }
  renderSidebarNav(project);
  updateUsageUI(project.usage);
}

function renderProjectView(project) {
  $('sidebar-project-name').textContent = project.name;
  $('sidebar-status').innerHTML = `<span class="card-status-badge status-${project.status}">${statusLabel(project.status)}</span>`;

  renderSidebarNav(project);
  updateUsageUI(project.usage);
  updateMobileHeader();

  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);

  if (!state.currentPartId) {
    hide($('part-content'));
    if (isProcessing) {
      // Show immersive proc-stage instead of the plain welcome message
      showProcessingIndicator(project.status);
      hide($('main-welcome'));
      // If segmentation data already exists (e.g. re-opening a processing project), show the grid immediately
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


function renderSidebarNav(project) {
  const nav = $('sidebar-nav');
  nav.innerHTML = '';

  if (!project.segmentation || !project.segmentation.partes) return;

  const projectId = state.currentProjectId;

  project.segmentation.partes.forEach(parte => {
    const partId = parte.numero;
    const contenido = project.partes_contenido ? project.partes_contenido[String(partId)] : null;
    const status = contenido ? contenido.status : 'pending';

    const dotClass = {
      pending: 'dot-pending',
      processing: 'dot-processing',
      completed: 'dot-completed',
      error: 'dot-error',
    }[status] || 'dot-pending';

    const href = typeof buildHash === 'function' && projectId
      ? buildHash({
          view: 'project',
          projectId,
          partId,
          tab: state.activeTab,
        })
      : '#';

    const el = document.createElement('a');
    el.className = `sidebar-part${state.currentPartId === partId ? ' active' : ''}`;
    el.dataset.partId = partId;
    el.href = href;
    el.innerHTML = `
      <span class="part-num">P${partId}</span>
      <span class="part-label">${escHtml(parte.titulo)}</span>
      <span class="part-status-dot ${dotClass}"></span>
    `;
    nav.appendChild(el);
  });
}

// ═══════════════════════════════════════════════════════════
//  PROC STAGE — The Scholarly Forge loading experience
//  Non-blocking, real-time, section-by-section reveal.
// ═══════════════════════════════════════════════════════════

/**
 * Show the proc-stage loading screen and set the correct phase.
 * @param {string} status — project status string (uploading/segmenting/processing/pending)
 */
function showProcessingIndicator(status) {
  const stage = $('proc-stage');
  if (!stage) return;
  stage.classList.remove('hidden');
  setProcPhase(status);
}

/** Hide the proc-stage loading screen. */
function hideProcessingIndicator() {
  const stage = $('proc-stage');
  if (stage) stage.classList.add('hidden');
}

/**
 * Update the phase banner + timeline to reflect the current processing phase.
 * @param {string} status
 */
function setProcPhase(status) {
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
  if (orb) {
    orb.className = 'proc-phase-orb ' + (orbMap[status] || '');
  }
  if (hint) hint.textContent = subMap[status] || 'Procesando...';

  // --- Timeline step states ---
  // upload → pstep-upload
  // segmenting → pstep-upload done, pstep-segment active
  // processing → pstep-upload done, pstep-segment done, pstep-generate active
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

/**
 * Render the parts grid from project segmentation data.
 * Shows grid, hides the forge animation, adds one card per section.
 * @param {object} project
 */
function renderProcPartsGrid(project) {
  const grid = $('proc-parts-grid');
  const forge = $('proc-forge');
  if (!grid) return;

  const partes = project.segmentation?.partes || [];
  const contenido = project.partes_contenido || {};

  // Build a staggered delay per card for the cascade entrance
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
        if (typeof pushRoute === 'function') {
          pushRoute({
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

  // Show grid, hide forge animation
  grid.classList.remove('hidden');
  if (forge) forge.classList.add('hidden');
}

/**
 * Light up an agent badge on a specific part card when agent_completed fires.
 * @param {number} partId
 * @param {string} agentName  — 'explainer' | 'recorrido' | 'resources'
 */
function updateProcPartCard(partId, agentName) {
  const card = document.querySelector(`#proc-parts-grid .proc-part-card[data-part-id="${partId}"]`);
  if (!card) return;

  // Activate the card border (processing state)
  card.classList.remove('pending');
  card.classList.add('processing');

  // Light up the specific agent badge
  const badge = card.querySelector(`.proc-agent-badge[data-agent="${agentName}"]`);
  if (badge) {
    badge.classList.remove('active');
    badge.classList.add('done');
  }
}

/**
 * Mark a part card as fully completed: green border + click-to-open.
 * @param {number} partId
 */
function completeProcPartCard(partId) {
  const card = document.querySelector(`#proc-parts-grid .proc-part-card[data-part-id="${partId}"]`);
  if (!card) return;

  card.classList.remove('pending', 'processing');
  card.classList.add('completed');

  // All badges should be done
  card.querySelectorAll('.proc-agent-badge').forEach(b => {
    b.classList.remove('active');
    b.classList.add('done');
  });

  // Make clickable
  card.style.cursor = 'pointer';
  card.addEventListener('click', () => {
    if (typeof pushRoute === 'function') {
      pushRoute({
        view: 'project',
        projectId: state.currentProjectId,
        partId,
        tab: 'explicacion',
      });
    }
  });
}

function selectPart(partId) {
  state.currentPartId = partId;

  document.querySelectorAll('.sidebar-part').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.partId) === partId);
  });

  // Hide the proc-stage and the plain welcome, show reading content
  hide($('proc-stage'));
  hide($('main-welcome'));
  show($('part-content'));

  const project = state.currentProject;
  const parte = project.segmentation.partes.find(p => p.numero === partId);
  const contenido = project.partes_contenido ? project.partes_contenido[String(partId)] : null;

  $('content-part-number').textContent = `Sección ${partId}`;
  $('content-part-title').textContent = parte.titulo;
  $('content-part-description').textContent = parte.contenido;
  $('content-part-badges').innerHTML = `
    <span class="badge">${parte.extension_estimada}</span>
    <span class="badge">Complejidad: ${parte.complejidad}</span>
    <span class="badge">↑ ${parte.expansion_prevista}</span>
  `;

  renderTab('explicacion', contenido);
  renderTab('recorrido', contenido);
  renderTab('recursos', contenido);

  activateTab(state.activeTab);

  // Scroll reading area back to top
  const main = $('project-main');
  if (main) main.scrollTo({ top: 0, behavior: 'smooth' });

  // Update toolbar & mobile header
  updateReadingToolbar();
  updateMobileHeader();

  saveViewState();
}

function renderTab(tabName, contenido) {
  const panelId = `panel-${tabName}`;
  const loadingId = `loading-${tabName}`;
  const contentId = `content-${tabName}`;
  const panel = $(panelId);
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

function activateTab(tabName) {
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

// ── Renderers ──────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function nl2p(str) {
  if (!str) return '';
  return str.split(/\n\n+/)
    .map(p => p.trim())
    .filter(Boolean)
    .map(p => `<p>${escHtml(p)}</p>`)
    .join('');
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

// ── Page Visibility API ───────────────────────────────────
// Mantiene SSE activo incluso al cambiar de pestaña; reconecta rápido al volver
function initVisibilityHandling() {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      state.ssePausedByVisibility = true;
      // NO cerramos SSE, solo marcamos pausa. Al volver reconectamos si es necesario.
    } else {
      const wasPaused = state.ssePausedByVisibility;
      state.ssePausedByVisibility = false;
      if (wasPaused && state.sseProjectId && state.currentProjectId === state.sseProjectId) {
        // Reconectar rápidamente si el SSE estaba idle o cerrado
        const idle = Date.now() - state.sseLastEventAt > 5000;
        const closed = !state.processingSSE || state.processingSSE.readyState === EventSource.CLOSED;
        if (idle || closed) {
          setTimeout(() => startSSE(state.sseProjectId, { forceReconnect: true }), VISIBILITY_RECONNECT_DELAY_MS);
        }
      }
    }
  });
}

// ── SSE (real-time) + polling fallback ──────────────────────
function stopPolling() {
  if (state.pollProjectsInterval) {
    clearInterval(state.pollProjectsInterval);
    state.pollProjectsInterval = null;
  }
  if (state.pollCurrentProjectInterval) {
    clearInterval(state.pollCurrentProjectInterval);
    state.pollCurrentProjectInterval = null;
  }
}

function closeSSEIfDifferent(projectId) {
  // Solo cierra SSE si es de OTRO proyecto; si es el mismo, mantenerlo
  if (state.processingSSE && state.sseProjectId !== projectId) {
    state.processingSSE.close();
    state.processingSSE = null;
    state.sseProjectId = null;
  }
}

function startProjectsListPolling() {
  stopPolling();
  state.pollProjectsInterval = setInterval(async () => {
    const view = document.querySelector('.view.active');
    if (!view || view.id !== 'view-projects') return;
    try {
      const serverProjects = await api('/api/projects');
      const localProjects = loadLocalBackup().projects;
      const merged = mergeProjects(serverProjects, localProjects);
      const hasActive = merged.some((p) => ['pending', 'uploading', 'segmenting', 'processing'].includes(p.status));
      syncProjectsToLocal(merged);
      renderProjectsList(merged);
      if (!hasActive && state.pollProjectsInterval) {
        clearInterval(state.pollProjectsInterval);
        state.pollProjectsInterval = null;
      }
    } catch (_) { /* ignore */ }
  }, POLL_PROJECTS_MS);
}

function startSSE(projectId, opts = {}) {
  // Si ya hay SSE para el mismo proyecto y no se fuerza reconexión, reutilizar
  if (state.processingSSE && state.sseProjectId === projectId && !opts.forceReconnect) {
    // Ya estamos conectados a este proyecto, solo actualizar UI
    syncProcessingUIWithState();
    return;
  }

  // Cerrar SSE anterior si es de otro proyecto
  if (state.processingSSE && state.sseProjectId !== projectId) {
    state.processingSSE.close();
  }

  state.sseProjectId = projectId;
  state.sseReconnectAttempts = 0;
  state.sseLastEventAt = Date.now();
  // Reset proc-stage to forge state (forge visible, grid hidden)
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
          // Render the parts grid now that we have segmentation data
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
          // Activate this card's visual state in proc-stage grid
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
          // Light up agent badge in the grid card
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
          // Golden reveal animation on the grid card
          completeProcPartCard(payload.part_id);
          // If this part is currently being viewed, refresh its content
          if (state.currentPartId === payload.part_id) {
            selectPart(payload.part_id);
          }
          break;
        }

        case 'completed':
          project.status = 'completed';
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-completed">Completado</span>`;
          // Update timeline to all-done and hide proc-stage after a brief moment
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
          hide($('processing-overlay'));
          pushStreamEvent('Error', payload.message || 'Error');
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
          hide($('processing-overlay'));
          toast('¡Análisis completo!', 'success');
          stopPolling();
        } else if (fresh.status === 'error') {
          hide($('processing-overlay'));
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



async function exportProjectsBackup() {
  try {
    const localProjects = loadLocalBackup().projects;
    let payload = { version: 1, exported_at: new Date().toISOString(), projects: localProjects };

    try {
      const serverPayload = await api('/api/projects/export');
      payload = {
        ...serverPayload,
        projects: mergeProjects(serverPayload.projects || [], localProjects),
      };
    } catch (_) {
      // Si el servidor falla, exportamos desde la copia local sin bloquear al usuario.
    }

    syncProjectsToLocal(payload.projects);

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `explainer-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Backup exportado', 'success');
  } catch (err) {
    toast('Error exportando backup: ' + err.message, 'error');
  }
}

async function importProjectsBackup(file) {
  try {
    const parsed = JSON.parse(await file.text());
    if (!parsed || !Array.isArray(parsed.projects)) {
      throw new Error('Formato inválido: el backup no contiene una lista de proyectos');
    }

    const localMerged = mergeProjects(parsed.projects, loadLocalBackup().projects);
    syncProjectsToLocal(localMerged);

    const fd = new FormData();
    fd.append('file', payloadToJsonFile(parsed, file.name || 'explainer-import.json'));

    const result = await api('/api/projects/import', { method: 'POST', body: fd });
    toast(`Importación completada: ${result.imported} importados, ${result.skipped} omitidos`, 'success');
    loadProjectsView();
  } catch (err) {
    toast('Error importando backup: ' + err.message, 'error');
  }
}
// ── OBSIDIAN EXPORT ────────────────────────────────────────

// ── Shared export utilities ─────────────────────────────────

/**
 * Converts a raw string (section title, project name) into a safe folder/file
 * name segment: strips diacritics, removes filesystem-invalid characters,
 * collapses whitespace to hyphens, and caps length at 60 characters.
 */
function sanitizeFolderName(raw) {
  return raw
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')          // é→e, ñ→n, ü→u …
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '')   // chars inválidos en rutas
    .replace(/\s+/g, '-')                     // espacios → guiones
    .replace(/-{2,}/g, '-')                   // colapsar guiones múltiples
    .replace(/^-+|-+$/g, '')                  // trim guiones extremos
    .slice(0, 60);
}

/**
 * Builds a zero-padded folder name for a section, ensuring correct
 * alphabetical sort in Obsidian's file explorer.
 * Example: (3, "Ética de la Virtud") → "03 - Etica-de-la-Virtud"
 */
function buildSectionFolderName(numero, titulo) {
  return `${String(numero).padStart(2, '0')} - ${sanitizeFolderName(titulo)}`;
}

/**
 * Extracts autor/obra from a project name formatted as "Autor - Obra"
 * or "Autor — Obra". Returns { autor, obra }.
 */
function prefillFromProjectName(projectName) {
  if (!projectName) return { autor: '', obra: '' };
  const parts = projectName.split(/[-—]/);
  if (parts.length >= 2) {
    return { autor: parts[0].trim(), obra: parts.slice(1).join('-').trim() };
  }
  return { autor: '', obra: projectName.trim() };
}

/**
 * Loads JSZip from CDN lazily — only when actually needed.
 * Returns a Promise resolving to the JSZip constructor, or null on failure.
 */
function loadJSZip() {
  if (window.JSZip) return Promise.resolve(window.JSZip);
  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';
    script.onload = () => resolve(window.JSZip || null);
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
}

/**
 * Triggers a single programmatic file download and waits before returning,
 * giving the browser time to register it before the next one starts.
 */
function triggerDownload(blob, filename) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      resolve();
    }, 800);
  });
}

function initObsidianExport() {
  const modal = $('modal-export-obsidian');
  const btnOpen = $('btn-open-export');
  const btnClose = $('btn-close-export');
  const btnCopy = $('btn-copy-obsidian');
  const form = $('form-export-obsidian');
  const inputAutor = $('export-autor');
  const inputObra = $('export-obra');

  if (!modal || !btnOpen || !btnClose || !btnCopy || !form) return;

  btnOpen.addEventListener('click', () => {
    // Try to pre-fill autor and obra from project name if formatted like "Autor - Obra"
    if (state.currentProject && state.currentProject.name) {
      const parts = state.currentProject.name.split(/[-—]/);
      if (parts.length >= 2) {
        inputAutor.value = parts[0].trim();
        inputObra.value = parts.slice(1).join('-').trim();
      } else {
        inputObra.value = state.currentProject.name;
        inputAutor.value = '';
      }
    }
    show(modal);
  });

  const closeModal = () => {
    hide(modal);
  };

  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  const getExportData = () => {
    if (!state.currentProject || !state.currentPartId) {
      toast('No hay contenido seleccionado para exportar.', 'error');
      return null;
    }

    const partData = state.currentProject.partes_contenido?.[String(state.currentPartId)];
    if (!partData) {
      toast('El contenido de esta parte aún no está listo.', 'warning');
      return null;
    }

    const autor = inputAutor.value.trim() || 'Desconocido';
    const obra = inputObra.value.trim() || 'Desconocida';
    const partName = state.currentProject.partes?.find(p => String(p.id) === String(state.currentPartId))?.name || `Parte ${state.currentPartId}`;

    const scope = document.querySelector('input[name="export-scope"]:checked').value; // 'current' or 'all'
    const tabs = scope === 'current' ? [state.activeTab] : ['explicacion', 'recorrido', 'recursos'];

    const files = [];

    if (tabs.includes('explicacion') && partData.explainer) {
      files.push({
        markdown: formatExplicacionMd(partData.explainer, autor, obra, partName),
        filename: `explicacion.md`
      });
    }
    if (tabs.includes('recorrido') && partData.recorrido) {
      files.push({
        markdown: formatRecorridoMd(partData.recorrido, autor, obra, partName),
        filename: `recorrido-anotado.md`
      });
    }
    if (tabs.includes('recursos') && partData.resources) {
      files.push({
        markdown: formatRecursosMd(partData.resources, autor, obra, partName),
        filename: `recursos.md`
      });
    }

    if (files.length === 0) {
      toast('No se encontró contenido en las pestañas seleccionadas.', 'warning');
      return null;
    }

    return files;
  };

  btnCopy.addEventListener('click', () => {
    const files = getExportData();
    if (!files) return;

    const textToCopy = files.map(f => f.markdown).join('\n\n\n======================================================\n\n\n');

    navigator.clipboard.writeText(textToCopy).then(() => {
      toast(files.length > 1 ? 'Todos copiados al portapapeles' : 'Copiado al portapapeles', 'success');
      closeModal();
    }).catch(err => {
      toast('Error al copiar: ' + err, 'error');
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const files = getExportData();
    if (!files) return;

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

    try {
      // Strategy 1: Native Folder Access (showDirectoryPicker)
      // Best for Desktop. On Android, it's often sandboxed or buggy for writing.
      if (window.showDirectoryPicker && !isMobile) {
        try {
          const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
          for (const file of files) {
            const fileHandle = await dirHandle.getFileHandle(file.filename, { create: true });
            const writable = await fileHandle.createWritable();
            const blob = new Blob([file.markdown], { type: 'text/markdown;charset=utf-8' });
            await writable.write(blob);
            await writable.close();
          }
          toast(`Exportados ${files.length} archivo(s) a la carpeta de Obsidian`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 1 (Native Folder) falló:', err);
        }
      }

      // Strategy 2: Native Mobile Share (Web Share API)
      // Best for Mobile - hands off files directly to the Obsidian app.
      const fileObjects = files.map(f => new File([f.markdown], f.filename, { type: 'text/plain' }));
      if (navigator.canShare && navigator.canShare({ files: fileObjects })) {
        try {
          await navigator.share({
            title: `Explainer: ${files.length} archivos`,
            files: fileObjects
          });
          toast(`Enviado a Obsidian / Compartir`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 2 (Native Share) falló:', err);
        }
      }

      // Strategy 3: Universal Fallback (Sequential download)
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        await new Promise(resolve => setTimeout(resolve, i * 1000));
        const blob = new Blob([file.markdown], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = file.filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 30000);
      }

      toast(`Descargando ${files.length} archivo(s)`, 'info');
      closeModal();

    } catch (globalErr) {
      console.error('Export Error:', globalErr);
      toast('Error durante la exportación: ' + globalErr.message, 'error');
    }
  });
}

// ── FULL PROJECT OBSIDIAN EXPORT ───────────────────────────

/**
 * Collects all completed sections from the current project and builds
 * an array of section descriptors ready to be exported.
 * Returns null when no sections are completed.
 */
function buildFullExportSections(autor, obra) {
  const project = state.currentProject;
  if (!project?.segmentation?.partes) return null;

  const sections = [];
  for (const parte of project.segmentation.partes) {
    const partData = project.partes_contenido?.[String(parte.numero)];
    if (!partData || partData.status !== 'completed') continue;

    const folderName = buildSectionFolderName(parte.numero, parte.titulo);
    const files = [];

    if (partData.explainer)
      files.push({
        filename: 'explicacion.md',
        content: formatExplicacionMd(partData.explainer, autor, obra, parte.titulo)
      });
    if (partData.recorrido)
      files.push({
        filename: 'recorrido-anotado.md',
        content: formatRecorridoMd(partData.recorrido, autor, obra, parte.titulo)
      });
    if (partData.resources)
      files.push({
        filename: 'recursos.md',
        content: formatRecursosMd(partData.resources, autor, obra, parte.titulo)
      });

    if (files.length > 0) sections.push({ folderName, files });
  }

  return sections.length > 0 ? sections : null;
}

/**
 * Strategy 1: File System Access API.
 * Creates one real subfolder per section inside the user-chosen directory.
 * Throws AbortError if the user cancels the picker; throws on API errors
 * so the caller can fall through to the next strategy.
 */
async function exportViaDirectoryPicker(sections) {
  const rootHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
  for (const section of sections) {
    const dirHandle = await rootHandle.getDirectoryHandle(section.folderName, { create: true });
    for (const file of section.files) {
      const fileHandle = await dirHandle.getFileHandle(file.filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(new Blob([file.content], { type: 'text/markdown;charset=utf-8' }));
      await writable.close();
    }
  }
}

/**
 * Strategy 2: ZIP download via JSZip (loaded lazily).
 * Builds a ZIP preserving the folder structure.
 * Returns false if JSZip could not be loaded.
 */
async function exportViaZip(sections, projectName) {
  const JSZip = await loadJSZip();
  if (!JSZip) return false;

  const zip = new JSZip();
  for (const section of sections) {
    for (const file of section.files) {
      zip.file(`${section.folderName}/${file.filename}`, file.content);
    }
  }

  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
  await triggerDownload(blob, `${sanitizeFolderName(projectName || 'proyecto')}-obsidian.zip`);
  return true;
}

/**
 * Strategy 3: Sequential flat downloads — universal fallback.
 * Files are named with the section folder prefix so they remain identifiable.
 */
async function exportViaSequentialDownload(sections) {
  for (const section of sections) {
    for (const file of section.files) {
      const blob = new Blob([file.content], { type: 'text/markdown;charset=utf-8' });
      await triggerDownload(blob, `${section.folderName} — ${file.filename}`);
    }
  }
}

function initFullProjectExport() {
  const modal = $('modal-full-export');
  const btnOpen = $('btn-open-full-export');
  const btnClose = $('btn-close-full-export');
  const form = $('form-full-export');
  const inputAutor = $('full-export-autor');
  const inputObra = $('full-export-obra');
  const summaryText = $('full-export-summary-text');
  const sectionList = $('full-export-section-list');
  const btnSubmit = $('btn-do-full-export');

  if (!modal || !btnOpen) return;

  btnOpen.addEventListener('click', () => {
    const project = state.currentProject;
    if (!project) return;

    // Pre-rellenar metadatos desde el nombre del proyecto
    const { autor, obra } = prefillFromProjectName(project.name);
    inputAutor.value = autor;
    inputObra.value = obra;

    // Calcular resumen de secciones listas
    const partes = project.segmentation?.partes ?? [];
    const readyCount = partes.filter(p =>
      project.partes_contenido?.[String(p.numero)]?.status === 'completed'
    ).length;
    summaryText.textContent = readyCount === partes.length
      ? `${readyCount} secciones · ${readyCount * 3} archivos listos para exportar`
      : `${readyCount} de ${partes.length} secciones listas · ${readyCount * 3} archivos`;

    // Renderizar checklist de secciones
    sectionList.innerHTML = partes.map(parte => {
      const isReady = project.partes_contenido?.[String(parte.numero)]?.status === 'completed';
      return `<div class="export-section-row${isReady ? ' ready' : ''}">
        <span class="row-dot"></span>
        <span>${escHtml(buildSectionFolderName(parte.numero, parte.titulo))}</span>
      </div>`;
    }).join('');

    btnSubmit.disabled = readyCount === 0;
    show(modal);
  });

  const closeModal = () => hide(modal);
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!state.currentProject) return;

    const autor = inputAutor.value.trim() || 'Desconocido';
    const obra = inputObra.value.trim() || 'Desconocida';
    const sections = buildFullExportSections(autor, obra);

    if (!sections) {
      toast('No hay secciones completadas para exportar.', 'warning');
      return;
    }

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const btnText = btnSubmit.querySelector('.btn-text');
    const origText = btnText.textContent;
    btnSubmit.disabled = true;
    btnText.textContent = 'Exportando...';

    try {
      // Estrategia 1: File System Access API — ideal para Desktop
      if (window.showDirectoryPicker && !isMobile) {
        try {
          await exportViaDirectoryPicker(sections);
          toast(`Proyecto exportado: ${sections.length} secciones en tu vault de Obsidian`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 1 (showDirectoryPicker) falló:', err);
        }
      }

      // Estrategia 2: ZIP con JSZip — preserva estructura de carpetas
      try {
        const ok = await exportViaZip(sections, state.currentProject.name);
        if (ok) {
          const total = sections.reduce((n, s) => n + s.files.length, 0);
          toast(`ZIP descargado: ${sections.length} secciones, ${total} archivos`, 'success');
          closeModal();
          return;
        }
        console.warn('Strategy 2: JSZip no disponible, usando descarga plana');
      } catch (err) {
        console.warn('Strategy 2 (JSZip) falló:', err);
      }

      // Estrategia 3: Descarga plana secuencial — fallback universal
      const total = sections.reduce((n, s) => n + s.files.length, 0);
      toast(`Descargando ${total} archivos...`, 'info');
      await exportViaSequentialDownload(sections);
      toast('Descarga completada.', 'success');
      closeModal();

    } catch (globalErr) {
      console.error('Full project export error:', globalErr);
      toast('Error durante la exportación: ' + globalErr.message, 'error');
    } finally {
      btnSubmit.disabled = false;
      btnText.textContent = origText;
    }
  });
}

function formatExplicacionMd(data, autor, obra, partName) {
  let md = ``;

  if (data.introduccion) {
    md += `> [!summary] Introducción\n> ${data.introduccion.replace(/\n/g, '\n> ')}\n\n---\n\n`;
  }

  md += `# DESARROLLO TEMÁTICO DETALLADO\n\n`;

  if (data.desarrollo && data.desarrollo.length > 0) {
    data.desarrollo.forEach((sec, i) => {
      md += `## ${i + 1}. ${sec.titulo_seccion}\n\n`;
      if (sec.explicacion_introductoria) {
        md += `${sec.explicacion_introductoria}\n\n`;
      }
      if (sec.subsecciones && sec.subsecciones.length > 0) {
        sec.subsecciones.forEach((subsec, j) => {
          md += `### ${i + 1}.${j + 1}. ${subsec.titulo_subseccion}\n\n`;
          md += `${subsec.explicacion_detallada}\n\n`;
        });
      }
      md += `---\n\n`;
    });
  }

  if (data.conclusion) {
    md += `> [!summary] Conclusión\n> ${data.conclusion.replace(/\n/g, '\n> ')}\n\n`;
  }

  if (data.conexiones_contextuales && data.conexiones_contextuales.length > 0) {
    md += `\n---\n\n## Conexiones Contextuales\n\n`;
    data.conexiones_contextuales.forEach(cx => {
      md += `### ${cx.seccion_temario_relacionada}\n\n${cx.descripcion_conexion}\n\n`;
    });
  }

  return md.trim() + '\n';
}

function formatRecorridoMd(data, autor, obra, partName) {
  let md = `# ${autor} — Recorrido Anotado (${partName})\n\n`;

  md += `> [!summary] Introducción orientadora\n> Recorrido analítico correspondiente a la sección **${partName}** de la obra **${obra}** por **${autor}**.\n\n---\n\n`;

  md += `## Recorrido Anotado\n\n`;

  if (data.recorrido_anotado && data.recorrido_anotado.length > 0) {
    data.recorrido_anotado.forEach(entry => {
      if (entry.cita_textual && entry.cita_textual.trim().length > 0) {
        md += `> [!quote] ${autor}, *${obra}*, ${entry.ubicacion}\n> «${entry.cita_textual.replace(/\n/g, '\n> ')}»\n\n`;
      } else {
        md += `> [!quote] ${autor}, *${obra}*, ${entry.ubicacion}\n> *(Contenido no citado textualmente)*\n\n`;
      }
      if (entry.traduccion) {
        md += `> [!cite]- **Traducción**\n> «${entry.traduccion.replace(/\n/g, '\n> ')}»\n\n`;
      }
      if (entry.apuntes_traductologicos) {
        md += `> *Apunte traductológico:* ${entry.apuntes_traductologicos}\n\n`;
      }
      if (entry.anotacion) {
        md += `> [!info]+ **Anotación**\n> ${entry.anotacion.replace(/\n/g, '\n> ')}\n\n`;
      }
      md += `---\n\n`;
    });
  }

  if (data.sintesis_de_cobertura) {
    md += `## Síntesis de Cobertura\n\n`;
    md += `> [!summary] Alcance del recorrido\n`;
    const s = data.sintesis_de_cobertura;
    if (s.secciones_procesadas) md += `> **Secciones procesadas:** ${s.secciones_procesadas}\n`;
    if (s.alcance) md += `> **Alcance:** ${s.alcance}\n`;
    if (s.contenido_excluido) md += `> **Contenido excluido:** ${s.contenido_excluido}\n`;
    if (s.idioma_original) md += `> **Idioma original:** ${s.idioma_original}\n>\n`;

    if (s.observaciones_globales) {
      md += `> [!abstract] Observaciones globales\n> ${s.observaciones_globales.replace(/\n/g, '\n> ')}\n\n`;
    }
  }

  return md.trim() + '\n';
}

function formatRecursosMd(data, autor, obra, partName) {
  let md = `# MAPA DE RECURSOS: ${data.titulo_mapa || partName}\n\n`;
  md += `**Autor:** ${autor}  \n**Obra:** *${obra}*\n\n---\n\n`;

  if (data.vision_general) {
    md += `${data.vision_general}\n\n---\n\n`;
  }

  if (data.ejes_tematicos && data.ejes_tematicos.length > 0) {
    data.ejes_tematicos.forEach((eje, i) => {
      md += `## ${i + 1}. ${eje.nombre_eje}\n\n`;

      if (eje.recursos && eje.recursos.length > 0) {
        eje.recursos.forEach(r => {
          let tipoIcon = r.formato === 'documental' ? '🎬' : r.formato.includes('video') ? '🎥' : r.formato.includes('podcast') ? '🎧' : '📚';
          md += `> [!tip]+ ${tipoIcon} ${r.titulo}\n`;
          md += `> **Autor/Creador:** ${r.autor_creador}  \n`;
          if (r.tipo_y_datos) md += `> **Tipo:** ${r.tipo_y_datos}  \n`;
          if (r.idioma) md += `> **Idioma:** ${r.idioma}  \n`;
          md += `> \n`;
          if (r.conexion_con_texto) {
            md += `> **Conexión con el texto:**  \n> ${r.conexion_con_texto.replace(/\n/g, '\n> ')}\n> \n`;
          }
          if (r.nivel_y_accesibilidad) {
            md += `> **Nivel y accesibilidad:**  \n> ${r.nivel_y_accesibilidad.replace(/\n/g, '\n> ')}\n`;
          }
          if (r.nota) {
            md += `> \n> **Nota:** ${r.nota.replace(/\n/g, '\n> ')}\n`;
          }
          md += `\n---\n\n`;
        });
      }
    });
  }

  if (data.nota_de_integridad) {
    md += `> [!abstract] Nota de integridad\n> ${data.nota_de_integridad.replace(/\n/g, '\n> ')}\n\n---\n\n`;
  }

  let d = new Date();
  md += `**Fecha de creación:** ${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}\n`;

  return md.trim() + '\n';
}

// ── Navigation buttons ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Tab switching
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      if (state.currentProjectId && state.currentPartId && typeof pushRoute === 'function') {
        pushRoute({
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

  // Home / logo clicks
  $('btn-home-from-projects').addEventListener('click', () => {
    if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
  });

  $('btn-new-project').addEventListener('click', () => {
    if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
  });
  $('btn-new-project-2').addEventListener('click', () => {
    if (typeof pushRoute === 'function') pushRoute({ view: 'landing' });
  });

  $('btn-export-projects').addEventListener('click', exportProjectsBackup);
  $('import-projects-input').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) importProjectsBackup(file);
    e.target.value = '';
  });

  $('btn-back-to-projects').addEventListener('click', () => {
    if (typeof pushRoute === 'function') pushRoute({ view: 'projects' });
  });

  $('btn-delete-project').addEventListener('click', async () => {
    if (!state.currentProjectId) return;
    if (!confirm('¿Eliminar este proyecto y todo su contenido? Esta acción no se puede deshacer.')) return;
    try {
      await api(`/api/projects/${state.currentProjectId}`, { method: 'DELETE' });
      const remaining = loadLocalBackup().projects.filter((p) => p.id !== state.currentProjectId);
      syncProjectsToLocal(remaining);
      toast('Proyecto eliminado.', 'success');
      if (state.processingSSE) { state.processingSSE.close(); state.processingSSE = null; }
      if (typeof pushRoute === 'function') pushRoute({ view: 'projects' });
    } catch (err) {
      toast('Error al eliminar: ' + err.message, 'error');
    }
  });

  // Init
  initSettings();
  initVisibilityHandling();
  initObsidianExport();
  initFullProjectExport();
  initReadingProgressBar();
  initSidebarMobile();
  initSidebarCollapse();
  initPartNavigation();
  initCopyLink();
  initApp();
});

// ── READING PROGRESS BAR ─────────────────────────────────────
function initReadingProgressBar() {
  const bar = $('reading-progress-bar');
  const main = $('project-main');
  if (!bar || !main) return;

  main.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = main;
    const pct = scrollHeight <= clientHeight ? 0 : (scrollTop / (scrollHeight - clientHeight)) * 100;
    bar.style.width = pct + '%';
  }, { passive: true });
}

// ── MOBILE SIDEBAR DRAWER ────────────────────────────────────
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

  // Close on overlay click
  overlay.addEventListener('click', closeMobileSidebar);

  // Also close when a part is tapped on mobile
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

// ── DESKTOP SIDEBAR COLLAPSE ─────────────────────────────────
function initSidebarCollapse() {
  const sidebar = $('project-sidebar');
  const collapseBtn = $('btn-sidebar-collapse');
  const expandBtn = $('btn-sidebar-expand');
  const layout = document.querySelector('.project-layout');

  if (!sidebar || !collapseBtn) return;

  function toggleSidebar() {
    const collapsed = sidebar.classList.toggle('collapsed');
    collapseBtn.style.transform = collapsed ? 'rotate(180deg)' : '';
    // Push main content
    if (layout) layout.classList.toggle('sidebar-hidden', collapsed);
  }

  collapseBtn.addEventListener('click', toggleSidebar);
  if (expandBtn) expandBtn.addEventListener('click', toggleSidebar);
}


// ── PART NAVIGATION (prev / next) ───────────────────────────
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
  if (next && typeof pushRoute === 'function') {
    pushRoute({
      view: 'project',
      projectId: state.currentProjectId,
      partId: next.numero,
      tab: state.activeTab,
    });
  }
}

// ── COPY LINK ──────────────────────────────────────────────
function initCopyLink() {
  const btn = $('btn-copy-link');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    if (!state.currentProjectId || !state.currentPartId) return;
    const url = location.origin + location.pathname + (typeof buildHash === 'function'
      ? buildHash({
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

/**
 * Update the reading toolbar prev/next buttons and label based on current part index.
 */
function updateReadingToolbar() {
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

/**
 * Update mobile header name.
 */
function updateMobileHeader() {
  const el = $('mobile-project-name');
  if (el && state.currentProject) {
    el.textContent = state.currentProject.name || '';
  }
}

