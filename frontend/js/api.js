/* ============================================================
   EXPLAINER — API Client & Prefetch
   ============================================================ */

import { state, supabaseClient } from './state.js';
import { showView, toast } from './dom.js';

export const API_BASE_URL = window.EXPLAINER_API_BASE_URL || '';

export function getAccessToken() {
  return state.session?.access_token || null;
}

let _refreshInFlight = null;

async function _refreshOnce() {
  if (!_refreshInFlight) {
    _refreshInFlight = supabaseClient.auth.refreshSession()
      .finally(() => { _refreshInFlight = null; });
  }
  return _refreshInFlight;
}

async function _forceSignOut() {
  if (supabaseClient) await supabaseClient.auth.signOut();
  state.session = null;
  state.user = null;
  showView('view-auth');
  toast('Sesión expirada. Inicia sesión de nuevo.', 'error');
}

export async function api(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers = { ...(options.headers || {}) };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    if (supabaseClient) {
      const { data: refreshData, error: refreshError } = await _refreshOnce();
      if (!refreshError && refreshData?.session) {
        state.session = refreshData.session;
        const retryHeaders = { ...(options.headers || {}), 'Authorization': `Bearer ${refreshData.session.access_token}` };
        const retryRes = await fetch(url, { ...options, headers: retryHeaders });
        if (retryRes.ok) return retryRes.json();
        if (retryRes.status !== 401) {
          const err = await retryRes.json().catch(() => ({ detail: 'Error desconocido' }));
          throw new Error(err.detail || 'Error en el servidor');
        }
      }
      await _forceSignOut();
    }
    const err = await res.json().catch(() => ({ detail: 'No autorizado' }));
    throw new Error(err.detail || 'No autorizado');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    const detail = err && err.detail ? err.detail : 'Error desconocido';
    throw new Error(`${res.status}: ${detail}`);
  }

  return res.json();
}
