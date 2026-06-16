/* ============================================================
   EXPLAINER — Local Storage & Backup
   ============================================================ */

import {
  state,
  LOCAL_BACKUP_KEY_LEGACY,
  API_KEY_CACHE_KEY_PREFIX,
  OPENROUTER_KEY_CACHE_KEY_PREFIX,
  MISTRAL_KEY_CACHE_KEY_PREFIX,
  DEEPSEEK_KEY_CACHE_KEY_PREFIX,
  TAVILY_KEY_CACHE_KEY_PREFIX,
  API_KEY_CACHE_TTL_MS,
} from './state.js';
import { api } from './api.js';
import {
  loadBackup,
  saveBackup,
  pinProjectOffline,
  unpinProjectOffline,
  getOfflinePins,
  isProjectPinned,
} from './backupStorage.js';
import { isOffline } from './pwa.js';

// Re-export offline pin helpers for use across the app
export { pinProjectOffline, unpinProjectOffline, getOfflinePins, isProjectPinned };

function _projectTimeMs(project) {
  return new Date(project.updated_at || project.created_at || 0).getTime();
}

function _readingProgressTimeMs(project) {
  const value = project?.reading_progress?.last_read_at;
  const time = value ? new Date(value).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
}

function _bestReadingProgress(primary, secondary) {
  const primaryProgress = primary?.reading_progress;
  const secondaryProgress = secondary?.reading_progress;
  if (!secondaryProgress) return primaryProgress;
  if (!primaryProgress) return secondaryProgress;
  return _readingProgressTimeMs(secondary) > _readingProgressTimeMs(primary)
    ? secondaryProgress
    : primaryProgress;
}

/**
 * Merge two project records for the same id. Prefers newer updated_at.
 * If the newer record is a server list_summary, preserve partes_contenido and source_text
 * from the older record when missing on the newer.
 */
export function mergePairProjects(a, b) {
  const ta = _projectTimeMs(a);
  const tb = _projectTimeMs(b);
  let newer;
  let older;
  if (tb > ta) {
    newer = b;
    older = a;
  } else if (ta > tb) {
    newer = a;
    older = b;
  } else {
    return b;
  }

  if (!newer.list_summary) {
    return {
      ...newer,
      reading_progress: _bestReadingProgress(newer, older),
    };
  }

  const out = { ...newer };
  out.reading_progress = _bestReadingProgress(newer, older);
  if (
    !Object.prototype.hasOwnProperty.call(newer, 'partes_contenido') &&
    older &&
    Object.prototype.hasOwnProperty.call(older, 'partes_contenido')
  ) {
    out.partes_contenido = older.partes_contenido;
  }
  if (
    !Object.prototype.hasOwnProperty.call(newer, 'source_text') &&
    older &&
    Object.prototype.hasOwnProperty.call(older, 'source_text')
  ) {
    out.source_text = older.source_text;
  }
  delete out.list_summary;
  return out;
}

export function getLocalBackupKey(userId) {
  return userId ? `explainer.projects.backup.v1.${userId}` : null;
}

export function getCachedApiKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(API_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasApiKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedApiKeyStatus(userId, hasApiKey) {
  if (!userId) return;
  try {
    localStorage.setItem(API_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasApiKey: Boolean(hasApiKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

export function getCachedOpenRouterKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(OPENROUTER_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedOpenRouterKeyStatus(userId, hasKey) {
  if (!userId) return;
  try {
    localStorage.setItem(OPENROUTER_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasKey: Boolean(hasKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

export function getCachedMistralKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(MISTRAL_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedMistralKeyStatus(userId, hasKey) {
  if (!userId) return;
  try {
    localStorage.setItem(MISTRAL_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasKey: Boolean(hasKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

export function getCachedDeepSeekKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(DEEPSEEK_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedDeepSeekKeyStatus(userId, hasKey) {
  if (!userId) return;
  try {
    localStorage.setItem(DEEPSEEK_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasKey: Boolean(hasKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

export function getCachedTavilyKeyStatus(userId) {
  if (!userId) return null;
  try {
    const raw = localStorage.getItem(TAVILY_KEY_CACHE_KEY_PREFIX + userId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - (parsed.updatedAt ? new Date(parsed.updatedAt).getTime() : 0);
    if (age > API_KEY_CACHE_TTL_MS) return null;
    return parsed.hasKey === true;
  } catch (_) {
    return null;
  }
}

export function setCachedTavilyKeyStatus(userId, hasKey) {
  if (!userId) return;
  try {
    localStorage.setItem(TAVILY_KEY_CACHE_KEY_PREFIX + userId, JSON.stringify({
      hasKey: Boolean(hasKey),
      updatedAt: new Date().toISOString(),
    }));
  } catch (_) {}
}

/**
 * Sync load from localStorage only (legacy compatibility).
 * Prefer loadBackupAsync for new code.
 */
export function loadLocalBackup(userId) {
  const key = getLocalBackupKey(userId);
  if (!key) return { version: 1, projects: [] };
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { version: 1, projects: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.projects)) return { version: 1, projects: [] };
    return parsed;
  } catch (_) {
    return { version: 1, projects: [] };
  }
}

/**
 * Async load from IndexedDB (primary) or localStorage (fallback).
 */
export async function loadBackupAsync(userId) {
  return loadBackup(userId);
}

/**
 * Async save to IndexedDB (primary) or localStorage (fallback).
 * Never throws; returns { ok, quotaExceeded?, usedLite? }.
 */
export async function syncProjectsToBackup(projects, userId, opts = {}) {
  if (!userId) return { ok: true };
  try {
    return await saveBackup(userId, { projects }, opts);
  } catch (_) {
    return { ok: false };
  }
}

/**
 * @deprecated Use syncProjectsToBackup. Kept for backward compatibility.
 */
export function syncProjectsToLocal(projects, userId) {
  syncProjectsToBackup(projects, userId).catch(() => {});
}

export async function migrateLegacyBackupIfNeeded(userId) {
  if (!userId) return;
  const userKey = getLocalBackupKey(userId);
  if (!userKey) return;
  try {
    const legacyRaw = localStorage.getItem(LOCAL_BACKUP_KEY_LEGACY);
    const userRaw = localStorage.getItem(userKey);
    const raw = userRaw || legacyRaw;
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.projects)) return;
    const result = await saveBackup(userId, { projects: parsed.projects });
    if (result.ok) {
      localStorage.removeItem(LOCAL_BACKUP_KEY_LEGACY);
      localStorage.removeItem(userKey);
    }
  } catch (_) {}
}

export function mergeProjects(serverProjects = [], localProjects = []) {
  const byId = new Map();
  [...localProjects, ...serverProjects].forEach((project) => {
    if (!project || !project.id) return;
    const current = byId.get(project.id);
    if (!current) {
      byId.set(project.id, project);
      return;
    }
    byId.set(project.id, mergePairProjects(current, project));
  });

  return Array.from(byId.values()).sort(
    (a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime(),
  );
}

/**
 * Sync get cached project (legacy). Prefer getCachedProjectAsync.
 */
export function getCachedProject(projectId) {
  const backup = loadLocalBackup(state.user?.id);
  if (backup.lite) return null;
  return backup.projects.find((p) => p.id === projectId) || null;
}

/**
 * Async get cached project from backup. Returns null if backup is lite (no full content).
 */
export async function getCachedProjectAsync(projectId) {
  const backup = await loadBackupAsync(state.user?.id);
  if (backup.lite) return null;
  return backup.projects.find((p) => p.id === projectId) || null;
}

export function getFirstIncompletePart(project) {
  const partes = project?.segmentation?.partes || [];
  const completed = new Set(project?.reading_progress?.completed_parts || []);
  return partes.find((p) => !completed.has(p.numero))?.numero ?? null;
}

/**
 * Returns the best resume target for a project.
 * Priority: last_subsection (precise scroll target) > first incomplete part > first part.
 * Validates that the referenced part still exists in segmentation.
 * Returns null only when there are no parts at all.
 */
export function getResumeTarget(project) {
  const partes = project?.segmentation?.partes || [];
  if (partes.length === 0) return null;

  const last = project?.reading_progress?.last_subsection;
  if (last && last.part_id != null) {
    const partExists = partes.some((p) => p.numero === last.part_id);
    if (partExists) {
      return {
        partId: last.part_id,
        tab: last.tab || 'explicacion',
        subsectionId: last.subsection_id || null,
      };
    }
  }

  const completed = new Set(project?.reading_progress?.completed_parts || []);
  const firstIncomplete = partes.find((p) => !completed.has(p.numero))?.numero;
  if (firstIncomplete != null) {
    return { partId: firstIncomplete, tab: 'explicacion', subsectionId: null };
  }

  return { partId: partes[0].numero, tab: 'explicacion', subsectionId: null };
}

export function payloadToJsonFile(payload, filename = 'explainer-sync.json') {
  return new File([JSON.stringify(payload, null, 2)], filename, { type: 'application/json' });
}

export async function rehydrateProjectToServer(project) {
  const fd = new FormData();
  fd.append('file', payloadToJsonFile({ version: 1, projects: [project] }));
  await api('/api/projects/import', { method: 'POST', body: fd });
}

// Projects prefetch
let projectsFetchPromise = null;

export function invalidateProjectsCache() {
  projectsFetchPromise = null;
}

export function ensureProjectsFetched(opts = {}) {
  const userId = state.user?.id;
  if (!userId) return Promise.resolve([]);
  if (!projectsFetchPromise) {
    projectsFetchPromise = (async () => {
      try {
        if (isOffline()) {
          const local = await loadBackupAsync(userId);
          return local.projects;
        }
        const [serverProjects, local] = await Promise.all([
          api('/api/projects'),
          loadBackupAsync(userId),
        ]);
        const merged = mergeProjects(serverProjects, local.projects);
        await syncProjectsToBackup(merged, userId, opts);
        return merged;
      } catch (err) {
        projectsFetchPromise = null;
        throw err;
      }
    })();
  }
  return projectsFetchPromise;
}
