/* ============================================================
   EXPLAINER — State & Configuration
   ============================================================ */

const SUPABASE_URL = window.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.SUPABASE_ANON_KEY || '';
export const supabaseClient = (SUPABASE_URL && SUPABASE_ANON_KEY && window.supabase)
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
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
