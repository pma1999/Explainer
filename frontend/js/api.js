/* ============================================================
   EXPLAINER — API Client & Prefetch
   ============================================================ */

import { state, supabaseClient } from './state.js';
import { showView, toast } from './dom.js';

export const API_BASE_URL = window.EXPLAINER_API_BASE_URL || '';

export function getAccessToken() {
  return state.session?.access_token || null;
}

export async function api(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers = { ...(options.headers || {}) };
  const token = getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    if (supabaseClient) {
      await supabaseClient.auth.signOut();
      state.session = null;
      state.user = null;
      showView('view-auth');
      toast('Sesión expirada. Inicia sesión de nuevo.', 'error');
    }
    const err = await res.json().catch(() => ({ detail: 'No autorizado' }));
    throw new Error(err.detail || 'No autorizado');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Error desconocido' }));
    throw new Error(err.detail || 'Error en el servidor');
  }

  return res.json();
}

export function getAccessToken() {
  return state.session?.access_token || null;
}
