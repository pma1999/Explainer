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
  invalidateProjectsCache,
} from './storage.js';
import { getPreferOffline, setPreferOffline } from './pwa.js';

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
  } catch (_) {
    if (cached === null && state.apiKeyStatus === 'loading') state.apiKeyStatus = 'none';
    if (cachedOR === null && state.openRouterKeyStatus === 'loading') state.openRouterKeyStatus = 'none';
    if (cachedMistral === null && state.mistralKeyStatus === 'loading') state.mistralKeyStatus = 'none';
    if (cachedDeepSeek === null && state.deepSeekKeyStatus === 'loading') state.deepSeekKeyStatus = 'none';
    if (cachedTavily === null && state.tavilyKeyStatus === 'loading') state.tavilyKeyStatus = 'none';
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

  syncPreferOfflineSwitchUI();
}

export function showSettings() {
  $('settings-email').textContent = state.user?.email || '—';
  updateApiKeyUI();
  syncPreferOfflineSwitchUI();
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
}
