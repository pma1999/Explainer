/* ============================================================
   EXPLAINER — PWA: Service Worker, Install Prompt, Offline
   ============================================================ */

import { toast } from './dom.js';

let deferredInstallPrompt = null;
let swRegistration = null;

// ─── Service Worker Registration ────────────────────────────

export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;

  try {
    swRegistration = await navigator.serviceWorker.register('/sw.js', {
      scope: '/',
    });

    // Detect SW update available
    swRegistration.addEventListener('updatefound', () => {
      const newWorker = swRegistration.installing;
      if (!newWorker) return;

      newWorker.addEventListener('statechange', () => {
        if (
          newWorker.state === 'installed' &&
          navigator.serviceWorker.controller
        ) {
          // New version available — show actionable toast
          showUpdateToast();
        }
      });
    });

    // Reload page when new SW takes control (after user clicks update)
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });
  } catch (err) {
    console.warn('[PWA] Service worker registration failed:', err);
  }
}

function showUpdateToast() {
  // Custom toast with action button
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
  // Don't auto-dismiss update toasts
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

  // Wire up install buttons (there may be multiple in different views)
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
  // Set initial state
  updateOnlineState();

  window.addEventListener('online', () => {
    updateOnlineState();
    toast('Conexión restaurada', 'success');
    // Dispatch custom event so other modules can react
    window.dispatchEvent(new CustomEvent('explainer:online'));
  });

  window.addEventListener('offline', () => {
    updateOnlineState();
    // Dispatch custom event so other modules can react
    window.dispatchEvent(new CustomEvent('explainer:offline'));
  });
}

function updateOnlineState() {
  const isOnline = navigator.onLine;
  const banner = document.getElementById('offline-banner');
  if (banner) {
    banner.classList.toggle('hidden', isOnline);
  }
  // Add body class for CSS hooks
  document.body.classList.toggle('is-offline', !isOnline);
  document.body.classList.toggle('is-online', isOnline);
}

/** Returns true when the browser reports no network connection. */
export function isOffline() {
  return !navigator.onLine;
}

// ─── Init ───────────────────────────────────────────────────

export function initPWA() {
  // Register SW after page load so it doesn't compete with initial network requests
  if (document.readyState === 'complete') {
    registerServiceWorker();
  } else {
    window.addEventListener('load', registerServiceWorker);
  }

  listenInstallPrompt();
  listenOnlineOffline();
}
