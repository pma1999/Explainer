/* ============================================================
   EXPLAINER — State & Configuration
   ============================================================ */

const SUPABASE_URL = window.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || '';
export const AUTH_PERSISTENCE_PREFERENCE_KEY = 'explainer.auth.persist.v1';

function _getStorageHandle(name) {
  try {
    if (typeof window === 'undefined') return null;
    const storage = window[name];
    if (!storage) return null;
    const probe = '__explainer_storage_probe__';
    storage.setItem(probe, '1');
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

function _getLocalStorage() {
  return _getStorageHandle('localStorage');
}

function _getSessionStorage() {
  return _getStorageHandle('sessionStorage');
}

function _readStorage(storage, key) {
  if (!storage) return null;
  try {
    const value = storage.getItem(key);
    return typeof value === 'string' ? value : null;
  } catch {
    return null;
  }
}

function _writeStorage(storage, key, value) {
  if (!storage) return;
  try {
    storage.setItem(key, value);
  } catch {
    // Ignore storage quota / privacy-mode failures and let the client continue.
  }
}

function _removeStorage(storage, key) {
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // Ignore storage cleanup failures.
  }
}

export function getRememberSessionPreference() {
  const storage = _getLocalStorage();
  const raw = _readStorage(storage, AUTH_PERSISTENCE_PREFERENCE_KEY);
  if (raw === '1') return true;
  if (raw === '0') return false;
  return null;
}

export function setRememberSessionPreference(remember) {
  const storage = _getLocalStorage();
  if (!storage) return;
  _writeStorage(storage, AUTH_PERSISTENCE_PREFERENCE_KEY, remember ? '1' : '0');
}

export function createSupabaseAuthStorage() {
  return {
    getItem(key) {
      const sessionStorage = _getSessionStorage();
      const localStorage = _getLocalStorage();
      const rememberPreference = getRememberSessionPreference();
      const sessionValue = _readStorage(sessionStorage, key);

      if (rememberPreference === false) {
        return sessionValue;
      }

      const localValue = _readStorage(localStorage, key);
      if (rememberPreference === true) {
        return localValue ?? sessionValue;
      }

      if (sessionValue !== null) {
        return sessionValue;
      }
      if (localValue !== null) {
        // Preserve legacy persisted sessions created before the remember-me toggle existed.
        setRememberSessionPreference(true);
        return localValue;
      }
      return null;
    },
    setItem(key, value) {
      const localStorage = _getLocalStorage();
      const sessionStorage = _getSessionStorage();
      const rememberPreference = getRememberSessionPreference() === true;
      const primary = rememberPreference
        ? (localStorage || sessionStorage)
        : (sessionStorage || localStorage);
      const secondary = primary === localStorage ? sessionStorage : localStorage;

      _writeStorage(primary, key, value);
      _removeStorage(secondary, key);
    },
    removeItem(key) {
      _removeStorage(_getSessionStorage(), key);
      _removeStorage(_getLocalStorage(), key);
    },
  };
}

const supabaseAuthStorage = createSupabaseAuthStorage();
export const supabaseClient = (SUPABASE_URL && SUPABASE_ANON_KEY && window.supabase)
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        storage: supabaseAuthStorage,
      },
    })
  : null;

export const state = {
  currentProjectId: null,
  currentProject: null,
  currentPartId: null,
  currentSubsectionId: null,
  activeTab: 'explicacion',
  isSharedView: false,
  shareToken: null,
  processingSSE: null,
  sseProjectId: null,
  sseReconnectAttempts: 0,
  sseLastEventAt: 0,
  ssePausedByVisibility: false,
  pollProjectsInterval: null,
  pollCurrentProjectInterval: null,
  hasApiKey: false,
  apiKeyStatus: 'loading',
  hasOpenRouterKey: false,
  openRouterKeyStatus: 'loading',
  hasMistralKey: false,
  mistralKeyStatus: 'loading',
  session: null,
  user: null,
  previousUserId: null,
  lastPartChangeAt: 0,
};

export const SSE_RECONNECT_MAX = 5;
export const SSE_RECONNECT_DELAY_MS = 2000;
export const POLL_PROJECTS_MS = 6000;
export const POLL_CURRENT_IF_IDLE_MS = 12000;
export const VISIBILITY_RECONNECT_DELAY_MS = 800;

export const LOCAL_BACKUP_KEY_LEGACY = 'explainer.projects.backup.v1';
export const SESSION_VIEW_KEY = 'explainer.current_view.v1';
export const API_KEY_CACHE_KEY_PREFIX = 'explainer.apiKeyStatus.v1.';
export const OPENROUTER_KEY_CACHE_KEY_PREFIX = 'explainer.openrouterKeyStatus.v1.';
export const MISTRAL_KEY_CACHE_KEY_PREFIX = 'explainer.mistralKeyStatus.v1.';
export const API_KEY_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
