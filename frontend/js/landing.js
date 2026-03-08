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
let selectedModel = 'gemini-3-flash-preview';

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

export function initLanding() {
  updateApiKeyUI();

  const zone = $('upload-zone');
  const fileInput = $('file-input');
  const btnUpload = $('btn-upload');
  const nameInput = $('project-name');
  const descInput = $('project-description');
  const youtubeUrlInput = $('youtube-url');
  const webUrlInput = $('web-url');

  const tabPdf = $('tab-pdf');
  const tabYoutube = $('tab-youtube');
  const tabWeb = $('tab-web');
  const panelPdf = $('panel-pdf');
  const panelYoutube = $('panel-youtube');
  const panelWeb = $('panel-web');

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

    validateForm();
  }

  tabPdf.addEventListener('click', () => switchSourceType('pdf'));
  tabYoutube.addEventListener('click', () => switchSourceType('youtube'));
  tabWeb.addEventListener('click', () => switchSourceType('web'));

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

  document.querySelectorAll('input[name="model-choice"]').forEach(radio => {
    radio.addEventListener('change', (e) => { selectedModel = e.target.value; });
  });

  btnUpload.addEventListener('click', handleUpload);
  $('btn-go-projects').addEventListener('click', () => {
    if (window.pushRoute) window.pushRoute({ view: 'projects' });
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
  errEl.textContent = '';

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
    document.querySelectorAll('input[name="model-choice"]').forEach(r => {
      r.checked = r.value === 'gemini-3-flash-preview';
    });
    const modelForProcess = selectedModel;
    selectedModel = 'gemini-3-flash-preview';

    await api(`/api/projects/${project.id}/process?model=${encodeURIComponent(modelForProcess)}`, { method: 'POST' });

    if (window.pushRoute) window.pushRoute({ view: 'project', projectId: project.id });

  } catch (err) {
    errEl.textContent = err.message;
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = 'Iniciar análisis';
  }
}
