/* ============================================================
   EXPLAINER — Landing View & Upload
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, formatBytes, toast } from './dom.js';
import { api } from './api.js';
import { invalidateProjectsCache, loadBackupAsync, mergeProjects, syncProjectsToBackup } from './storage.js';
import { updateApiKeyUI, showSettings } from './auth.js';

let selectedFile = null;
let currentSourceType = 'pdf';
let currentExplainerProvider = 'gemini';

export function extractYouTubeVideoId(url) {
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

export function isValidYouTubeUrl(url) {
  if (!url || url.trim().length === 0) return false;
  return extractYouTubeVideoId(url) !== null;
}

export function normalizeWebUrl(url) {
  if (!url || url.trim().length === 0) return null;
  try {
    const parsed = new URL(url.trim());
    if (!['http:', 'https:'].includes(parsed.protocol)) return null;
    parsed.hash = '';
    return parsed.toString();
  } catch (_) {
    return null;
  }
}

export function isValidWebUrl(url) {
  return normalizeWebUrl(url) !== null;
}

export function isExplainerProviderSupportedForSource(sourceType, provider) {
  if (provider === 'openrouter' && sourceType === 'youtube') return false;
  return provider === 'gemini' || provider === 'openrouter';
}

export function validateExplainerProviderSelection({
  sourceType,
  provider,
  hasGeminiKey,
  hasOpenRouterKey,
  hasMistralKey,
}) {
  if (!hasGeminiKey) {
    return 'Necesitas configurar tu API key de Gemini primero. Ve a Ajustes.';
  }

  if (!isExplainerProviderSupportedForSource(sourceType, provider)) {
    return 'OpenRouter todavía no está disponible para vídeos de YouTube. Usa Gemini para esta fuente.';
  }

  if (provider === 'openrouter' && !hasOpenRouterKey) {
    return 'Necesitas configurar tu API key de OpenRouter para usar Xiaomi en el explainer.';
  }

  if (provider === 'openrouter' && sourceType === 'pdf' && !hasMistralKey) {
    return 'Necesitas configurar tu API key de Mistral para usar OCR nativo en PDFs con Xiaomi/OpenRouter.';
  }

  return null;
}

function buildExplainerProviderHint(sourceType, provider) {
  if (!isExplainerProviderSupportedForSource(sourceType, 'openrouter')) {
    return 'YouTube se procesa con Gemini. OpenRouter todavía no está disponible para esta fuente.';
  }

  if (provider === 'openrouter') {
    if (sourceType === 'pdf') {
      if (state.hasOpenRouterKey && state.hasMistralKey) {
        return 'La explicación usará Xiaomi vía OpenRouter y el OCR de PDFs usará Mistral nativo. Segmentación, recorrido, recursos y formateo siguen usando Gemini.';
      }
      if (!state.hasMistralKey) {
        return 'Para PDFs con Xiaomi necesitas guardar también tu API key de Mistral para el OCR nativo.';
      }
    }
    if (state.hasOpenRouterKey) {
      return 'La explicación usará Xiaomi vía OpenRouter. Segmentación, recorrido, recursos y formateo seguirán usando Gemini.';
    }
    return 'Xiaomi está disponible para PDF y web, pero primero necesitas guardar tu API key de OpenRouter. Gemini sigue siendo obligatorio para el resto del pipeline.';
  }

  return 'La explicación usará Gemini. Segmentación, recorrido, recursos y formateo seguirán usando Gemini.';
}

export function initLanding() {
  updateApiKeyUI();

  const zone = $('upload-zone');
  const fileInput = $('file-input');
  const btnUpload = $('btn-upload');
  const nameInput = $('project-name');
  const descInput = $('project-description');
  const youtubeUrlInput = $('youtube-url');
  const webUrlInput = $('web-url');
  const providerGemini = $('explainer-provider-gemini');
  const providerOpenRouter = $('explainer-provider-openrouter');
  const providerHint = $('explainer-provider-hint');
  const providerError = $('explainer-provider-error');

  const tabPdf = $('tab-pdf');
  const tabYoutube = $('tab-youtube');
  const tabWeb = $('tab-web');
  const panelPdf = $('panel-pdf');
  const panelYoutube = $('panel-youtube');
  const panelWeb = $('panel-web');

  function clearProviderError() {
    providerError.textContent = '';
    hide(providerError);
  }

  function syncExplainerProviderUI() {
    const openRouterSupported = isExplainerProviderSupportedForSource(currentSourceType, 'openrouter');
    if (!openRouterSupported && currentExplainerProvider === 'openrouter') {
      currentExplainerProvider = 'gemini';
    }

    providerGemini.checked = currentExplainerProvider === 'gemini';
    providerOpenRouter.checked = currentExplainerProvider === 'openrouter';
    providerOpenRouter.disabled = !openRouterSupported;

    $('provider-card-gemini').classList.toggle('selected', currentExplainerProvider === 'gemini');
    $('provider-card-openrouter').classList.toggle('selected', currentExplainerProvider === 'openrouter');
    $('provider-card-openrouter').classList.toggle('disabled', !openRouterSupported);

    providerHint.textContent = buildExplainerProviderHint(currentSourceType, currentExplainerProvider);
    clearProviderError();
  }

  function setExplainerProvider(provider) {
    currentExplainerProvider = provider;
    syncExplainerProviderUI();
  }

  function switchSourceType(type) {
    currentSourceType = type;

    tabPdf.classList.toggle('active', type === 'pdf');
    tabYoutube.classList.toggle('active', type === 'youtube');
    tabWeb.classList.toggle('active', type === 'web');

    if (type === 'pdf') {
      show(panelPdf);
      hide(panelYoutube);
      hide(panelWeb);
    } else if (type === 'youtube') {
      hide(panelPdf);
      show(panelYoutube);
      hide(panelWeb);
    } else {
      hide(panelPdf);
      hide(panelYoutube);
      show(panelWeb);
    }

    $('upload-error').textContent = '';
    $('youtube-url-error').textContent = '';
    $('web-url-error').textContent = '';
    hide($('youtube-url-error'));
    hide($('web-url-error'));
    syncExplainerProviderUI();

    validateForm();
  }

  tabPdf.addEventListener('click', () => switchSourceType('pdf'));
  tabYoutube.addEventListener('click', () => switchSourceType('youtube'));
  tabWeb.addEventListener('click', () => switchSourceType('web'));
  providerGemini.addEventListener('change', () => {
    if (providerGemini.checked) setExplainerProvider('gemini');
  });
  providerOpenRouter.addEventListener('change', () => {
    if (providerOpenRouter.checked) setExplainerProvider('openrouter');
  });

  function checkReady() {
    const hasName = nameInput.value.trim();
    if (currentSourceType === 'pdf') {
      const ready = selectedFile && hasName;
      btnUpload.disabled = !ready;
    } else if (currentSourceType === 'youtube') {
      const url = youtubeUrlInput.value.trim();
      const ready = isValidYouTubeUrl(url) && hasName;
      btnUpload.disabled = !ready;
    } else {
      const url = webUrlInput.value.trim();
      const ready = isValidWebUrl(url) && hasName;
      btnUpload.disabled = !ready;
    }
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

  webUrlInput.addEventListener('input', () => {
    const url = webUrlInput.value.trim();
    const urlError = $('web-url-error');

    if (url && !isValidWebUrl(url)) {
      urlError.textContent = 'URL web inválida. Usa una URL pública completa con http:// o https://';
      show(urlError);
    } else {
      urlError.textContent = '';
      hide(urlError);
    }
    checkReady();
  });

  nameInput.addEventListener('input', checkReady);
  descInput.addEventListener('input', checkReady);

  btnUpload.addEventListener('click', handleUpload);
  $('btn-go-projects').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'projects' });
  });

  syncExplainerProviderUI();
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
  const webUrlInput = $('web-url');
  const hasName = nameInput.value.trim();

  if (currentSourceType === 'pdf') {
    const ready = selectedFile && hasName;
    $('btn-upload').disabled = !ready;
  } else if (currentSourceType === 'youtube') {
    const url = youtubeUrlInput.value.trim();
    const ready = isValidYouTubeUrl(url) && hasName;
    $('btn-upload').disabled = !ready;
  } else {
    const url = webUrlInput.value.trim();
    const ready = isValidWebUrl(url) && hasName;
    $('btn-upload').disabled = !ready;
  }
}

async function handleUpload() {
  const name = $('project-name').value.trim();
  const description = $('project-description').value.trim();
  const errEl = $('upload-error');
  const providerError = $('explainer-provider-error');
  errEl.textContent = '';
  providerError.textContent = '';
  hide(providerError);

  const providerValidationError = validateExplainerProviderSelection({
    sourceType: currentSourceType,
    provider: currentExplainerProvider,
    hasGeminiKey: state.hasApiKey,
    hasOpenRouterKey: state.hasOpenRouterKey,
    hasMistralKey: state.hasMistralKey,
  });
  if (providerValidationError) {
    providerError.textContent = providerValidationError;
    show(providerError);
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
    } else if (currentSourceType === 'youtube') {
      const youtubeUrl = $('youtube-url').value.trim();
      if (!isValidYouTubeUrl(youtubeUrl)) {
        errEl.textContent = 'URL de YouTube inválida.';
        btn.disabled = false;
        return;
      }
      btn.querySelector('.btn-text').textContent = 'Creando proyecto...';
      fd.append('youtube_url', youtubeUrl);
    } else {
      const webUrl = normalizeWebUrl($('web-url').value.trim());
      if (!webUrl) {
        errEl.textContent = 'URL web inválida.';
        btn.disabled = false;
        return;
      }
      btn.querySelector('.btn-text').textContent = 'Creando proyecto...';
      fd.append('web_url', webUrl);
    }

    const project = await api('/api/projects', { method: 'POST', body: fd });
    invalidateProjectsCache();
    const local = (await loadBackupAsync(state.user?.id)).projects;
    const mergedAfterCreate = mergeProjects([project], local);
    await syncProjectsToBackup(mergedAfterCreate, state.user?.id);
    toast('Proyecto creado. Iniciando análisis...', 'success');

    clearFile();
    $('project-name').value = '';
    $('project-description').value = '';
    $('youtube-url').value = '';
    $('web-url').value = '';
    await api(`/api/projects/${project.id}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ explainer_provider: currentExplainerProvider }),
    });

    if (window.pushRoute) window.pushRoute({ view: 'project', projectId: project.id });

  } catch (err) {
    errEl.textContent = err.message;
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = 'Iniciar análisis';
  }
}
