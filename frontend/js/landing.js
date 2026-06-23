/* ============================================================
   EXPLAINER — Landing View & Upload
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, formatBytes, toast } from './dom.js';
import { api } from './api.js';
import { createCombobox } from './components/openrouter-combobox.js';
import { invalidateProjectsCache, loadBackupAsync, mergeProjects, syncProjectsToBackup } from './storage.js';
import { updateApiKeyUI, showSettings } from './auth.js';

let selectedFile = null;
let currentSourceType = 'pdf';
let currentExplainerProvider = 'gemini';
let currentTargetLanguage = 'es-ES';
export const OPENROUTER_MODEL_MIMO_PRO = 'xiaomi/mimo-v2.5-pro';
export const OPENROUTER_MODEL_MIMO = 'xiaomi/mimo-v2.5';
export const OPENROUTER_MODEL_DEEPSEEK_V4_PRO = 'deepseek/deepseek-v4-pro';
export const DEFAULT_TARGET_LANGUAGE = 'es-ES';
export const SUPPORTED_TARGET_LANGUAGES = ['es-ES', 'en', 'fr', 'de', 'it', 'pt-PT'];
export const DEEPSEEK_MODEL_V4_PRO = 'deepseek-v4-pro';
export const DEEPSEEK_MODEL_V4_FLASH = 'deepseek-v4-flash';
let currentOpenRouterModel = OPENROUTER_MODEL_MIMO_PRO;
let currentOpenRouterMode = 'preset'; // 'preset' | 'custom'
let currentCustomOpenRouterModel = null; // string | null
let currentOpenRouterProvider = ''; // string
let currentOpenRouterProviderOnly = false; // bool
let _openrouterCombobox = null; // model combobox instance
let _openrouterProviderCombobox = null; // provider combobox instance
let _orModelsCache = null; // cached model list
let _orEndpointsCache = {}; // modelId -> [provider slugs]
let currentDeepSeekModel = DEEPSEEK_MODEL_V4_PRO;
let _landingListenersAttached = false;

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
  if (provider === 'deepseek' && sourceType === 'youtube') return false;
  return provider === 'gemini' || provider === 'openrouter' || provider === 'deepseek';
}

export function isValidOpenRouterModel(model) {
  return model === OPENROUTER_MODEL_MIMO_PRO || model === OPENROUTER_MODEL_MIMO || model === OPENROUTER_MODEL_DEEPSEEK_V4_PRO;
}

export function isPresetOpenRouterModel(model) {
  return model === OPENROUTER_MODEL_MIMO_PRO || model === OPENROUTER_MODEL_MIMO || model === OPENROUTER_MODEL_DEEPSEEK_V4_PRO;
}

export function setCustomOpenRouterModel(value) {
  currentCustomOpenRouterModel = value;
}

export function isValidTargetLanguage(language) {
  return SUPPORTED_TARGET_LANGUAGES.includes(language);
}

function setTargetLanguage(language) {
  currentTargetLanguage = isValidTargetLanguage(language) ? language : DEFAULT_TARGET_LANGUAGE;
  const targetLanguageSelect = $('target-language');
  if (targetLanguageSelect) targetLanguageSelect.value = currentTargetLanguage;
}

function openRouterModelLabel(model) {
  if (model === OPENROUTER_MODEL_MIMO) return 'Xiaomi MiMo V2.5';
  if (model === OPENROUTER_MODEL_DEEPSEEK_V4_PRO) return 'DeepSeek V4 Pro';
  return 'Xiaomi MiMo V2.5 Pro';
}

export function isValidDeepSeekModel(model) {
  return model === DEEPSEEK_MODEL_V4_PRO || model === DEEPSEEK_MODEL_V4_FLASH;
}

function deepSeekModelLabel(model) {
  if (model === DEEPSEEK_MODEL_V4_FLASH) return 'DeepSeek V4 Flash';
  return 'DeepSeek V4 Pro';
}

export function validateExplainerProviderSelection({
  sourceType,
  provider,
  hasGeminiKey,
  hasOpenRouterKey,
  hasMistralKey,
  hasDeepSeekKey = false,
  hasTavilyKey = false,
}) {
  if (!isExplainerProviderSupportedForSource(sourceType, provider)) {
    return 'Los vídeos de YouTube solo son compatibles con Gemini.';
  }

  if (provider === 'gemini' && !hasGeminiKey) {
    return 'Necesitas configurar tu API key de Gemini primero. Ve a Ajustes.';
  }

  if (provider === 'openrouter' && !hasGeminiKey) {
    return 'Necesitas configurar tu API key de Gemini. OpenRouter la sigue usando para pasos auxiliares de compatibilidad.';
  }

  if (provider === 'openrouter' && !hasOpenRouterKey) {
    return 'Necesitas configurar tu API key de OpenRouter para usar modelos OpenRouter en el explainer y los agentes auxiliares.';
  }

  if (provider === 'openrouter' && sourceType === 'pdf' && !hasMistralKey) {
    return 'Necesitas configurar tu API key de Mistral para usar OCR nativo en PDFs con OpenRouter.';
  }

  if (provider === 'deepseek' && !hasDeepSeekKey) {
    return 'Necesitas configurar tu API key de DeepSeek para usar DeepSeek directo.';
  }

  if (provider === 'deepseek' && !hasTavilyKey) {
    return 'Necesitas configurar tu API key de Tavily para que DeepSeek pueda verificar recursos con búsqueda web.';
  }

  if (provider === 'deepseek' && sourceType === 'pdf' && !hasMistralKey) {
    return 'Necesitas configurar tu API key de Mistral para usar OCR nativo en PDFs con DeepSeek.';
  }

  return null;
}

function buildExplainerProviderHint(sourceType, provider) {
  if (sourceType === 'youtube') {
    return 'Los vídeos de YouTube usan siempre Gemini.';
  }

  if (provider === 'openrouter') {
    if (currentOpenRouterMode === 'custom') {
      return 'Modelo personalizado activo. Elige un modelo de OpenRouter.';
    }
    const modelLabel = openRouterModelLabel(currentOpenRouterModel);
    if (sourceType === 'pdf') {
      if (state.hasOpenRouterKey && state.hasMistralKey) {
        return `La explicación usará ${modelLabel} vía OpenRouter. Segmentación, recorrido, recursos y formateo usarán DeepSeek V4 Flash vía OpenRouter; recursos tendrá búsqueda web. El OCR de PDFs usará Mistral nativo.`;
      }
      if (!state.hasMistralKey) {
        return `Para PDFs con ${modelLabel} necesitas guardar también tu API key de Mistral para el OCR nativo.`;
      }
    }
    if (state.hasOpenRouterKey) {
      return `La explicación usará ${modelLabel} vía OpenRouter. Segmentación, recorrido, recursos y formateo usarán DeepSeek V4 Flash vía OpenRouter; recursos tendrá búsqueda web.`;
    }
    return `${modelLabel} está disponible para PDF y web, pero primero necesitas guardar tu API key de OpenRouter. Gemini sigue siendo obligatorio por compatibilidad del flujo OpenRouter.`;
  }

  if (provider === 'deepseek') {
    const modelLabel = deepSeekModelLabel(currentDeepSeekModel);
    if (sourceType === 'pdf') {
      if (state.hasDeepSeekKey && state.hasTavilyKey && state.hasMistralKey) {
        return `La explicación usará ${modelLabel} directamente en DeepSeek con razonamiento máximo. Segmentación, recorrido, recursos y formateo usarán DeepSeek V4 Flash; recursos verificará con Tavily y el OCR de PDFs usará Mistral.`;
      }
      if (!state.hasMistralKey) {
        return `Para PDFs con ${modelLabel} necesitas guardar también tu API key de Mistral para el OCR nativo.`;
      }
      if (!state.hasTavilyKey) {
        return `Para DeepSeek directo necesitas Tavily para las búsquedas de recursos.`;
      }
    }
    if (state.hasDeepSeekKey && state.hasTavilyKey) {
      return `La explicación usará ${modelLabel} directamente en DeepSeek con razonamiento máximo. Segmentación, recorrido, recursos y formateo usarán DeepSeek V4 Flash; recursos verificará con Tavily.`;
    }
    return `${modelLabel} está disponible para PDF y web, pero primero necesitas guardar tus API keys de DeepSeek y Tavily.`;
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
  const targetLanguageSelect = $('target-language');
  const providerGemini = $('explainer-provider-gemini');
  const providerOpenRouter = $('explainer-provider-openrouter');
  const providerDeepSeek = $('explainer-provider-deepseek');
  const modelPro = $('openrouter-model-pro');
  const modelStandard = $('openrouter-model-standard');
  const modelDeepseek = $('openrouter-model-deepseek');
  const modelPanel = $('openrouter-model-panel');
  const openRouterCustomRadio = $('openrouter-model-custom');
  const openRouterCustomPanel = $('openrouter-custom-panel');
  const openRouterProviderCombobox = $('openrouter-provider-combobox');
  const openRouterProviderOnlyCheckbox = $('openrouter-provider-only');
  const openRouterCustomLoading = $('openrouter-custom-loading');
  const openRouterCustomFetchError = $('openrouter-custom-fetch-error');
  const openRouterCustomModelError = $('openrouter-custom-model-error');
  const openRouterProviderFetchError = $('openrouter-provider-fetch-error');
  const deepseekModelPro = $('deepseek-model-pro');
  const deepseekModelFlash = $('deepseek-model-flash');
  const deepseekModelPanel = $('deepseek-model-panel');
  const providerHint = $('explainer-provider-hint');
  const providerError = $('explainer-provider-error');

  // Initialize provider combobox (empty; populated when model is selected)
  _openrouterProviderCombobox = createCombobox(openRouterProviderCombobox, {
    placeholder: 'Selecciona un modelo primero…',
    items: [],
    onSelect() {
      hide(openRouterProviderFetchError);
    },
    emptyText: 'No hay proveedores disponibles',
  });

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
    const deepSeekSupported = isExplainerProviderSupportedForSource(currentSourceType, 'deepseek');
    if (!openRouterSupported && currentExplainerProvider === 'openrouter') {
      currentExplainerProvider = 'gemini';
    }
    if (!deepSeekSupported && currentExplainerProvider === 'deepseek') {
      currentExplainerProvider = 'gemini';
    }

    providerGemini.checked = currentExplainerProvider === 'gemini';
    providerOpenRouter.checked = currentExplainerProvider === 'openrouter';
    providerDeepSeek.checked = currentExplainerProvider === 'deepseek';
    providerOpenRouter.disabled = !openRouterSupported;
    providerDeepSeek.disabled = !deepSeekSupported;

    $('provider-card-gemini').classList.toggle('selected', currentExplainerProvider === 'gemini');
    $('provider-card-openrouter').classList.toggle('selected', currentExplainerProvider === 'openrouter');
    $('provider-card-deepseek').classList.toggle('selected', currentExplainerProvider === 'deepseek');
    $('provider-card-openrouter').classList.toggle('disabled', !openRouterSupported);
    $('provider-card-deepseek').classList.toggle('disabled', !deepSeekSupported);
    modelPanel.classList.toggle('hidden', currentExplainerProvider !== 'openrouter' || !openRouterSupported);
    deepseekModelPanel.classList.toggle('hidden', currentExplainerProvider !== 'deepseek' || !deepSeekSupported);
    modelPro.checked = currentOpenRouterModel === OPENROUTER_MODEL_MIMO_PRO && currentOpenRouterMode === 'preset';
    modelStandard.checked = currentOpenRouterModel === OPENROUTER_MODEL_MIMO && currentOpenRouterMode === 'preset';
    modelDeepseek.checked = currentOpenRouterModel === OPENROUTER_MODEL_DEEPSEEK_V4_PRO && currentOpenRouterMode === 'preset';
    openRouterCustomRadio.checked = currentOpenRouterMode === 'custom';
    if (currentOpenRouterMode === 'custom') {
      openRouterCustomPanel.classList.remove('hidden');
      $('openrouter-model-card-pro').classList.remove('selected');
      $('openrouter-model-card-standard').classList.remove('selected');
      $('openrouter-model-card-deepseek').classList.remove('selected');
      $('openrouter-model-card-custom').classList.add('selected');
    } else {
      openRouterCustomPanel.classList.add('hidden');
      hide(openRouterCustomModelError);
      hide(openRouterCustomFetchError);
      $('openrouter-model-card-custom').classList.remove('selected');
      $('openrouter-model-card-pro').classList.toggle('selected', currentOpenRouterModel === OPENROUTER_MODEL_MIMO_PRO);
      $('openrouter-model-card-standard').classList.toggle('selected', currentOpenRouterModel === OPENROUTER_MODEL_MIMO);
      $('openrouter-model-card-deepseek').classList.toggle('selected', currentOpenRouterModel === OPENROUTER_MODEL_DEEPSEEK_V4_PRO);
    }
    deepseekModelPro.checked = currentDeepSeekModel === DEEPSEEK_MODEL_V4_PRO;
    deepseekModelFlash.checked = currentDeepSeekModel === DEEPSEEK_MODEL_V4_FLASH;
    $('deepseek-model-card-pro').classList.toggle('selected', currentDeepSeekModel === DEEPSEEK_MODEL_V4_PRO);
    $('deepseek-model-card-flash').classList.toggle('selected', currentDeepSeekModel === DEEPSEEK_MODEL_V4_FLASH);

    providerHint.textContent = buildExplainerProviderHint(currentSourceType, currentExplainerProvider);
    clearProviderError();
  }

  function setExplainerProvider(provider) {
    currentExplainerProvider = provider;
    syncExplainerProviderUI();
  }

  function setOpenRouterModel(model) {
    if (model === '__custom__') {
      currentOpenRouterMode = 'custom';
      currentOpenRouterModel = OPENROUTER_MODEL_MIMO_PRO; // keep a valid fallback
      syncExplainerProviderUI();
      // Lazily load models and init combobox
      loadOpenRouterModels().then((models) => {
        if (_openrouterCombobox) {
          _openrouterCombobox.destroy();
          _openrouterCombobox = null;
        }
        const mountEl = $('openrouter-custom-model-combobox');
        _openrouterCombobox = createCombobox(mountEl, {
          placeholder: 'Busca un modelo de OpenRouter…',
          items: models.map((m) => ({
            value: m.id || m.value || m,
            label: m.name || m.label || m,
            sublabel: m.id || m.value || '',
          })),
          onSelect(value) {
            currentCustomOpenRouterModel = value;
            hide(openRouterCustomModelError);
            // Reset and auto-populate provider combobox for this model
            if (_openrouterProviderCombobox) {
              _openrouterProviderCombobox.setValue('');
              _openrouterProviderCombobox.setItems([]);
            }
            hide(openRouterProviderFetchError);
            fetchEndpointsForModel(value);
          },
          getItemLabel(item) {
            return item.label + ' ' + (item.sublabel || '');
          },
          emptyText: 'No se encontraron modelos',
        });
      });
      return;
    }
    if (!isValidOpenRouterModel(model)) return;
    currentOpenRouterMode = 'preset';
    currentOpenRouterModel = model;
    if (_openrouterCombobox) {
      _openrouterCombobox.destroy();
      _openrouterCombobox = null;
    }
    // Reset provider combobox when switching away from custom
    if (_openrouterProviderCombobox) {
      _openrouterProviderCombobox.setValue('');
      _openrouterProviderCombobox.setItems([]);
    }
    hide(openRouterProviderFetchError);
    syncExplainerProviderUI();
  }

  function setDeepSeekModel(model) {
    if (!isValidDeepSeekModel(model)) return;
    currentDeepSeekModel = model;
    syncExplainerProviderUI();
  }

  async function loadOpenRouterModels() {
    if (_orModelsCache) return _orModelsCache;
    show(openRouterCustomLoading);
    try {
      const data = await api('/api/openrouter/models');
      _orModelsCache = data.models || [];
      return _orModelsCache;
    } catch (err) {
      show(openRouterCustomFetchError);
      openRouterCustomFetchError.textContent = 'No se pudieron cargar los modelos. Escribe el ID manualmente.';
      return [];
    } finally {
      hide(openRouterCustomLoading);
    }
  }

  /** Format provider slug into a human-readable label. */
  function formatProviderLabel(slug) {
    return slug.charAt(0).toUpperCase() + slug.slice(1).replace(/-/g, ' ');
  }

  /**
   * Fetch available providers for a model and populate the provider combobox.
   * Falls back gracefully — user can always type a provider manually.
   */
  async function fetchEndpointsForModel(modelId) {
    if (!modelId || !_openrouterProviderCombobox) return;
    if (_orEndpointsCache[modelId]) {
      _openrouterProviderCombobox.setItems(formatProviderItems(_orEndpointsCache[modelId]));
      return;
    }
    try {
      const data = await api(`/api/openrouter/models/endpoints?model=${encodeURIComponent(modelId)}`);
      const providers = data.providers || [];
      _orEndpointsCache[modelId] = providers;
      _openrouterProviderCombobox.setItems(formatProviderItems(providers));
    } catch (err) {
      // Non-blocking: user can still type a provider manually
      show(openRouterProviderFetchError);
      openRouterProviderFetchError.textContent = 'No se pudieron cargar los proveedores disponibles. Escríbelo manualmente.';
    }
  }

  function formatProviderItems(providers) {
    return providers.map((p) => ({
      value: p,
      label: formatProviderLabel(p),
      sublabel: p,
      meta: p,
    }));
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

  if (!_landingListenersAttached) {
    _landingListenersAttached = true;

    tabPdf.addEventListener('click', () => switchSourceType('pdf'));
    tabYoutube.addEventListener('click', () => switchSourceType('youtube'));
    tabWeb.addEventListener('click', () => switchSourceType('web'));
    providerGemini.addEventListener('change', () => {
      if (providerGemini.checked) setExplainerProvider('gemini');
    });
    providerOpenRouter.addEventListener('change', () => {
      if (providerOpenRouter.checked) setExplainerProvider('openrouter');
    });
    providerDeepSeek.addEventListener('change', () => {
      if (providerDeepSeek.checked) setExplainerProvider('deepseek');
    });
    modelPro.addEventListener('change', () => {
      if (modelPro.checked) setOpenRouterModel(OPENROUTER_MODEL_MIMO_PRO);
    });
    modelStandard.addEventListener('change', () => {
      if (modelStandard.checked) setOpenRouterModel(OPENROUTER_MODEL_MIMO);
    });
    modelDeepseek.addEventListener('change', () => {
      if (modelDeepseek.checked) setOpenRouterModel(OPENROUTER_MODEL_DEEPSEEK_V4_PRO);
    });
    if (targetLanguageSelect) {
      setTargetLanguage(targetLanguageSelect.value || DEFAULT_TARGET_LANGUAGE);
      targetLanguageSelect.addEventListener('change', () => setTargetLanguage(targetLanguageSelect.value));
    }
    deepseekModelPro.addEventListener('change', () => {
      if (deepseekModelPro.checked) setDeepSeekModel(DEEPSEEK_MODEL_V4_PRO);
    });
    deepseekModelFlash.addEventListener('change', () => {
      if (deepseekModelFlash.checked) setDeepSeekModel(DEEPSEEK_MODEL_V4_FLASH);
    });
    openRouterCustomRadio.addEventListener('change', () => {
      if (openRouterCustomRadio.checked) setOpenRouterModel('__custom__');
    });
    openRouterProviderOnlyCheckbox.addEventListener('change', (e) => {
      currentOpenRouterProviderOnly = e.target.checked;
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
  }

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
    hasDeepSeekKey: state.hasDeepSeekKey,
    hasTavilyKey: state.hasTavilyKey,
  });
  if (providerValidationError) {
    providerError.textContent = providerValidationError;
    show(providerError);
    showSettings();
    return;
  }

  // Custom model validation: block submit before creating project
  if (currentExplainerProvider === 'openrouter' && currentOpenRouterMode === 'custom' && !currentCustomOpenRouterModel) {
    show($('openrouter-custom-model-error'));
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
    const processPayload = { explainer_provider: currentExplainerProvider, target_language: currentTargetLanguage };
    setTargetLanguage(DEFAULT_TARGET_LANGUAGE);
    if (currentExplainerProvider === 'openrouter') {
      if (currentOpenRouterMode === 'custom') {
        processPayload.openrouter_model = currentCustomOpenRouterModel;
        const providerVal = _openrouterProviderCombobox
          ? _openrouterProviderCombobox.getValue().trim()
          : '';
        if (providerVal) {
          processPayload.openrouter_provider = providerVal;
          processPayload.openrouter_provider_only = currentOpenRouterProviderOnly;
        }
      } else {
        processPayload.openrouter_model = currentOpenRouterModel;
      }
      // Reset custom state after upload
      currentOpenRouterMode = 'preset';
      currentCustomOpenRouterModel = null;
      currentOpenRouterProviderOnly = false;
      if (_openrouterProviderCombobox) {
        _openrouterProviderCombobox.setValue('');
        _openrouterProviderCombobox.setItems([]);
      }
      hide($('openrouter-provider-fetch-error'));
    } else if (currentExplainerProvider === 'deepseek') {
      processPayload.deepseek_model = currentDeepSeekModel;
    }

    await api(`/api/projects/${project.id}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(processPayload),
    });

    if (window.pushRoute) window.pushRoute({ view: 'project', projectId: project.id });

  } catch (err) {
    errEl.textContent = err.message;
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = 'Iniciar análisis';
  }
}
