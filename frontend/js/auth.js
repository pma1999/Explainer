/* ============================================================
   EXPLAINER — Auth & Settings
   ============================================================ */

import {
  state,
  supabaseClient,
  getRememberSessionPreference,
  setRememberSessionPreference,
} from './state.js';
import { $, show, hide, showView, toast } from './dom.js';
import { api } from './api.js';
import {
  getCachedApiKeyStatus,
  setCachedApiKeyStatus,
  getCachedOpenRouterKeyStatus,
  setCachedOpenRouterKeyStatus,
  getCachedMistralKeyStatus,
  setCachedMistralKeyStatus,
  getCachedDeepSeekKeyStatus,
  setCachedDeepSeekKeyStatus,
  getCachedTavilyKeyStatus,
  setCachedTavilyKeyStatus,
  getCachedCodexLinkStatus,
  setCachedCodexLinkStatus,
  invalidateProjectsCache,
} from './storage.js';
import { getPreferOffline, setPreferOffline } from './pwa.js';

const CODEX_POLL_INTERVAL_MS = 3000;
const CODEX_POLL_MAX_MS = 10 * 60 * 1000;
let _codexPollTimer = null;
let _codexPollEndsAt = 0;
let _codexLastError = null;

function _stopCodexPolling() {
  if (_codexPollTimer !== null) {
    clearInterval(_codexPollTimer);
    _codexPollTimer = null;
  }
}

function _startCodexPolling() {
  _stopCodexPolling();
  _codexPollTimer = setInterval(_pollCodexLinkStatus, CODEX_POLL_INTERVAL_MS);
}

function _cacheCodexLinkState(userId) {
  setCachedCodexLinkStatus(userId, {
    hasCodexLink: state.hasCodexLink,
    codexStatus: state.codexLinkStatus,
    codexPlanType: state.codexPlanType,
  });
}

async function _pollCodexLinkStatus() {
  if (Date.now() > _codexPollEndsAt) {
    _stopCodexPolling();
    state.hasCodexLink = false;
    state.codexLinkStatus = 'failed';
    _codexLastError = 'El vínculo caducó. Vuelve a iniciarlo.';
    _cacheCodexLinkState(state.user?.id);
    updateApiKeyUI();
    return;
  }

  let data;
  try {
    data = await api('/api/settings/codex-link/status');
  } catch (_) {
    // Transient network failure: keep polling until the deadline.
    return;
  }

  if (data.codex_status === 'linked') {
    _stopCodexPolling();
    state.hasCodexLink = true;
    state.codexLinkStatus = 'linked';
    state.codexPlanType = typeof data.codex_plan_type === 'string' && data.codex_plan_type ? data.codex_plan_type : null;
    _codexLastError = null;
    _cacheCodexLinkState(state.user?.id);
    hide($('codex-device-panel'));
    updateApiKeyUI();
    toast('Cuenta ChatGPT vinculada', 'success');
  } else if (data.codex_status === 'failed') {
    _stopCodexPolling();
    state.hasCodexLink = false;
    state.codexLinkStatus = 'failed';
    _codexLastError = typeof data.last_error === 'string' && data.last_error
      ? data.last_error
      : 'El vínculo falló. Vuelve a iniciarlo.';
    _cacheCodexLinkState(state.user?.id);
    hide($('codex-device-panel'));
    updateApiKeyUI();
  } else if (data.codex_status === 'none') {
    // The pending flow no longer exists server-side (e.g. cancelled elsewhere).
    _stopCodexPolling();
    state.hasCodexLink = false;
    state.codexLinkStatus = 'none';
    _codexLastError = null;
    _cacheCodexLinkState(state.user?.id);
    hide($('codex-device-panel'));
    updateApiKeyUI();
  }
  // 'pending' → keep polling
}

export async function startCodexLink() {
  _stopCodexPolling();
  const btn = $('btn-start-codex-link');
  const spinner = btn ? btn.querySelector('.spinner') : null;
  const btnText = btn ? btn.querySelector('.btn-text') : null;
  const errEl = $('codex-link-error');
  if (errEl) {
    errEl.textContent = '';
    hide(errEl);
  }
  if (btn) btn.disabled = true;
  if (spinner) show(spinner);
  if (btnText) btnText.textContent = 'Iniciando…';

  try {
    const data = await api('/api/settings/codex-link/start', { method: 'POST' });

    const urlEl = $('codex-verification-url');
    if (urlEl) {
      urlEl.href = data.verification_url || '';
      urlEl.textContent = data.verification_url || '';
    }
    const codeInput = $('codex-user-code');
    if (codeInput) codeInput.value = data.user_code || '';

    const expiresInMs = Number.isFinite(Number(data.expires_in)) && Number(data.expires_in) > 0
      ? Number(data.expires_in) * 1000
      : CODEX_POLL_MAX_MS;
    _codexPollEndsAt = Date.now() + Math.min(expiresInMs, CODEX_POLL_MAX_MS);

    state.hasCodexLink = false;
    state.codexLinkStatus = 'pending';
    _codexLastError = null;
    _cacheCodexLinkState(state.user?.id);
    show($('codex-device-panel'));
    updateApiKeyUI();
    _startCodexPolling();
    toast('Completa el vínculo en la web de ChatGPT', 'success');
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      show(errEl);
    }
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) hide(spinner);
    if (btnText) btnText.textContent = 'Vincular cuenta ChatGPT';
  }
}

export async function cancelCodexLink() {
  const errEl = $('codex-link-error');
  try {
    await api('/api/settings/codex-link/cancel', { method: 'POST' });
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      show(errEl);
    }
    return;
  }
  _stopCodexPolling();
  state.hasCodexLink = false;
  state.codexLinkStatus = 'none';
  _codexLastError = null;
  _cacheCodexLinkState(state.user?.id);
  hide($('codex-device-panel'));
  updateApiKeyUI();
  toast('Vínculo cancelado', 'success');
}

export async function unlinkCodexAccount() {
  if (!confirm('¿Desvincular tu cuenta de ChatGPT?')) return;
  const errEl = $('codex-link-error');
  if (errEl) {
    errEl.textContent = '';
    hide(errEl);
  }
  try {
    await api('/api/settings/codex-link', { method: 'DELETE' });
    _stopCodexPolling();
    state.hasCodexLink = false;
    state.codexLinkStatus = 'none';
    state.codexPlanType = null;
    _codexLastError = null;
    _cacheCodexLinkState(state.user?.id);
    updateApiKeyUI();
    toast('Cuenta ChatGPT desvinculada', 'success');
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      show(errEl);
    }
  }
}

async function copyCodexUserCode() {
  const codeInput = $('codex-user-code');
  const code = codeInput ? codeInput.value : '';
  const btn = $('btn-copy-codex-code');
  const btnText = btn ? btn.querySelector('.btn-text') : null;
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code);
    if (btnText) btnText.textContent = '¡Copiado!';
    toast('Código copiado', 'success');
    setTimeout(() => {
      if (btnText) btnText.textContent = 'Copiar';
    }, 1500);
  } catch (_) {
    toast('No se pudo copiar el código', 'error');
  }
}

export async function refreshApiKeyStatus() {
  const userId = state.user?.id;
  if (!userId) return;

  // Seed from cache before network call
  const cached = getCachedApiKeyStatus(userId);
  if (cached !== null) {
    state.hasApiKey = cached;
    state.apiKeyStatus = cached ? 'has' : 'none';
  } else {
    state.apiKeyStatus = 'loading';
  }

  const cachedOR = getCachedOpenRouterKeyStatus(userId);
  if (cachedOR !== null) {
    state.hasOpenRouterKey = cachedOR;
    state.openRouterKeyStatus = cachedOR ? 'has' : 'none';
  } else {
    state.openRouterKeyStatus = 'loading';
  }

  const cachedMistral = getCachedMistralKeyStatus(userId);
  if (cachedMistral !== null) {
    state.hasMistralKey = cachedMistral;
    state.mistralKeyStatus = cachedMistral ? 'has' : 'none';
  } else {
    state.mistralKeyStatus = 'loading';
  }

  const cachedDeepSeek = getCachedDeepSeekKeyStatus(userId);
  if (cachedDeepSeek !== null) {
    state.hasDeepSeekKey = cachedDeepSeek;
    state.deepSeekKeyStatus = cachedDeepSeek ? 'has' : 'none';
  } else {
    state.deepSeekKeyStatus = 'loading';
  }

  const cachedTavily = getCachedTavilyKeyStatus(userId);
  if (cachedTavily !== null) {
    state.hasTavilyKey = cachedTavily;
    state.tavilyKeyStatus = cachedTavily ? 'has' : 'none';
  } else {
    state.tavilyKeyStatus = 'loading';
  }

  const cachedCodex = getCachedCodexLinkStatus(userId);
  if (cachedCodex !== null) {
    state.hasCodexLink = cachedCodex.hasCodexLink;
    state.codexLinkStatus = cachedCodex.codexStatus;
    state.codexPlanType = cachedCodex.codexPlanType;
  } else {
    state.codexLinkStatus = 'loading';
    state.codexPlanType = null;
  }

  updateApiKeyUI();

  try {
    const status = await api('/api/settings/api-key/status');

    state.hasApiKey = Boolean(status.has_api_key);
    state.apiKeyStatus = state.hasApiKey ? 'has' : 'none';
    setCachedApiKeyStatus(userId, state.hasApiKey);

    state.hasOpenRouterKey = Boolean(status.has_openrouter_key);
    state.openRouterKeyStatus = state.hasOpenRouterKey ? 'has' : 'none';
    setCachedOpenRouterKeyStatus(userId, state.hasOpenRouterKey);

    state.hasMistralKey = Boolean(status.has_mistral_key);
    state.mistralKeyStatus = state.hasMistralKey ? 'has' : 'none';
    setCachedMistralKeyStatus(userId, state.hasMistralKey);

    state.hasDeepSeekKey = Boolean(status.has_deepseek_key);
    state.deepSeekKeyStatus = state.hasDeepSeekKey ? 'has' : 'none';
    setCachedDeepSeekKeyStatus(userId, state.hasDeepSeekKey);

    state.hasTavilyKey = Boolean(status.has_tavily_key);
    state.tavilyKeyStatus = state.hasTavilyKey ? 'has' : 'none';
    setCachedTavilyKeyStatus(userId, state.hasTavilyKey);

    state.hasCodexLink = Boolean(status.has_codex_link);
    const codexStatuses = ['none', 'pending', 'linked', 'failed'];
    state.codexLinkStatus = codexStatuses.includes(status.codex_status)
      ? status.codex_status
      : (state.hasCodexLink ? 'linked' : 'none');
    state.codexPlanType = typeof status.codex_plan_type === 'string' && status.codex_plan_type
      ? status.codex_plan_type
      : null;
    _cacheCodexLinkState(userId);
  } catch (_) {
    if (cached === null && state.apiKeyStatus === 'loading') state.apiKeyStatus = 'none';
    if (cachedOR === null && state.openRouterKeyStatus === 'loading') state.openRouterKeyStatus = 'none';
    if (cachedMistral === null && state.mistralKeyStatus === 'loading') state.mistralKeyStatus = 'none';
    if (cachedDeepSeek === null && state.deepSeekKeyStatus === 'loading') state.deepSeekKeyStatus = 'none';
    if (cachedTavily === null && state.tavilyKeyStatus === 'loading') state.tavilyKeyStatus = 'none';
    if (cachedCodex === null && state.codexLinkStatus === 'loading') {
      state.codexLinkStatus = 'none';
      state.hasCodexLink = false;
    }
  }

  updateApiKeyUI();
}

function syncPreferOfflineSwitchUI() {
  const el = $('prefer-offline-switch');
  if (!el) return;
  const on = getPreferOffline();
  el.setAttribute('aria-checked', on ? 'true' : 'false');
  el.classList.toggle('is-on', on);
}

export function initSettings() {
  $('btn-settings').addEventListener('click', showSettings);
  $('btn-settings-projects').addEventListener('click', showSettings);
  $('btn-configure-api-key').addEventListener('click', showSettings);

  $('btn-close-settings').addEventListener('click', hideSettings);

  $('modal-settings').addEventListener('click', (e) => {
    if (e.target === $('modal-settings')) hideSettings();
  });

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
      state.apiKeyStatus = 'has';
      setCachedApiKeyStatus(state.user?.id, true);
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

  const preferOfflineSwitch = $('prefer-offline-switch');
  if (preferOfflineSwitch) {
    preferOfflineSwitch.addEventListener('click', () => {
      const next = !getPreferOffline();
      setPreferOffline(next);
      invalidateProjectsCache();
      syncPreferOfflineSwitchUI();
    });
  }

  $('btn-delete-api-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key de Gemini guardada?')) return;

    try {
      await api('/api/settings/api-key', { method: 'DELETE' });
      state.hasApiKey = false;
      state.apiKeyStatus = 'none';
      setCachedApiKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key de Gemini eliminada', 'success');
    } catch (err) {
      $('api-key-error').textContent = err.message;
    }
  });

  // ---- OpenRouter key ----

  $('form-openrouter-key').addEventListener('submit', async (e) => {
    e.preventDefault();
    const apiKey = $('openrouter-key-input').value.trim();

    if (!apiKey) {
      $('openrouter-key-error').textContent = 'Ingresa una API key de OpenRouter';
      return;
    }

    const btn = $('btn-save-openrouter-key');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('.btn-text');

    btn.disabled = true;
    show(spinner);
    btnText.textContent = 'Guardando...';
    $('openrouter-key-error').textContent = '';
    $('openrouter-key-success').textContent = '';

    try {
      const formData = new FormData();
      formData.append('api_key', apiKey);

      await api('/api/settings/api-key/openrouter', {
        method: 'POST',
        body: formData,
      });

      state.hasOpenRouterKey = true;
      state.openRouterKeyStatus = 'has';
      setCachedOpenRouterKeyStatus(state.user?.id, true);
      $('openrouter-key-input').value = '';
      $('openrouter-key-success').textContent = 'API key de OpenRouter guardada';
      updateApiKeyUI();
      toast('API key de OpenRouter guardada', 'success');
    } catch (err) {
      $('openrouter-key-error').textContent = err.message;
    } finally {
      btn.disabled = false;
      hide(spinner);
      btnText.textContent = 'Guardar API Key';
    }
  });

  $('btn-delete-openrouter-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key de OpenRouter guardada?')) return;

    try {
      await api('/api/settings/api-key/openrouter', { method: 'DELETE' });
      state.hasOpenRouterKey = false;
      state.openRouterKeyStatus = 'none';
      setCachedOpenRouterKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key de OpenRouter eliminada', 'success');
    } catch (err) {
      $('openrouter-key-error').textContent = err.message;
    }
  });

  // ---- DeepSeek key ----

  $('form-deepseek-key').addEventListener('submit', async (e) => {
    e.preventDefault();
    const apiKey = $('deepseek-key-input').value.trim();

    if (!apiKey) {
      $('deepseek-key-error').textContent = 'Ingresa una API key de DeepSeek';
      return;
    }

    const btn = $('btn-save-deepseek-key');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('.btn-text');

    btn.disabled = true;
    show(spinner);
    btnText.textContent = 'Guardando...';
    $('deepseek-key-error').textContent = '';
    $('deepseek-key-success').textContent = '';

    try {
      const formData = new FormData();
      formData.append('api_key', apiKey);

      await api('/api/settings/api-key/deepseek', {
        method: 'POST',
        body: formData,
      });

      state.hasDeepSeekKey = true;
      state.deepSeekKeyStatus = 'has';
      setCachedDeepSeekKeyStatus(state.user?.id, true);
      $('deepseek-key-input').value = '';
      $('deepseek-key-success').textContent = 'API key de DeepSeek guardada';
      updateApiKeyUI();
      toast('API key de DeepSeek guardada', 'success');
    } catch (err) {
      $('deepseek-key-error').textContent = err.message;
    } finally {
      btn.disabled = false;
      hide(spinner);
      btnText.textContent = 'Guardar API Key';
    }
  });

  $('btn-delete-deepseek-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key de DeepSeek guardada?')) return;

    try {
      await api('/api/settings/api-key/deepseek', { method: 'DELETE' });
      state.hasDeepSeekKey = false;
      state.deepSeekKeyStatus = 'none';
      setCachedDeepSeekKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key de DeepSeek eliminada', 'success');
    } catch (err) {
      $('deepseek-key-error').textContent = err.message;
    }
  });

  // ---- Tavily key ----

  $('form-tavily-key').addEventListener('submit', async (e) => {
    e.preventDefault();
    const apiKey = $('tavily-key-input').value.trim();

    if (!apiKey) {
      $('tavily-key-error').textContent = 'Ingresa una API key de Tavily';
      return;
    }

    const btn = $('btn-save-tavily-key');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('.btn-text');

    btn.disabled = true;
    show(spinner);
    btnText.textContent = 'Guardando...';
    $('tavily-key-error').textContent = '';
    $('tavily-key-success').textContent = '';

    try {
      const formData = new FormData();
      formData.append('api_key', apiKey);

      await api('/api/settings/api-key/tavily', {
        method: 'POST',
        body: formData,
      });

      state.hasTavilyKey = true;
      state.tavilyKeyStatus = 'has';
      setCachedTavilyKeyStatus(state.user?.id, true);
      $('tavily-key-input').value = '';
      $('tavily-key-success').textContent = 'API key de Tavily guardada';
      updateApiKeyUI();
      toast('API key de Tavily guardada', 'success');
    } catch (err) {
      $('tavily-key-error').textContent = err.message;
    } finally {
      btn.disabled = false;
      hide(spinner);
      btnText.textContent = 'Guardar API Key';
    }
  });

  $('btn-delete-tavily-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key de Tavily guardada?')) return;

    try {
      await api('/api/settings/api-key/tavily', { method: 'DELETE' });
      state.hasTavilyKey = false;
      state.tavilyKeyStatus = 'none';
      setCachedTavilyKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key de Tavily eliminada', 'success');
    } catch (err) {
      $('tavily-key-error').textContent = err.message;
    }
  });

  // ---- Mistral key ----

  $('form-mistral-key').addEventListener('submit', async (e) => {
    e.preventDefault();
    const apiKey = $('mistral-key-input').value.trim();
    if (!apiKey) {
      $('mistral-key-error').textContent = 'Ingresa una API key de Mistral';
      return;
    }

    const btn = $('btn-save-mistral-key');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('.btn-text');

    btn.disabled = true;
    show(spinner);
    btnText.textContent = 'Guardando...';
    $('mistral-key-error').textContent = '';
    $('mistral-key-success').textContent = '';

    try {
      const formData = new FormData();
      formData.append('api_key', apiKey);

      await api('/api/settings/api-key/mistral', {
        method: 'POST',
        body: formData,
      });

      state.hasMistralKey = true;
      state.mistralKeyStatus = 'has';
      setCachedMistralKeyStatus(state.user?.id, true);
      $('mistral-key-input').value = '';
      $('mistral-key-success').textContent = 'API key de Mistral guardada';
      updateApiKeyUI();
      toast('API key de Mistral guardada', 'success');
    } catch (err) {
      $('mistral-key-error').textContent = err.message;
    } finally {
      btn.disabled = false;
      hide(spinner);
      btnText.textContent = 'Guardar API Key';
    }
  });

  $('btn-delete-mistral-key').addEventListener('click', async () => {
    if (!confirm('¿Eliminar tu API key de Mistral guardada?')) return;

    try {
      await api('/api/settings/api-key/mistral', { method: 'DELETE' });
      state.hasMistralKey = false;
      state.mistralKeyStatus = 'none';
      setCachedMistralKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key de Mistral eliminada', 'success');
    } catch (err) {
      $('mistral-key-error').textContent = err.message;
    }
  });

  // ---- Codex (ChatGPT) link ----

  const codexStartBtn = $('btn-start-codex-link');
  if (codexStartBtn) codexStartBtn.addEventListener('click', startCodexLink);
  const codexCancelBtn = $('btn-cancel-codex-link');
  if (codexCancelBtn) codexCancelBtn.addEventListener('click', cancelCodexLink);
  const codexUnlinkBtn = $('btn-unlink-codex');
  if (codexUnlinkBtn) codexUnlinkBtn.addEventListener('click', unlinkCodexAccount);
  const codexCopyBtn = $('btn-copy-codex-code');
  if (codexCopyBtn) codexCopyBtn.addEventListener('click', copyCodexUserCode);

  syncPreferOfflineSwitchUI();
}

export function showSettings() {
  $('settings-email').textContent = state.user?.email || '—';
  updateApiKeyUI();
  syncPreferOfflineSwitchUI();
  // Resume a pending device-code flow with a fresh 10-minute window when the
  // modal is reopened (polling was stopped when the settings closed).
  if (state.codexLinkStatus === 'pending' && _codexPollTimer === null) {
    _codexPollEndsAt = Date.now() + CODEX_POLL_MAX_MS;
    _startCodexPolling();
  }
  show($('modal-settings'));
}

function syncRememberSessionInputs(remember = false) {
  const nextValue = Boolean(remember);
  const loginCheckbox = $('login-remember-session');
  const registerCheckbox = $('register-remember-session');
  if (loginCheckbox) loginCheckbox.checked = nextValue;
  if (registerCheckbox) registerCheckbox.checked = nextValue;
}

let _authInitialized = false;

export function initAuth(onNavigateFromRoute, onInitLanding) {
  if (_authInitialized) return;
  _authInitialized = true;

  const formLogin = $('form-login');
  const formRegister = $('form-register');
  const loginError = $('auth-login-error');
  const registerError = $('auth-register-error');
  const loginRemember = $('login-remember-session');
  const registerRemember = $('register-remember-session');

  syncRememberSessionInputs(getRememberSessionPreference() === true);

  [loginRemember, registerRemember].forEach((checkbox) => {
    if (!checkbox) return;
    checkbox.addEventListener('change', () => {
      syncRememberSessionInputs(checkbox.checked);
    });
  });

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
    const rememberSession = Boolean(loginRemember?.checked);
    if (!email || !password) {
      loginError.textContent = 'Completa email y contraseña';
      return;
    }
    const btn = $('btn-login');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = 'Entrando...';
    try {
      setRememberSessionPreference(rememberSession);
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
      if (error) throw error;
      state.session = data.session;
      state.user = data.user;
      const route = window.parseRoute ? window.parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        onNavigateFromRoute(route);
      } else {
        if (window.pushRoute) window.pushRoute({ view: 'landing' });
        onInitLanding();
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
    const rememberSession = Boolean(registerRemember?.checked);
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
      setRememberSessionPreference(rememberSession);
      const { data, error } = await supabaseClient.auth.signUp({ email, password });
      if (error) throw error;
      state.session = data.session;
      state.user = data.user;
      const route = window.parseRoute ? window.parseRoute() : null;
      if (route && (route.view === 'projects' || (route.view === 'project' && route.projectId))) {
        onNavigateFromRoute(route);
      } else {
        if (window.pushRoute) window.pushRoute({ view: 'landing' });
        onInitLanding();
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
    setRememberSessionPreference(false);
    syncRememberSessionInputs(false);
    state.session = null;
    state.user = null;
    hide($('modal-settings'));
    showView('view-auth');
    toast('Sesión cerrada', 'success');
  });
}

export function hideSettings() {
  _stopCodexPolling();
  hide($('modal-settings'));
  $('api-key-error').textContent = '';
  $('api-key-success').textContent = '';
  $('api-key-input').value = '';
  $('openrouter-key-error').textContent = '';
  $('openrouter-key-success').textContent = '';
  $('openrouter-key-input').value = '';
  $('mistral-key-error').textContent = '';
  $('mistral-key-success').textContent = '';
  $('mistral-key-input').value = '';
  $('deepseek-key-error').textContent = '';
  $('deepseek-key-success').textContent = '';
  $('deepseek-key-input').value = '';
  $('tavily-key-error').textContent = '';
  $('tavily-key-success').textContent = '';
  $('tavily-key-input').value = '';
  $('codex-link-error').textContent = '';
  hide($('codex-link-error'));
}

export function updateApiKeyUI() {
  // Gemini key UI
  const isLoading = state.apiKeyStatus === 'loading';

  if (state.hasApiKey) {
    hide($('api-key-not-set'));
    show($('api-key-set'));
    $('btn-delete-api-key').style.display = 'inline-block';
  } else if (isLoading) {
    hide($('api-key-not-set'));
    hide($('api-key-set'));
    $('btn-delete-api-key').style.display = 'none';
  } else {
    show($('api-key-not-set'));
    hide($('api-key-set'));
    $('btn-delete-api-key').style.display = 'none';
  }

  if (state.apiKeyStatus === 'none' && !state.hasDeepSeekKey) {
    show($('api-key-warning'));
  } else {
    hide($('api-key-warning'));
  }

  // OpenRouter key UI
  const orLoading = state.openRouterKeyStatus === 'loading';

  if (state.hasOpenRouterKey) {
    hide($('openrouter-key-not-set'));
    show($('openrouter-key-set'));
    $('btn-delete-openrouter-key').style.display = 'inline-block';
  } else if (orLoading) {
    hide($('openrouter-key-not-set'));
    hide($('openrouter-key-set'));
    $('btn-delete-openrouter-key').style.display = 'none';
  } else {
    show($('openrouter-key-not-set'));
    hide($('openrouter-key-set'));
    $('btn-delete-openrouter-key').style.display = 'none';
  }

  // Mistral key UI
  const mistralLoading = state.mistralKeyStatus === 'loading';

  if (state.hasMistralKey) {
    hide($('mistral-key-not-set'));
    show($('mistral-key-set'));
    $('btn-delete-mistral-key').style.display = 'inline-block';
  } else if (mistralLoading) {
    hide($('mistral-key-not-set'));
    hide($('mistral-key-set'));
    $('btn-delete-mistral-key').style.display = 'none';
  } else {
    show($('mistral-key-not-set'));
    hide($('mistral-key-set'));
    $('btn-delete-mistral-key').style.display = 'none';
  }

  // DeepSeek key UI
  const deepSeekLoading = state.deepSeekKeyStatus === 'loading';

  if (state.hasDeepSeekKey) {
    hide($('deepseek-key-not-set'));
    show($('deepseek-key-set'));
    $('btn-delete-deepseek-key').style.display = 'inline-block';
  } else if (deepSeekLoading) {
    hide($('deepseek-key-not-set'));
    hide($('deepseek-key-set'));
    $('btn-delete-deepseek-key').style.display = 'none';
  } else {
    show($('deepseek-key-not-set'));
    hide($('deepseek-key-set'));
    $('btn-delete-deepseek-key').style.display = 'none';
  }

  // Tavily key UI
  const tavilyLoading = state.tavilyKeyStatus === 'loading';

  if (state.hasTavilyKey) {
    hide($('tavily-key-not-set'));
    show($('tavily-key-set'));
    $('btn-delete-tavily-key').style.display = 'inline-block';
  } else if (tavilyLoading) {
    hide($('tavily-key-not-set'));
    hide($('tavily-key-set'));
    $('btn-delete-tavily-key').style.display = 'none';
  } else {
    show($('tavily-key-not-set'));
    hide($('tavily-key-set'));
    $('btn-delete-tavily-key').style.display = 'none';
  }

  // Codex (ChatGPT) link UI — settings section
  const codexStatus = state.codexLinkStatus;
  const codexSetText = $('codex-link-set-text');
  const codexFailedText = $('codex-link-failed-text');

  if (codexStatus === 'linked') {
    show($('codex-link-set'));
    hide($('codex-link-not-set'));
    hide($('codex-link-pending'));
    hide($('codex-link-failed'));
    if (codexSetText) {
      codexSetText.textContent = state.codexPlanType
        ? `Cuenta ChatGPT vinculada · plan ${state.codexPlanType}. Codex (GPT-5.6 Luna) queda disponible con la cuota incluida de tu plan.`
        : 'Cuenta ChatGPT vinculada. Codex (GPT-5.6 Luna) queda disponible con la cuota incluida de tu plan.';
    }
    $('btn-start-codex-link').style.display = 'none';
    $('btn-unlink-codex').style.display = 'inline-block';
    hide($('codex-device-panel'));
  } else if (codexStatus === 'pending') {
    show($('codex-link-pending'));
    hide($('codex-link-not-set'));
    hide($('codex-link-set'));
    hide($('codex-link-failed'));
    $('btn-start-codex-link').style.display = 'none';
    $('btn-unlink-codex').style.display = 'none';
    // The device panel stays visible while the flow is in flight.
  } else if (codexStatus === 'failed') {
    show($('codex-link-failed'));
    hide($('codex-link-not-set'));
    hide($('codex-link-pending'));
    hide($('codex-link-set'));
    if (codexFailedText) {
      codexFailedText.textContent = _codexLastError || 'El vínculo falló. Vuelve a iniciarlo.';
    }
    $('btn-start-codex-link').style.display = 'inline-block';
    $('btn-unlink-codex').style.display = 'none';
    hide($('codex-device-panel'));
  } else if (codexStatus === 'loading') {
    hide($('codex-link-not-set'));
    hide($('codex-link-pending'));
    hide($('codex-link-set'));
    hide($('codex-link-failed'));
    $('btn-start-codex-link').style.display = 'none';
    $('btn-unlink-codex').style.display = 'none';
  } else {
    show($('codex-link-not-set'));
    hide($('codex-link-pending'));
    hide($('codex-link-set'));
    hide($('codex-link-failed'));
    $('btn-start-codex-link').style.display = 'inline-block';
    $('btn-unlink-codex').style.display = 'none';
    hide($('codex-device-panel'));
  }

  // Codex card status point (selector) + inline sub-panel link status
  const codexStatusEl = $('provider-card-codex-status');
  if (codexStatusEl) {
    if (codexStatus === 'loading') {
      codexStatusEl.textContent = '';
    } else if (codexStatus === 'linked') {
      codexStatusEl.textContent = state.codexPlanType ? `Vinculada · ${state.codexPlanType}` : 'Vinculada';
    } else if (codexStatus === 'pending') {
      codexStatusEl.textContent = 'Vínculo pendiente — complétalo en Ajustes';
    } else {
      codexStatusEl.textContent = 'No vinculada — vincúlala en Ajustes';
    }
  }
  const codexCard = $('provider-card-codex');
  if (codexCard) {
    codexCard.classList.toggle('needs-key', codexStatus !== 'loading' && codexStatus !== 'linked');
  }

  const codexPanelLinkText = $('codex-panel-link-text');
  if (codexPanelLinkText) {
    if (codexStatus === 'loading') {
      codexPanelLinkText.textContent = '';
    } else if (codexStatus === 'linked') {
      codexPanelLinkText.textContent = state.codexPlanType ? `Vinculada · ${state.codexPlanType}` : 'Vinculada';
    } else if (codexStatus === 'pending') {
      codexPanelLinkText.textContent = 'Vínculo pendiente — complétalo en Ajustes';
    } else {
      codexPanelLinkText.textContent = 'No vinculada';
    }
  }
  const codexPanelBtnLink = $('codex-panel-btn-link');
  if (codexPanelBtnLink) {
    codexPanelBtnLink.style.display = codexStatus === 'linked' ? 'none' : 'inline-block';
  }
  const codexPanelBtnUnlink = $('codex-panel-btn-unlink');
  if (codexPanelBtnUnlink) {
    codexPanelBtnUnlink.style.display = codexStatus === 'linked' ? 'inline-block' : 'none';
  }
}
