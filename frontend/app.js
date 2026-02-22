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
  processingSSE: null,
  hasApiKey: false,
  session: null,
  user: null,
};

const LOCAL_BACKUP_KEY = 'explainer.projects.backup.v1';

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

  supabaseClient.auth.onAuthStateChange((_event, session) => {
    state.session = session;
    state.user = session?.user ?? null;
    if (session) {
      showView('view-landing');
      initLanding();
      refreshApiKeyStatus();
    } else {
      showView('view-auth');
    }
  });

  if (!state.session) {
    showView('view-auth');
    initAuth();
    return;
  }

  showView('view-landing');
  initLanding();
  await refreshApiKeyStatus();
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

function initLanding() {
  updateApiKeyUI();

  const zone = $('upload-zone');
  const fileInput = $('file-input');
  const btnUpload = $('btn-upload');
  const nameInput = $('project-name');
  const descInput = $('project-description');

  function checkReady() {
    const ready = selectedFile && nameInput.value.trim() && descInput.value.trim();
    btnUpload.disabled = !ready;
  }

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

  nameInput.addEventListener('input', checkReady);
  descInput.addEventListener('input', checkReady);

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
  const descInput = $('project-description');
  const ready = selectedFile && nameInput.value.trim() && descInput.value.trim();
  $('btn-upload').disabled = !ready;
}

async function handleUpload() {
  const name = $('project-name').value.trim();
  const description = $('project-description').value.trim();
  const errEl = $('upload-error');
  errEl.textContent = '';

  if (!selectedFile || !name || !description) {
    errEl.textContent = 'Completa todos los campos y selecciona un PDF.';
    return;
  }

  // Verificar que tenga API key
  if (!state.hasApiKey) {
    errEl.textContent = 'Necesitas configurar tu API key de Gemini primero. Ve a Ajustes.';
    showSettings();
    return;
  }

  const btn = $('btn-upload');
  btn.disabled = true;
  btn.querySelector('.btn-text').textContent = 'Creando proyecto...';

  try {
    const fd = new FormData();
    fd.append('name', name);
    fd.append('description', description);
    fd.append('file', selectedFile);

    const project = await api('/api/projects', { method: 'POST', body: fd });
    const mergedAfterCreate = mergeProjects([project], loadLocalBackup().projects);
    syncProjectsToLocal(mergedAfterCreate);
    toast('Proyecto creado. Iniciando análisis...', 'success');

    // Reset form
    clearFile();
    $('project-name').value = '';
    $('project-description').value = '';

    // Start processing
    await api(`/api/projects/${project.id}/process`, { method: 'POST' });

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
      startSSE(projectId);
    }
  } catch (err) {
    const cachedProject = getCachedProject(projectId);

    if (cachedProject) {
      state.currentProject = cachedProject;
      renderProjectView(cachedProject);
      toast('Proyecto recuperado desde copia local. Intentando sincronizar en segundo plano…', 'success');

      rehydrateProjectToServer(cachedProject).catch(() => {});
      return;
    }

    toast('Error cargando proyecto: ' + err.message, 'error');
  }
}

function renderProjectView(project) {
  $('sidebar-project-name').textContent = project.name;
  $('sidebar-status').innerHTML = `<span class="card-status-badge status-${project.status}">${statusLabel(project.status)}</span>`;

  renderSidebarNav(project);
  updateUsageUI(project.usage);

  const isProcessing = ['pending', 'uploading', 'segmenting', 'processing'].includes(project.status);
  if (isProcessing) {
    show($('processing-overlay'));
    updateProcessingOverlay(project.status);
  } else {
    hide($('processing-overlay'));
  }

  if (!state.currentPartId) {
    show($('main-welcome'));
    hide($('part-content'));
    const hasPartes = project.segmentation && project.segmentation.partes && project.segmentation.partes.length > 0;
    $('welcome-title').textContent = hasPartes ? 'Selecciona una parte' : 'Procesando...';
    $('welcome-sub').textContent = hasPartes
      ? 'Elige una parte del sidebar para ver su contenido'
      : 'El análisis está en curso. Los resultados aparecerán aquí.';
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
    uploading: 'Subiendo documento...', segmenting: 'Segmentando el texto...',
    processing: 'Generando contenido...', pending: 'Iniciando...',
  };
  const subs = {
    uploading: 'Enviando el PDF a la IA', segmenting: 'El Segmentador está dividiendo el texto en partes',
    processing: 'Explainer, Recorrido y Recursos trabajando en paralelo', pending: 'Preparando',
  };
  $('processing-title').textContent = titles[status] || 'Procesando...';
  $('processing-sub').textContent = subs[status] || '';
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

// ── SSE ────────────────────────────────────────────────────
function startSSE(projectId) {
  if (state.processingSSE) {
    state.processingSSE.close();
  }

  const token = getAccessToken();
  const base = `${API_BASE_URL}/api/projects/${projectId}/events`;
  const url = token ? `${base}?token=${encodeURIComponent(token)}` : base;
  const evtSource = new EventSource(url);
  state.processingSSE = evtSource;

  evtSource.onmessage = async (e) => {
    let payload;
    try { payload = JSON.parse(e.data); } catch { return; }

    const project = state.currentProject;
    if (!project) return;

    switch (payload.type) {
      case 'ping': break;

      case 'usage_update':
        if (state.currentProject) {
          state.currentProject.usage = payload.usage;
          updateUsageUI(payload.usage);
        }
        break;

      case 'uploading':
        project.status = 'uploading';
        updateProcessingOverlay('uploading');
        $('sidebar-status').innerHTML = `<span class="card-status-badge status-uploading">Subiendo</span>`;
        break;

      case 'segmenting':
        project.status = 'segmenting';
        updateProcessingOverlay('segmenting');
        $('sidebar-status').innerHTML = `<span class="card-status-badge status-segmenting">Segmentando</span>`;
        break;

      case 'segmented':
        project.status = 'processing';
        try {
          const fresh = await api(`/api/projects/${projectId}`);
          state.currentProject = fresh;
          project.segmentation = fresh.segmentation;
          project.partes_contenido = fresh.partes_contenido;
        } catch { }
        renderSidebarNav(state.currentProject);
        updateProcessingOverlay('processing');
        $('sidebar-status').innerHTML = `<span class="card-status-badge status-processing">Procesando</span>`;
        $('welcome-title').textContent = 'Generando contenido';
        $('welcome-sub').textContent = 'Los 3 agentes están trabajando en paralelo para cada parte.';
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
        break;

      case 'agent_completed': {
        const key = String(payload.part_id);
        try {
          const fresh = await api(`/api/projects/${projectId}`);
          if (fresh.partes_contenido && fresh.partes_contenido[key]) {
            if (!project.partes_contenido[key]) project.partes_contenido[key] = {};
            const agentKey = payload.agent;
            project.partes_contenido[key][agentKey] = fresh.partes_contenido[key][agentKey];
          }
          if (state.currentPartId === payload.part_id) {
            renderTab(payload.agent === 'explainer' ? 'explicacion' : payload.agent === 'recorrido' ? 'recorrido' : 'recursos', project.partes_contenido[key]);
          }
        } catch { }
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
        break;
      }

      case 'completed':
        project.status = 'completed';
        $('sidebar-status').innerHTML = `<span class="card-status-badge status-completed">Completado</span>`;
        hide($('processing-overlay'));
        toast('¡Análisis completo! Ya puedes estudiar todo el contenido.', 'success');
        evtSource.close();
        break;

      case 'error':
        project.status = 'error';
        $('sidebar-status').innerHTML = `<span class="card-status-badge status-error">Error</span>`;
        hide($('processing-overlay'));
        toast('Error: ' + (payload.message || 'Error desconocido'), 'error');
        evtSource.close();
        break;

      case 'stream_end':
        evtSource.close();
        break;
    }
  };

  evtSource.onerror = () => {
    // Silently retry
  };
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
    if (state.processingSSE) {
      state.processingSSE.close();
      state.processingSSE = null;
    }
    loadProjectsView();
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
  initApp();
});
