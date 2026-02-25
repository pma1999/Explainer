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

  supabaseClient.auth.onAuthStateChange((_event, newSession) => {
    const prevUserId = state.user?.id ?? null;
    const newUserId = newSession?.user?.id ?? null;

    // Update state
    state.session = newSession;
    state.user = newSession?.user ?? null;

    // Smart navigation: only redirect on meaningful state changes
    if (!prevUserId && newUserId) {
      // Fresh login (was logged out, now logged in)
      showView('view-landing');
      initLanding();
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

  // Try to restore previous view state from sessionStorage
  // This handles browser tab discard/recovery scenarios
  const savedState = sessionStorage.getItem('explainer.viewState');
  if (savedState) {
    try {
      const viewState = JSON.parse(savedState);
      // Only restore if it's the same user
      if (viewState.userId === state.user?.id) {
        // Restore view based on saved state
        if (viewState.view === 'view-project' && viewState.projectId) {
          // Restore project view
          state.currentProjectId = viewState.projectId;
          state.currentPartId = viewState.partId || null;
          state.activeTab = viewState.activeTab || 'explicacion';
          // Load project and show view
          await restoreProjectView(viewState.projectId, viewState.partId, viewState.activeTab);
          return;
        } else if (viewState.view === 'view-projects') {
          showView('view-projects');
          loadProjectsView();
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

  // Default: go to landing
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
    // If restore fails, go to projects list
    showView('view-projects');
    loadProjectsView();
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
      showView('view-landing');
      initLanding();
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
      showView('view-landing');
      initLanding();
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
  $('btn-go-projects').addEventListener('click', loadProjectsView);
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

    // Open project view and start listening
    await openProjectView(project.id);

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
    card.addEventListener('click', () => openProjectView(card.dataset.id));
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

  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
  if (isProcessing) {
    showProcessingIndicator(project.status);
  } else {
    hideProcessingIndicator();
  }

  if (!state.currentPartId) {
    show($('main-welcome'));
    hide($('part-content'));
    const hasPartes = project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0;
    const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
    $('welcome-title').textContent = hasPartes ? 'Selecciona una parte' : (isProcessing ? 'Procesando...' : 'Sin contenido');
    $('welcome-sub').textContent = hasPartes
      ? 'Haz clic en cualquier parte completada para ver su contenido mientras se genera el resto.'
      : (isProcessing ? 'El análisis está en curso. Los resultados aparecerán en el sidebar.' : 'No hay partes disponibles.');
  }
}

function renderSidebarNav(project) {
  const nav = $('sidebar-nav');
  nav.innerHTML = '';

  if (!project.segmentation || !project.segmentation.partes) return;

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

    const el = document.createElement('div');
    el.className = `sidebar-part${state.currentPartId === partId ? ' active' : ''}`;
    el.dataset.partId = partId;
    el.innerHTML = `
      <span class="part-num">P${partId}</span>
      <span class="part-label">${escHtml(parte.titulo)}</span>
      <span class="part-status-dot ${dotClass}"></span>
    `;
    el.addEventListener('click', () => selectPart(partId));
    nav.appendChild(el);
  });
}

function updateProcessingOverlay(status) {
  const titles = {
    uploading: 'Subiendo documento...',
    segmenting: 'Segmentando el texto...',
    processing: 'Generando contenido...',
    pending: 'Iniciando...',
  };
  const subs = {
    uploading: 'Enviando el PDF a la IA',
    segmenting: 'El Segmentador está dividiendo el texto en partes',
    processing: 'Explainer, Recorrido y Recursos trabajando en paralelo',
    pending: 'Preparando',
  };
  const titleEl = $('processing-title');
  const subEl = $('processing-sub');
  if (titleEl) titleEl.textContent = titles[status] || 'Procesando...';
  if (subEl) subEl.textContent = subs[status] || '';
}

function pushStreamEvent(type, desc) {
  const container = $('stream-events');
  if (container) {
    const time = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const el = document.createElement('div');
    el.className = 'stream-event';
    el.innerHTML = `<span class="event-time">${time}</span><span class="event-type">${escHtml(type)}</span><span class="event-desc">${escHtml(desc || '')}</span>`;
    container.insertBefore(el, container.firstChild);
    while (container.children.length > 20) container.lastChild.remove();
  }
  // Also update floating indicator
  pushIndicatorStream(`${type}: ${desc || ''}`);
}

function setAgentNodeState(agentId, stateKind) {
  const node = $(`agent-${agentId}`);
  if (!node) return;
  node.classList.remove('active', 'completed');
  if (stateKind === 'active') node.classList.add('active');
  if (stateKind === 'completed') node.classList.add('completed');
}

function setAllAgentsIdle() {
  ['explainer', 'recorrido', 'resources'].forEach((id) => {
    setAgentNodeState(id, '');
    setIndicatorAgentState(id, '');
  });
}

// ── Non-blocking processing indicator ───────────────────
function ensureFloatingIndicatorExists() {
  if ($('floating-indicator')) return;
  const indicator = document.createElement('div');
  indicator.id = 'floating-indicator';
  indicator.className = 'floating-indicator hidden';
  indicator.innerHTML = `
    <div class="fi-core">
      <div class="fi-ring fi-ring-1"></div>
      <div class="fi-ring fi-ring-2"></div>
    </div>
    <div class="fi-content">
      <div class="fi-title">Generando...</div>
      <div class="fi-agents">
        <span id="fi-explainer" class="fi-agent">📖</span>
        <span id="fi-recorrido" class="fi-agent">✍️</span>
        <span id="fi-resources" class="fi-agent">🗺️</span>
      </div>
      <div class="fi-stream" id="fi-stream"></div>
    </div>
    <button class="fi-toggle" id="fi-toggle" title="Expandir/Colapsar">▼</button>
  `;
  document.body.appendChild(indicator);

  // Toggle expand/collapse
  indicator.querySelector('#fi-toggle').addEventListener('click', () => {
    indicator.classList.toggle('collapsed');
  });

  // Click on indicator to open project if not current
  indicator.addEventListener('click', (e) => {
    if (e.target.closest('#fi-toggle')) return;
    const view = document.querySelector('.view.active');
    if (view && view.id !== 'view-project' && state.sseProjectId) {
      openProjectView(state.sseProjectId);
    }
  });
}

function showProcessingIndicator(status) {
  ensureFloatingIndicatorExists();
  const indicator = $('floating-indicator');
  if (!indicator) return;
  indicator.classList.remove('hidden');
  updateProcessingIndicator(status);
}

function hideProcessingIndicator() {
  const indicator = $('floating-indicator');
  if (indicator) indicator.classList.add('hidden');
  // Also hide the old overlay if visible
  hide($('processing-overlay'));
}

function updateProcessingIndicator(status) {
  const titleMap = {
    uploading: 'Subiendo PDF...',
    segmenting: 'Segmentando...',
    processing: 'Generando contenido...',
    pending: 'Iniciando...',
  };
  const fiTitle = document.querySelector('#floating-indicator .fi-title');
  if (fiTitle) fiTitle.textContent = titleMap[status] || 'Procesando...';
}

function pushIndicatorStream(text) {
  const stream = $('fi-stream');
  if (!stream) return;
  const line = document.createElement('div');
  line.className = 'fi-line';
  line.textContent = text;
  stream.appendChild(line);
  if (stream.children.length > 5) stream.firstChild.remove();
}

function setIndicatorAgentState(agentId, stateKind) {
  const el = document.querySelector(`#fi-${agentId}`);
  if (!el) return;
  el.classList.remove('active', 'completed');
  if (stateKind) el.classList.add(stateKind);
}

function selectPart(partId) {
  state.currentPartId = partId;

  document.querySelectorAll('.sidebar-part').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.partId) === partId);
  });

  hide($('main-welcome'));
  show($('part-content'));

  const project = state.currentProject;
  const parte = project.segmentation.partes.find(p => p.numero === partId);
  const contenido = project.partes_contenido ? project.partes_contenido[String(partId)] : null;

  $('content-part-number').textContent = `PARTE ${partId}`;
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

  // Save view state when selecting a part
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
  // Save view state when changing tabs
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
  setAllAgentsIdle();
  const streamEvents = $('stream-events');
  if (streamEvents) streamEvents.innerHTML = '';

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
          pushStreamEvent('Uso', `$${(payload.usage?.total_cost || 0).toFixed(2)}`);
          break;

        case 'uploading':
          project.status = 'uploading';
          updateProcessingOverlay('uploading');
          pushStreamEvent('Subida', 'Enviando PDF a la IA');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-uploading">Subiendo</span>`;
          setAllAgentsIdle();
          break;

        case 'segmenting':
          project.status = 'segmenting';
          updateProcessingOverlay('segmenting');
          pushStreamEvent('Segmentación', 'Dividiendo el texto en partes');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-segmenting">Segmentando</span>`;
          setAllAgentsIdle();
          break;

        case 'segmented':
          project.status = 'processing';
          try {
            const fresh = await api(`/api/projects/${projectId}`);
            state.currentProject = fresh;
            Object.assign(project, { segmentation: fresh.segmentation, partes_contenido: fresh.partes_contenido || {} });
          } catch (_) { }
          renderSidebarNav(state.currentProject);
          updateProcessingOverlay('processing');
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-processing">Procesando</span>`;
          const welcomeTitle = $('welcome-title');
          const welcomeSub = $('welcome-sub');
          if (welcomeTitle) welcomeTitle.textContent = 'Generando contenido';
          if (welcomeSub) welcomeSub.textContent = 'Los 3 agentes están trabajando en paralelo para cada parte.';
          pushStreamEvent('Segmentado', `${(project.segmentation?.partes?.length || 0)} partes`);
          setAgentNodeState('explainer', 'active');
          setAgentNodeState('recorrido', 'active');
          setAgentNodeState('resources', 'active');
          setIndicatorAgentState('explainer', 'active');
          setIndicatorAgentState('recorrido', 'active');
          setIndicatorAgentState('resources', 'active');
          break;

        case 'part_started':
          if (project.partes_contenido) {
            const key = String(payload.part_id);
            if (!project.partes_contenido[key]) {
              project.partes_contenido[key] = { status: 'processing', explainer: null, recorrido: null, resources: null };
            } else {
              project.partes_contenido[key].status = 'processing';
            }
            renderSidebarNav(state.currentProject);
          }
          setAgentNodeState('explainer', 'active');
          setAgentNodeState('recorrido', 'active');
          setAgentNodeState('resources', 'active');
          setIndicatorAgentState('explainer', 'active');
          setIndicatorAgentState('recorrido', 'active');
          setIndicatorAgentState('resources', 'active');
          pushStreamEvent('Parte', `Parte ${payload.part_id} iniciada`);
          break;

        case 'agent_completed': {
          const key = String(payload.part_id);
          const agent = payload.agent;
          setAgentNodeState(agent, 'completed');
          setIndicatorAgentState(agent, 'completed');
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
          const agentLabel = agent === 'explainer' ? 'Explicación' : agent === 'recorrido' ? 'Recorrido' : 'Recursos';
          pushStreamEvent(agentLabel, `Parte ${payload.part_id} lista`);
          break;
        }

        case 'part_completed': {
          const key = String(payload.part_id);
          if (project.partes_contenido && project.partes_contenido[key]) {
            project.partes_contenido[key].status = 'completed';
          }
          renderSidebarNav(state.currentProject);
          if (state.currentPartId === payload.part_id) {
            selectPart(payload.part_id);
          }
          setAllAgentsIdle();
          pushStreamEvent('Parte completada', `Parte ${payload.part_id}`);
          break;
        }

        case 'completed':
          project.status = 'completed';
          if ($('sidebar-status')) $('sidebar-status').innerHTML = `<span class="card-status-badge status-completed">Completado</span>`;
          setAllAgentsIdle();
          pushStreamEvent('Completado', 'Análisis finalizado');
          hide($('processing-overlay'));
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
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
  });

  // Home / logo clicks
  $('btn-home-from-projects').addEventListener('click', () => showView('view-landing'));

  $('btn-new-project').addEventListener('click', () => {
    showView('view-landing');
  });
  $('btn-new-project-2').addEventListener('click', () => {
    showView('view-landing');
  });

  $('btn-export-projects').addEventListener('click', exportProjectsBackup);
  $('import-projects-input').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) importProjectsBackup(file);
    e.target.value = '';
  });

  $('btn-back-to-projects').addEventListener('click', () => {
    // NO cerrar SSE al ir a proyectos - seguimos escuchando en background
    // Solo detener polling específico de la lista de proyectos
    loadProjectsView();
    // Iniciar polling de la lista si hay proyectos activos (incluido el actual)
    const localProjects = loadLocalBackup().projects;
    const hasActive = localProjects.some((p) => ['pending', 'uploading', 'segmenting', 'processing'].includes(p.status));
    if (hasActive) startProjectsListPolling();
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
      loadProjectsView();
    } catch (err) {
      toast('Error al eliminar: ' + err.message, 'error');
    }
  });

  // Init
  initSettings();
  initVisibilityHandling();
  initObsidianExport();
  initApp();
});
