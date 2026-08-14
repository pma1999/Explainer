/* ============================================================
   EXPLAINER — Landing View & Upload
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, formatBytes, toast } from './dom.js';
import { api } from './api.js';
import { createCombobox } from './components/openrouter-combobox.js';
import { invalidateProjectsCache, loadBackupAsync, mergeProjects, syncProjectsToBackup } from './storage.js';
import { updateApiKeyUI, showSettings, unlinkCodexAccount } from './auth.js';

let selectedFile = null;
let currentSourceType = 'pdf';
let currentExplainerProvider = 'gemini';
let currentTargetLanguage = 'es-ES';
export const OPENROUTER_MODEL_MIMO_PRO = 'xiaomi/mimo-v2.5-pro';
export const OPENROUTER_MODEL_MIMO = 'xiaomi/mimo-v2.5';
export const OPENROUTER_MODEL_DEEPSEEK_V4_FLASH = 'deepseek/deepseek-v4-flash-0731';
export const DEFAULT_TARGET_LANGUAGE = 'es-ES';
export const SUPPORTED_TARGET_LANGUAGES = ['es-ES', 'en', 'fr', 'de', 'it', 'pt-PT'];
export const DEEPSEEK_MODEL_V4_PRO = 'deepseek-v4-pro';
export const DEEPSEEK_MODEL_V4_FLASH = 'deepseek-v4-flash';
export const CODEX_EFFORT_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max'];
export const CODEX_DEFAULT_EFFORT = 'medium';
let currentOpenRouterModel = OPENROUTER_MODEL_MIMO_PRO;
let currentOpenRouterMode = 'preset'; // 'preset' | 'custom'
let currentCustomOpenRouterModel = null; // string | null
let currentCustomOpenRouterModelMeta = null; // chosen model object (aggregate metadata) | null
let currentOpenRouterProvider = ''; // endpoint tag or manual typed text (canonical routing key)
let currentOpenRouterProviderEndpoint = null; // endpoint row matched by tag, or null for manual text
let currentOpenRouterProviderOnly = false; // bool
let _openrouterCombobox = null; // model combobox instance
let _openrouterProviderCombobox = null; // provider combobox instance
let _orModelsCache = null; // cached model list
let _orEndpointsCache = {}; // modelId -> [endpoint row objects]
let currentDeepSeekModel = DEEPSEEK_MODEL_V4_PRO;
let currentCodexEffort = CODEX_DEFAULT_EFFORT;
let _landingListenersAttached = false;

const SELECTOR_KEY = 'explainer.modelSelector.v1';

const PROJECT_NAME_PLACEHOLDER = 'Ej: Are Prisons Obsolete — Davis';
const AUTO_TITLE_PLACEHOLDER = 'La IA decidirá el título';
const AUTO_TITLE_FIELD_ID = 'project-autotitle';

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
  if (provider === 'codex' && sourceType === 'youtube') return false;
  return provider === 'gemini' || provider === 'openrouter' || provider === 'deepseek' || provider === 'codex';
}

export function isValidOpenRouterModel(model) {
  return model === OPENROUTER_MODEL_MIMO_PRO || model === OPENROUTER_MODEL_MIMO || model === OPENROUTER_MODEL_DEEPSEEK_V4_FLASH;
}

export function isPresetOpenRouterModel(model) {
  return model === OPENROUTER_MODEL_MIMO_PRO || model === OPENROUTER_MODEL_MIMO || model === OPENROUTER_MODEL_DEEPSEEK_V4_FLASH;
}

export function setCustomOpenRouterModel(value) {
  currentCustomOpenRouterModel = value;
}

export function isValidTargetLanguage(language) {
  return SUPPORTED_TARGET_LANGUAGES.includes(language);
}

/**
 * Read-only access to the user's currently selected target language.
 * The module keeps the mutable value private; consumers (e.g. the Repaso
 * agent) read it through this getter so selection logic stays in one place.
 */
export function getTargetLanguage() {
  return currentTargetLanguage;
}

/**
 * Current provider/model selection for the Repaso agent (body fallback).
 * The backend prefers the persisted `explainer_config` (exact provider/model
 * used for the part's explainer); these fields are only used when the project
 * predates that persistence (existing projects) or was processed without it.
 * Mirrors the processPayload built on project creation (upload flow).
 */
export function getReviewProviderConfig() {
  const config = { explainer_provider: currentExplainerProvider };
  if (currentExplainerProvider === 'openrouter') {
    config.openrouter_model = currentOpenRouterMode === 'custom'
      ? (currentCustomOpenRouterModel || currentOpenRouterModel)
      : currentOpenRouterModel;
  } else if (currentExplainerProvider === 'deepseek') {
    config.deepseek_model = currentDeepSeekModel;
  }
  return config;
}

function setTargetLanguage(language) {
  currentTargetLanguage = isValidTargetLanguage(language) ? language : DEFAULT_TARGET_LANGUAGE;
  const targetLanguageSelect = $('target-language');
  if (targetLanguageSelect) targetLanguageSelect.value = currentTargetLanguage;
}

function openRouterModelLabel(model) {
  if (model === OPENROUTER_MODEL_MIMO) return 'Xiaomi MiMo V2.5';
  if (model === OPENROUTER_MODEL_DEEPSEEK_V4_FLASH) return 'DeepSeek V4 Flash';
  return 'Xiaomi MiMo V2.5 Pro';
}

/**
 * Format a per-token USD price as a readable badge string.
 * Returns 'Gratis' when the price is exactly 0; otherwise '$<N>/1M'
 * where N = perTokenUsd * 1e6 rendered to 2 significant figures.
 * @param {number} perTokenUsd
 * @returns {string}
 */
export function formatModelPrice(perTokenUsd) {
  if (perTokenUsd === 0) return 'Gratis';
  const perMillion = perTokenUsd * 1e6;
  // 2 significant figures; parseFloat strips trailing zeros
  const formatted = parseFloat(perMillion.toPrecision(2)).toString();
  return `$${formatted}/1M`;
}

/**
 * Format a context length in tokens as a readable 'NNK ctx' badge.
 * Returns '' for falsy input (0 / undefined / null).
 * @param {number|undefined} n
 * @returns {string}
 */
export function formatContextLength(n) {
  if (!n) return '';
  return `${Math.round(n / 1000)}K ctx`;
}

/**
 * Format an endpoint max-token limit as a 'NNK <suffix>' badge.
 * Returns '' for absent/non-finite/non-positive values so the UI never
 * shows a misleading zero-token limit.
 * @param {number|undefined} n
 * @param {string} suffix - e.g. 'max out' or 'max in'
 * @returns {string}
 */
function formatMaxTokens(n, suffix) {
  if (!n || typeof n !== 'number' || !Number.isFinite(n) || n <= 0) return '';
  return `${Math.round(n / 1000)}K ${suffix}`;
}

/**
 * Build the endpoint input/output price segment ('$/1M in · $/1M out').
 * Returns '' when the endpoint row lacks both a positive prompt and
 * completion price, so absent pricing is never labelled as exact.
 * @param {{prompt_price?:number, completion_price?:number}} endpoint
 * @returns {string}
 */
function formatEndpointPriceSegment(endpoint) {
  const inPrice = endpoint && endpoint.prompt_price;
  const outPrice = endpoint && endpoint.completion_price;
  const hasIn = typeof inPrice === 'number' && Number.isFinite(inPrice) && inPrice > 0;
  const hasOut = typeof outPrice === 'number' && Number.isFinite(outPrice) && outPrice > 0;
  if (!hasIn && !hasOut) return '';
  return `${formatModelPrice(inPrice ?? 0)} in · ${formatModelPrice(outPrice ?? 0)} out`;
}

/**
 * Format a single endpoint row into the combobox `meta` slot string:
 * context, max completion tokens, max prompt tokens, and endpoint prices,
 * joining only the segments that are present.
 * @param {object} endpoint
 * @returns {string}
 */
export function formatEndpointMeta(endpoint) {
  if (!endpoint) return '';
  const parts = [];
  const ctx = formatContextLength(endpoint.context_length);
  if (ctx) parts.push(ctx);
  const maxOut = formatMaxTokens(endpoint.max_completion_tokens, 'max out');
  if (maxOut) parts.push(maxOut);
  const maxIn = formatMaxTokens(endpoint.max_prompt_tokens, 'max in');
  if (maxIn) parts.push(maxIn);
  const price = formatEndpointPriceSegment(endpoint);
  if (price) parts.push(price);
  return parts.join(' · ');
}

/**
 * Build the exact-mode summary chip texts for a selected endpoint row.
 * Returns only the chips whose underlying value is present; pricing is
 * omitted entirely when the endpoint lacks both a positive prompt and
 * completion price, so absent pricing never appears as an exact chip.
 * @param {object} endpoint
 * @returns {string[]}
 */
export function buildEndpointSummaryChips(endpoint) {
  if (!endpoint) return [];
  const chips = [];
  const name = endpoint.provider_name || endpoint.tag;
  if (name) chips.push(name);
  if (endpoint.tag) chips.push(endpoint.tag);
  const ctx = formatContextLength(endpoint.context_length);
  if (ctx) chips.push(ctx);
  const maxOut = formatMaxTokens(endpoint.max_completion_tokens, 'max out');
  if (maxOut) chips.push(maxOut);
  const maxIn = formatMaxTokens(endpoint.max_prompt_tokens, 'max in');
  if (maxIn) chips.push(maxIn);
  const price = formatEndpointPriceSegment(endpoint);
  if (price) chips.push(price);
  return chips;
}

export function isValidDeepSeekModel(model) {
  return model === DEEPSEEK_MODEL_V4_PRO || model === DEEPSEEK_MODEL_V4_FLASH;
}

/**
 * Write current model-selector state to localStorage.
 * Wrapped in try/catch — storage may throw in private mode or on quota exceeded.
 */
export function persistModelSelector() {
  try {
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: currentExplainerProvider,
      openrouterMode: currentOpenRouterMode,
      openrouterModel: currentOpenRouterModel,
      customOpenrouterModel: currentCustomOpenRouterModel,
      openrouterProvider: currentOpenRouterProvider,
      openrouterProviderOnly: currentOpenRouterProviderOnly,
      deepseekModel: currentDeepSeekModel,
      codexEffort: currentCodexEffort,
    }));
  } catch (_) {
    // Ignore write failures (private mode, quota exceeded, etc.)
  }
}

/**
 * Read + validate model-selector state from localStorage and apply it to module vars.
 * Never throws — corrupt / missing data results in a no-op (defaults remain).
 * Validates every field before applying; falls back to safe defaults when invalid.
 * Returns `{ pendingCustomModel, pendingProvider }` when a custom-mode async restore
 * is needed (caller must drive `setOpenRouterModel('__custom__')` + the post-load step),
 * otherwise returns null.
 *
 * @returns {{ pendingCustomModel: string, pendingProvider: string } | null}
 */
export function restoreModelSelector() {
  let saved;
  try {
    const raw = localStorage.getItem(SELECTOR_KEY);
    if (!raw) return null;
    saved = JSON.parse(raw);
  } catch (_) {
    return null; // corrupt / missing JSON — no-op
  }
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return null;

  // --- explainerProvider ---
  const validProviders = ['gemini', 'openrouter', 'deepseek', 'codex'];
  let provider = validProviders.includes(saved.explainerProvider) ? saved.explainerProvider : 'gemini';

  // Key-availability fallback (primary key only — submit-time validates full set)
  if (provider === 'openrouter' && !state.hasOpenRouterKey) provider = 'gemini';
  if (provider === 'deepseek' && !state.hasDeepSeekKey) provider = 'gemini';
  if (provider === 'codex' && !state.hasCodexLink) provider = 'gemini';
  // Source-type fallback (default source is 'pdf'; re-checked after source switches)
  if (!isExplainerProviderSupportedForSource(currentSourceType, provider)) provider = 'gemini';
  currentExplainerProvider = provider;

  // --- deepseekModel ---
  currentDeepSeekModel = isValidDeepSeekModel(saved.deepseekModel)
    ? saved.deepseekModel
    : DEEPSEEK_MODEL_V4_PRO;

  // --- codexEffort (absent / invalid / non-string → default) ---
  currentCodexEffort = CODEX_EFFORT_LEVELS.includes(saved.codexEffort)
    ? saved.codexEffort
    : CODEX_DEFAULT_EFFORT;

  // --- openrouterProviderOnly (coerce to boolean) ---
  currentOpenRouterProviderOnly = Boolean(saved.openrouterProviderOnly);

  // --- openrouterProvider ---
  currentOpenRouterProvider = typeof saved.openrouterProvider === 'string'
    ? saved.openrouterProvider
    : '';

  // --- openrouterMode + model ---
  const validModes = ['preset', 'custom'];
  const mode = validModes.includes(saved.openrouterMode) ? saved.openrouterMode : 'preset';

  if (mode === 'custom'
      && typeof saved.customOpenrouterModel === 'string'
      && saved.customOpenrouterModel) {
    // Signal to initLanding: drive the async custom-mode restore
    currentOpenRouterMode = 'custom';
    currentOpenRouterModel = OPENROUTER_MODEL_MIMO_PRO; // safe fallback while loading
    currentCustomOpenRouterModel = null; // set after combobox is ready
    return { pendingCustomModel: saved.customOpenrouterModel, pendingProvider: currentOpenRouterProvider };
  }

  // Preset or custom-with-no-model → apply preset
  const orModel = isPresetOpenRouterModel(saved.openrouterModel)
    ? saved.openrouterModel
    : OPENROUTER_MODEL_MIMO_PRO;
  currentOpenRouterMode = 'preset';
  currentOpenRouterModel = orModel;
  currentCustomOpenRouterModel = null;
  return null;
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
  hasCodexLink = false,
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

  if (provider === 'codex' && !hasCodexLink) {
    return 'Vincula tu cuenta ChatGPT en Ajustes para usar Codex.';
  }

  if (provider === 'codex' && sourceType === 'pdf' && !hasMistralKey) {
    return 'Necesitas configurar tu API key de Mistral para usar OCR en PDFs con Codex.';
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

  if (provider === 'codex') {
    if (sourceType === 'pdf' && !state.hasMistralKey) {
      return 'Para PDFs con Codex necesitas guardar también tu API key de Mistral para el OCR nativo.';
    }
    if (!state.hasCodexLink) {
      return 'Usa GPT-5.6 Luna con la cuota de tu plan ChatGPT. Primero vincula tu cuenta ChatGPT en Ajustes.';
    }
    return 'Usa GPT-5.6 Luna con la cuota de tu plan ChatGPT. Segmentación, recorrido, recursos y formateo seguirán usando Codex.';
  }

  return 'La explicación usará Gemini. Segmentación, recorrido, recursos y formateo seguirán usando Gemini.';
}

/**
 * Render the custom-mode model summary into #openrouter-custom-model-summary.
 * Shows `Proveedor exacto` + endpoint-specific data when an endpoint row is
 * matched by tag; otherwise `Modelo (agregado)` + model-list aggregate data.
 * No-op when no custom model meta is set (summary stays hidden).
 */
function renderCustomModelSummary() {
  const el = $('openrouter-custom-model-summary');
  if (!el) return;
  const modelMeta = currentCustomOpenRouterModelMeta;
  if (!modelMeta) {
    hide(el);
    return;
  }
  el.innerHTML = '';

  const nameSpan = document.createElement('span');
  nameSpan.className = 'model-summary-name';
  nameSpan.textContent = modelMeta.name || modelMeta.label || currentCustomOpenRouterModel || '';
  el.appendChild(nameSpan);

  const labelChip = document.createElement('span');
  labelChip.className = 'model-summary-chip model-summary-chip--label';
  const endpoint = currentOpenRouterProviderEndpoint;
  if (endpoint) {
    labelChip.textContent = 'Proveedor exacto';
    el.appendChild(labelChip);
    for (const text of buildEndpointSummaryChips(endpoint)) {
      const chip = document.createElement('span');
      chip.className = 'model-summary-chip';
      chip.textContent = text;
      el.appendChild(chip);
    }
  } else {
    labelChip.textContent = 'Modelo (agregado)';
    el.appendChild(labelChip);
    const idChip = document.createElement('span');
    idChip.className = 'model-summary-chip';
    idChip.textContent = modelMeta.id || currentCustomOpenRouterModel || '';
    el.appendChild(idChip);
    const ctx = formatContextLength(modelMeta.context_length);
    if (ctx) {
      const ctxChip = document.createElement('span');
      ctxChip.className = 'model-summary-chip';
      ctxChip.textContent = ctx;
      el.appendChild(ctxChip);
    }
    const priceChip = document.createElement('span');
    priceChip.className = 'model-summary-chip';
    const priceIn = formatModelPrice(modelMeta.prompt_price ?? 0);
    const priceOut = formatModelPrice(modelMeta.completion_price ?? 0);
    priceChip.textContent = `${priceIn} in · ${priceOut} out`;
    el.appendChild(priceChip);
  }
  show(el);
}

export function initLanding() {
  updateApiKeyUI();

  const zone = $('upload-zone');
  const fileInput = $('file-input');
  const btnUpload = $('btn-upload');
  const nameInput = $('project-name');
  const descInput = $('project-description');
  const autoTitleCheckbox = $(AUTO_TITLE_FIELD_ID);
  const youtubeUrlInput = $('youtube-url');
  const webUrlInput = $('web-url');
  const targetLanguageSelect = $('target-language');
  const providerGemini = $('explainer-provider-gemini');
  const providerOpenRouter = $('explainer-provider-openrouter');
  const providerDeepSeek = $('explainer-provider-deepseek');
  const providerCodex = $('explainer-provider-codex');
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
  const codexModelPanel = $('codex-model-panel');
  const codexPanelBtnLink = $('codex-panel-btn-link');
  const codexPanelBtnUnlink = $('codex-panel-btn-unlink');
  const codexEffortGroup = $('codex-effort-group');
  const codexEffortLow = $('codex-effort-low');
  const codexEffortMedium = $('codex-effort-medium');
  const codexEffortHigh = $('codex-effort-high');
  const codexEffortXhigh = $('codex-effort-xhigh');
  const codexEffortMax = $('codex-effort-max');
  const providerHint = $('explainer-provider-hint');
  const providerError = $('explainer-provider-error');

  // Initialize provider combobox (empty; populated when model is selected)
  _openrouterProviderCombobox = createCombobox(openRouterProviderCombobox, {
    placeholder: 'Selecciona un modelo primero…',
    items: [],
    onSelect(value, item) {
      // value is the canonical endpoint tag (routing key); the displayed
      // label is provider_name. Persist the tag, not the display label.
      currentOpenRouterProvider = value;
      currentOpenRouterProviderEndpoint = (item && item.endpoint) || null;
      hide(openRouterProviderFetchError);
      renderCustomModelSummary();
      persistModelSelector();
    },
    emptyText: 'No hay proveedores disponibles',
  });

  // Manual-edit guard (Named Risk): if the user types into the provider
  // input instead of picking an option, clear any previously selected
  // endpoint metadata and treat the current text as manual provider text.
  // Programmatic setValue() (option commit, restore) sets input.value
  // directly and does NOT fire an `input` event, so selections are safe.
  const providerComboboxInput = openRouterProviderCombobox.querySelector('input');
  if (providerComboboxInput) {
    providerComboboxInput.addEventListener('input', () => {
      currentOpenRouterProviderEndpoint = null;
      currentOpenRouterProvider = providerComboboxInput.value;
      renderCustomModelSummary();
      persistModelSelector();
    });
  }

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

  function providerNeedsKey(provider) {
    if (provider === 'gemini') {
      return state.hasApiKey ? null : 'Falta API key de Gemini — configúrala en Ajustes';
    }
    if (provider === 'openrouter') {
      if (!state.hasOpenRouterKey) return 'Falta API key de OpenRouter — configúrala en Ajustes';
      if (!state.hasApiKey) return 'Falta API key de Gemini (auxiliar) — configúrala en Ajustes';
      return null;
    }
    if (provider === 'deepseek') {
      return state.hasDeepSeekKey ? null : 'Falta API key de DeepSeek — configúrala en Ajustes';
    }
    return null;
  }

  function syncExplainerProviderUI() {
    const openRouterSupported = isExplainerProviderSupportedForSource(currentSourceType, 'openrouter');
    const deepSeekSupported = isExplainerProviderSupportedForSource(currentSourceType, 'deepseek');
    const codexSupported = isExplainerProviderSupportedForSource(currentSourceType, 'codex');
    if (!openRouterSupported && currentExplainerProvider === 'openrouter') {
      currentExplainerProvider = 'gemini';
    }
    if (!deepSeekSupported && currentExplainerProvider === 'deepseek') {
      currentExplainerProvider = 'gemini';
    }
    if (!codexSupported && currentExplainerProvider === 'codex') {
      currentExplainerProvider = 'gemini';
    }

    providerGemini.checked = currentExplainerProvider === 'gemini';
    providerOpenRouter.checked = currentExplainerProvider === 'openrouter';
    providerDeepSeek.checked = currentExplainerProvider === 'deepseek';
    providerCodex.checked = currentExplainerProvider === 'codex';
    providerOpenRouter.disabled = !openRouterSupported;
    providerDeepSeek.disabled = !deepSeekSupported;
    providerCodex.disabled = !codexSupported;

    $('provider-card-gemini').classList.toggle('selected', currentExplainerProvider === 'gemini');
    $('provider-card-openrouter').classList.toggle('selected', currentExplainerProvider === 'openrouter');
    $('provider-card-deepseek').classList.toggle('selected', currentExplainerProvider === 'deepseek');
    $('provider-card-codex').classList.toggle('selected', currentExplainerProvider === 'codex');
    $('provider-card-openrouter').classList.toggle('disabled', !openRouterSupported);
    $('provider-card-deepseek').classList.toggle('disabled', !deepSeekSupported);
    $('provider-card-codex').classList.toggle('disabled', !codexSupported);
    modelPanel.classList.toggle('hidden', currentExplainerProvider !== 'openrouter' || !openRouterSupported);
    deepseekModelPanel.classList.toggle('hidden', currentExplainerProvider !== 'deepseek' || !deepSeekSupported);
    codexModelPanel.classList.toggle('hidden', currentExplainerProvider !== 'codex' || !codexSupported);
    modelPro.checked = currentOpenRouterModel === OPENROUTER_MODEL_MIMO_PRO && currentOpenRouterMode === 'preset';
    modelStandard.checked = currentOpenRouterModel === OPENROUTER_MODEL_MIMO && currentOpenRouterMode === 'preset';
    modelDeepseek.checked = currentOpenRouterModel === OPENROUTER_MODEL_DEEPSEEK_V4_FLASH && currentOpenRouterMode === 'preset';
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
      $('openrouter-model-card-deepseek').classList.toggle('selected', currentOpenRouterModel === OPENROUTER_MODEL_DEEPSEEK_V4_FLASH);
    }
    deepseekModelPro.checked = currentDeepSeekModel === DEEPSEEK_MODEL_V4_PRO;
    deepseekModelFlash.checked = currentDeepSeekModel === DEEPSEEK_MODEL_V4_FLASH;
    $('deepseek-model-card-pro').classList.toggle('selected', currentDeepSeekModel === DEEPSEEK_MODEL_V4_PRO);
    $('deepseek-model-card-flash').classList.toggle('selected', currentDeepSeekModel === DEEPSEEK_MODEL_V4_FLASH);

    codexEffortLow.checked = currentCodexEffort === 'low';
    codexEffortMedium.checked = currentCodexEffort === 'medium';
    codexEffortHigh.checked = currentCodexEffort === 'high';
    codexEffortXhigh.checked = currentCodexEffort === 'xhigh';
    codexEffortMax.checked = currentCodexEffort === 'max';
    $('codex-effort-card-low').classList.toggle('selected', currentCodexEffort === 'low');
    $('codex-effort-card-medium').classList.toggle('selected', currentCodexEffort === 'medium');
    $('codex-effort-card-high').classList.toggle('selected', currentCodexEffort === 'high');
    $('codex-effort-card-xhigh').classList.toggle('selected', currentCodexEffort === 'xhigh');
    $('codex-effort-card-max').classList.toggle('selected', currentCodexEffort === 'max');

    providerHint.textContent = buildExplainerProviderHint(currentSourceType, currentExplainerProvider);

    const geminiMsg = providerNeedsKey('gemini');
    $('provider-card-gemini').classList.toggle('needs-key', geminiMsg !== null);
    $('provider-card-gemini-status').textContent = geminiMsg || '';

    const openRouterMsg = providerNeedsKey('openrouter');
    $('provider-card-openrouter').classList.toggle('needs-key', openRouterMsg !== null);
    $('provider-card-openrouter-status').textContent = openRouterMsg || '';

    const deepSeekMsg = providerNeedsKey('deepseek');
    $('provider-card-deepseek').classList.toggle('needs-key', deepSeekMsg !== null);
    $('provider-card-deepseek-status').textContent = deepSeekMsg || '';

    clearProviderError();
  }

  function setExplainerProvider(provider) {
    currentExplainerProvider = provider;
    syncExplainerProviderUI();
    persistModelSelector();
  }

  function setOpenRouterModel(model) {
    if (model === '__custom__') {
      currentOpenRouterMode = 'custom';
      currentOpenRouterModel = OPENROUTER_MODEL_MIMO_PRO; // keep a valid fallback
      syncExplainerProviderUI();
      // Hide stale summary while loading a fresh combobox
      const summaryEl = $('openrouter-custom-model-summary');
      if (summaryEl) hide(summaryEl);
      // Loading affordance on the card while the fetch is in flight
      const customCard = $('openrouter-model-card-custom');
      if (customCard) customCard.classList.add('is-loading');
      // Lazily load models and init combobox; return the promise so initLanding can chain off it
      return loadOpenRouterModels().then((models) => {
        if (customCard) customCard.classList.remove('is-loading');
        // Teardown-race guard: bail if user has since left custom mode or mount is gone
        if (currentOpenRouterMode !== 'custom') return;
        const mountEl = $('openrouter-custom-model-combobox');
        if (!mountEl || !document.body.contains(mountEl)) return;
        if (_openrouterCombobox) {
          _openrouterCombobox.destroy();
          _openrouterCombobox = null;
        }
        _openrouterCombobox = createCombobox(mountEl, {
          placeholder: 'Busca un modelo de OpenRouter…',
          items: models.map((m) => ({
            value: m.id || m.value || m,
            label: m.name || m.label || m,
            sublabel: m.id || m.value || '',
            meta: [
              formatContextLength(m.context_length),
              m.prompt_price !== undefined ? formatModelPrice(m.prompt_price) : '',
            ].filter(Boolean).join(' · '),
          })),
          onSelect(value) {
            currentCustomOpenRouterModel = value;
            hide(openRouterCustomModelError);
            // Cache chosen model aggregate metadata for summary rendering
            const chosen = models.find((m) => (m.id || m.value || m) === value);
            currentCustomOpenRouterModelMeta = chosen || null;
            // Reset provider state for the newly chosen model
            currentOpenRouterProvider = '';
            currentOpenRouterProviderEndpoint = null;
            if (_openrouterProviderCombobox) {
              _openrouterProviderCombobox.setValue('');
              _openrouterProviderCombobox.setItems([]);
            }
            hide(openRouterProviderFetchError);
            // Render aggregate summary (no endpoint selected yet)
            renderCustomModelSummary();
            fetchEndpointsForModel(value);
            persistModelSelector();
          },
          getItemLabel(item) {
            return item.label + ' ' + (item.sublabel || '');
          },
          emptyText: 'No se encontraron modelos',
        });
      }); // return value exits the if-block
    }
    if (!isValidOpenRouterModel(model)) return;
    currentOpenRouterMode = 'preset';
    currentOpenRouterModel = model;
    currentCustomOpenRouterModel = null;
    currentCustomOpenRouterModelMeta = null;
    currentOpenRouterProvider = '';
    currentOpenRouterProviderEndpoint = null;
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
    persistModelSelector();
  }

  function setDeepSeekModel(model) {
    if (!isValidDeepSeekModel(model)) return;
    currentDeepSeekModel = model;
    syncExplainerProviderUI();
    persistModelSelector();
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

  /**
   * Fetch available provider endpoints for a model and populate the provider
   * combobox. Caches endpoint row objects keyed by model id. Falls back
   * gracefully — user can always type a provider manually.
   * Returns the endpoint rows (cached or freshly fetched), or [] on error.
   * @param {string} modelId
   * @returns {Promise<object[]>}
   */
  async function fetchEndpointsForModel(modelId) {
    if (!modelId || !_openrouterProviderCombobox) return [];
    if (_orEndpointsCache[modelId]) {
      const cached = _orEndpointsCache[modelId];
      _openrouterProviderCombobox.setItems(formatProviderItems(cached));
      return cached;
    }
    try {
      const data = await api(`/api/openrouter/models/endpoints?model=${encodeURIComponent(modelId)}`);
      const endpoints = Array.isArray(data && data.endpoints) ? data.endpoints : [];
      _orEndpointsCache[modelId] = endpoints;
      _openrouterProviderCombobox.setItems(formatProviderItems(endpoints));
      return endpoints;
    } catch (err) {
      // Non-blocking: user can still type a provider manually
      show(openRouterProviderFetchError);
      openRouterProviderFetchError.textContent = 'No se pudieron cargar los proveedores disponibles. Escríbelo manualmente.';
      return [];
    }
  }

  /**
   * Map endpoint rows into provider combobox items. The canonical routing
   * key (`tag`) is the item value; `provider_name` is the display label.
   * @param {object[]} endpoints
   * @returns {Array<{value:string, label:string, sublabel:string, meta:string, endpoint:object}>}
   */
  function formatProviderItems(endpoints) {
    return (endpoints || []).map((endpoint) => ({
      value: endpoint.tag,
      label: endpoint.provider_name || endpoint.tag,
      sublabel: endpoint.tag,
      meta: formatEndpointMeta(endpoint),
      endpoint,
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
    providerCodex.addEventListener('change', () => {
      if (providerCodex.checked) setExplainerProvider('codex');
    });
    if (codexPanelBtnLink) {
      codexPanelBtnLink.addEventListener('click', showSettings);
    }
    if (codexPanelBtnUnlink) {
      codexPanelBtnUnlink.addEventListener('click', unlinkCodexAccount);
    }
    modelPro.addEventListener('change', () => {
      if (modelPro.checked) setOpenRouterModel(OPENROUTER_MODEL_MIMO_PRO);
    });
    modelStandard.addEventListener('change', () => {
      if (modelStandard.checked) setOpenRouterModel(OPENROUTER_MODEL_MIMO);
    });
    modelDeepseek.addEventListener('change', () => {
      if (modelDeepseek.checked) setOpenRouterModel(OPENROUTER_MODEL_DEEPSEEK_V4_FLASH);
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
    if (codexEffortGroup) {
      codexEffortGroup.addEventListener('change', (e) => {
        if (e.target && CODEX_EFFORT_LEVELS.includes(e.target.value)) {
          currentCodexEffort = e.target.value;
          syncExplainerProviderUI();
          persistModelSelector();
        }
      });
    }
    openRouterCustomRadio.addEventListener('change', () => {
      if (openRouterCustomRadio.checked) setOpenRouterModel('__custom__');
    });
    openRouterProviderOnlyCheckbox.addEventListener('change', (e) => {
      currentOpenRouterProviderOnly = e.target.checked;
      persistModelSelector();
    });

    function checkReady() {
      const hasName = nameInput.value.trim() || (autoTitleCheckbox && autoTitleCheckbox.checked);
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

    if (autoTitleCheckbox) {
      autoTitleCheckbox.addEventListener('change', () => {
        if (autoTitleCheckbox.checked) {
          nameInput.value = '';
          nameInput.disabled = true;
          nameInput.placeholder = AUTO_TITLE_PLACEHOLDER;
        } else {
          nameInput.disabled = false;
          nameInput.placeholder = PROJECT_NAME_PLACEHOLDER;
        }
        validateForm();
        checkReady();
      });
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

  // T6: Restore persisted model-selector state, validate, then apply.
  // For custom mode, drive the async load + combobox setup after models arrive.
  const _customRestore = restoreModelSelector();
  if (_customRestore && currentExplainerProvider === 'openrouter') {
    const { pendingCustomModel, pendingProvider } = _customRestore;
    const _loadPromise = setOpenRouterModel('__custom__');
    if (_loadPromise && typeof _loadPromise.then === 'function') {
      _loadPromise.then(async () => {
        // Teardown-race guard (mirrors T5): bail if user switched mode while models loaded
        if (currentOpenRouterMode !== 'custom') return;
        const mountEl = $('openrouter-custom-model-combobox');
        if (!mountEl || !document.body.contains(mountEl)) return;
        // Resolve display label from cached models list if available
        const loadedModel = _orModelsCache &&
          _orModelsCache.find((m) => (m.id || m.value || m) === pendingCustomModel);
        const displayVal = (loadedModel && (loadedModel.name || loadedModel.label)) || pendingCustomModel;
        if (_openrouterCombobox) _openrouterCombobox.setValue(displayVal);
        currentCustomOpenRouterModel = pendingCustomModel;
        currentCustomOpenRouterModelMeta = loadedModel || null;
        // Refetch endpoint rows so the saved provider can be re-matched by tag
        // (do not trust stale display metadata from localStorage).
        const endpoints = await fetchEndpointsForModel(pendingCustomModel);
        // Teardown-race guard: bail if user left custom mode while endpoints loaded
        if (currentOpenRouterMode !== 'custom') return;
        const matched = pendingProvider && Array.isArray(endpoints)
          ? endpoints.find((ep) => ep && ep.tag === pendingProvider)
          : null;
        if (matched) {
          // Re-matched by tag: show provider_name in the input, persist the tag,
          // and render endpoint-specific summary chips.
          currentOpenRouterProvider = matched.tag;
          currentOpenRouterProviderEndpoint = matched;
          if (_openrouterProviderCombobox) {
            _openrouterProviderCombobox.setValue(matched.provider_name || matched.tag);
          }
        } else if (pendingProvider) {
          // Saved tag is not in the endpoint rows: restore as manual text and
          // keep the summary on aggregate model chips.
          currentOpenRouterProvider = pendingProvider;
          currentOpenRouterProviderEndpoint = null;
          if (_openrouterProviderCombobox) {
            _openrouterProviderCombobox.setValue(pendingProvider);
          }
        } else {
          currentOpenRouterProvider = '';
          currentOpenRouterProviderEndpoint = null;
        }
        renderCustomModelSummary();
        // Restore provider-only checkbox state
        if (openRouterProviderOnlyCheckbox) {
          openRouterProviderOnlyCheckbox.checked = currentOpenRouterProviderOnly;
        }
        persistModelSelector();
      });
    }
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
  const autoTitleChecked = (($(AUTO_TITLE_FIELD_ID)) || {}).checked;
  const hasName = nameInput.value.trim() || autoTitleChecked;

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
  const autotitle = (($(AUTO_TITLE_FIELD_ID)) || {}).checked;
  const name = autotitle ? '' : $('project-name').value.trim();
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
    hasCodexLink: state.hasCodexLink,
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
    if (autotitle) fd.append('auto_title', 'true');

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
    if (autotitle) {
      const autoTitleEl = $(AUTO_TITLE_FIELD_ID);
      if (autoTitleEl) autoTitleEl.checked = false;
      $('project-name').disabled = false;
      $('project-name').placeholder = PROJECT_NAME_PLACEHOLDER;
    }
    $('project-description').value = '';
    $('youtube-url').value = '';
    $('web-url').value = '';
    const processPayload = { explainer_provider: currentExplainerProvider, target_language: currentTargetLanguage };
    setTargetLanguage(DEFAULT_TARGET_LANGUAGE);
    if (currentExplainerProvider === 'openrouter') {
      if (currentOpenRouterMode === 'custom') {
        processPayload.openrouter_model = currentCustomOpenRouterModel;
        // currentOpenRouterProvider holds the canonical endpoint tag when an
        // endpoint row is selected, or the manual typed text otherwise. The
        // combobox's getValue() returns the display label (provider_name),
        // which is not a valid routing key, so we submit the stored value.
        if (currentOpenRouterProvider) {
          processPayload.openrouter_provider = currentOpenRouterProvider;
          processPayload.openrouter_provider_only = currentOpenRouterProviderOnly;
        }
      } else {
        processPayload.openrouter_model = currentOpenRouterModel;
      }
      // Reset custom state after upload
      currentOpenRouterMode = 'preset';
      currentCustomOpenRouterModel = null;
      currentCustomOpenRouterModelMeta = null;
      currentOpenRouterProvider = '';
      currentOpenRouterProviderEndpoint = null;
      currentOpenRouterProviderOnly = false;
      if (_openrouterProviderCombobox) {
        _openrouterProviderCombobox.setValue('');
        _openrouterProviderCombobox.setItems([]);
      }
      hide($('openrouter-provider-fetch-error'));
    } else if (currentExplainerProvider === 'deepseek') {
      processPayload.deepseek_model = currentDeepSeekModel;
    } else if (currentExplainerProvider === 'codex') {
      processPayload.codex_effort = currentCodexEffort;
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
