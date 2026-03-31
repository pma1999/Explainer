/* ============================================================
   EXPLAINER — PWA: Service Worker, Install Prompt, Offline
   ============================================================ */

import { toast } from './dom.js';

const PREFER_OFFLINE_STORAGE_KEY = 'explainer.preferOffline';

let deferredInstallPrompt = null;
let swRegistration = null;

// ─── Prefer offline (user-controlled “ahorrar datos”) ───────

export function getPreferOffline() {
  try {
    return localStorage.getItem(PREFER_OFFLINE_STORAGE_KEY) === '1';
  } catch (_) {
    return false;
  }
}

export function setPreferOffline(value) {
  const v = Boolean(value);
  try {
    localStorage.setItem(PREFER_OFFLINE_STORAGE_KEY, v ? '1' : '0');
  } catch (_) {}
  updateOnlineState();
  syncPreferOfflineToServiceWorker();
  window.dispatchEvent(
    new CustomEvent('explainer:prefer-offline-changed', { detail: { preferOffline: v } })
  );
}

export function syncPreferOfflineToServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const msg = { type: 'SET_PREFER_OFFLINE', value: getPreferOffline() };
  const reg = swRegistration;
  if (reg?.active) reg.active.postMessage(msg);
  if (reg?.waiting) reg.waiting.postMessage(msg);
  navigator.serviceWorker.ready
    .then((r) => {
      if (r.active) r.active.postMessage(msg);
    })
    .catch(() => {});
}

/** True when there is no usable “online” path for app behavior (browser offline or user chose offline mode). */
export function isOffline() {
  return !navigator.onLine || getPreferOffline();
}

// ─── Connectivity (for safe SW activation) ───────────────────

async function checkConnectivityOk() {
  if (!navigator.onLine) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 4000);
  try {
    const url = new URL('/manifest.json', window.location.origin).href;
    const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
    return res.ok;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function scheduleServiceWorkerUpdateChecks() {
  const run = () => {
    if (swRegistration) swRegistration.update().then(() => maybeApplyWaitingServiceWorker());
  };
  window.addEventListener('focus', run);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) run();
  });
  window.addEventListener('pageshow', (e) => {
    if (e.persisted) run();
  });
}

/** If a waiting worker exists, auto-activate when online and not in prefer-offline; else show manual toast. */
function maybeApplyWaitingServiceWorker() {
  if (!swRegistration?.waiting) return;
  if (getPreferOffline()) {
    showUpdateToast();
    return;
  }
  checkConnectivityOk().then((ok) => {
    if (!swRegistration?.waiting) return;
    if (ok) {
      toast('Actualizando a la última versión…', 'info');
      swRegistration.waiting.postMessage('SKIP_WAITING');
    } else {
      showUpdateToast();
    }
  });
}

// ─── Service Worker Registration ────────────────────────────

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;

  try {
    swRegistration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/',
    });

    await swRegistration.update();
    if (swRegistration.waiting) maybeApplyWaitingServiceWorker();

    swRegistration.addEventListener('updatefound', () => {
      const newWorker = swRegistration.installing;
      if (!newWorker) return;

      newWorker.addEventListener('statechange', () => {
        if (
          newWorker.state === 'installed' &&
          navigator.serviceWorker.controller
        ) {
          maybeApplyWaitingServiceWorker();
        }
      });
    });

    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });

    await navigator.serviceWorker.ready;
    syncPreferOfflineToServiceWorker();
    scheduleServiceWorkerUpdateChecks();
  } catch (err) {
    console.warn('[PWA] Service worker registration failed:', err);
  }
}

function showUpdateToast() {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const id = `toast-update-${Date.now()}`;
  const div = document.createElement('div');
  div.id = id;
  div.className = 'toast toast-info toast-update';
  div.setAttribute('role', 'status');
  div.innerHTML = `
    <span class="toast-msg">Nueva versión disponible</span>
    <button class="toast-action-btn" type="button">Actualizar</button>
  `;

  div.querySelector('.toast-action-btn').addEventListener('click', () => {
    if (swRegistration && swRegistration.waiting) {
      swRegistration.waiting.postMessage('SKIP_WAITING');
    }
    div.remove();
  });

  container.appendChild(div);
}

// ─── Install Prompt ─────────────────────────────────────────

export function listenInstallPrompt() {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    showInstallButton();
  });

  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    hideInstallButton();
    toast('¡Explainer instalado correctamente!', 'success');
  });

  document.addEventListener('click', async (e) => {
    if (e.target.closest('#btn-install-pwa, .btn-install-pwa')) {
      await triggerInstall();
    }
  });
}

async function triggerInstall() {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  const { outcome } = await deferredInstallPrompt.userChoice;
  if (outcome === 'accepted') {
    deferredInstallPrompt = null;
    hideInstallButton();
  }
}

function showInstallButton() {
  document.querySelectorAll('.btn-install-pwa').forEach((btn) => {
    btn.classList.remove('hidden');
  });
}

function hideInstallButton() {
  document.querySelectorAll('.btn-install-pwa').forEach((btn) => {
    btn.classList.add('hidden');
  });
}

// ─── Online / Offline Detection ─────────────────────────────

export function listenOnlineOffline() {
  updateOnlineState();

  window.addEventListener('online', () => {
    updateOnlineState();
    if (!getPreferOffline()) {
      toast('Conexión restaurada', 'success');
    }
    window.dispatchEvent(new CustomEvent('explainer:online'));
  });

  window.addEventListener('offline', () => {
    updateOnlineState();
    window.dispatchEvent(new CustomEvent('explainer:offline'));
  });
}

export function updateOnlineState() {
  const effectiveOffline = isOffline();
  const preferOnly = navigator.onLine && getPreferOffline();

  const banner = document.getElementById('offline-banner');
  const textEl = document.getElementById('offline-banner-text');
  if (banner) {
    banner.classList.toggle('hidden', !effectiveOffline);
    if (textEl) {
      const compactCopy = window.matchMedia('(max-width: 768px)').matches;
      textEl.textContent = preferOnly
        ? (compactCopy
          ? 'Modo offline activado — solo copias locales'
          : 'Modo offline activado — solo proyectos guardados localmente; sin sincronización en segundo plano')
        : (compactCopy
          ? 'Sin conexión — solo contenido offline'
          : 'Sin conexión — mostrando proyectos disponibles offline');
    }
  }

  document.body.classList.toggle('is-offline', effectiveOffline);
  document.body.classList.toggle('is-online', !effectiveOffline);
  document.body.classList.toggle('is-prefer-offline', preferOnly);
  syncOfflineBannerHeight();
}

function syncOfflineBannerHeight() {
  const banner = document.getElementById('offline-banner');
  const visible = banner && !banner.classList.contains('hidden');
  const height = visible ? Math.ceil(banner.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty('--offline-banner-h', `${height}px`);
}

// ─── Init ───────────────────────────────────────────────────

export function initPWA() {
  if (document.readyState === 'complete') {
    registerServiceWorker();
  } else {
    window.addEventListener('load', registerServiceWorker);
  }

  listenInstallPrompt();
  listenOnlineOffline();
  window.addEventListener('resize', updateOnlineState);
}
