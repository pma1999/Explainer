/* ============================================================
   EXPLAINER — Auth & Settings
   ============================================================ */

import { state, supabaseClient } from './state.js';
import { $, show, hide, showView, toast } from './dom.js';
import { api } from './api.js';
import { getCachedApiKeyStatus, setCachedApiKeyStatus, invalidateProjectsCache } from './storage.js';
import { getPreferOffline, setPreferOffline } from './pwa.js';

export async function refreshApiKeyStatus() {
  const userId = state.user?.id;
  const cached = getCachedApiKeyStatus(userId);
  if (cached !== null) {
    state.hasApiKey = cached;
    state.apiKeyStatus = cached ? 'has' : 'none';
    updateApiKeyUI();
  }

  try {
    const status = await api('/api/settings/api-key/status');
    state.hasApiKey = Boolean(status.has_api_key);
    state.apiKeyStatus = state.hasApiKey ? 'has' : 'none';
    setCachedApiKeyStatus(userId, state.hasApiKey);
  } catch (_) {
    state.hasApiKey = false;
    state.apiKeyStatus = 'none';
    setCachedApiKeyStatus(userId, false);
  }
  updateApiKeyUI();
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
    if (!confirm('¿Eliminar tu API key guardada?')) return;

    try {
      await api('/api/settings/api-key', { method: 'DELETE' });
      state.hasApiKey = false;
      state.apiKeyStatus = 'none';
      setCachedApiKeyStatus(state.user?.id, false);
      updateApiKeyUI();
      toast('API key eliminada', 'success');
    } catch (err) {
      $('api-key-error').textContent = err.message;
    }
  });

  syncPreferOfflineSwitchUI();
}

function syncPreferOfflineSwitchUI() {
  const el = $('prefer-offline-switch');
  if (!el) return;
  const on = getPreferOffline();
  el.setAttribute('aria-checked', on ? 'true' : 'false');
  el.classList.toggle('is-on', on);
}

export function showSettings() {
  $('settings-email').textContent = state.user?.email || '—';
  updateApiKeyUI();
  syncPreferOfflineSwitchUI();
  show($('modal-settings'));
}

export function initAuth(onNavigateFromRoute, onInitLanding) {
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
}

export function updateApiKeyUI() {
  if (state.hasApiKey) {
    hide($('api-key-not-set'));
    show($('api-key-set'));
    $('btn-delete-api-key').style.display = 'inline-block';
  } else {
    show($('api-key-not-set'));
    hide($('api-key-set'));
    $('btn-delete-api-key').style.display = 'none';
  }

  if (state.apiKeyStatus === 'none') {
    show($('api-key-warning'));
  } else {
    hide($('api-key-warning'));
  }
}
