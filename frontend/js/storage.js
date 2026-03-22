/* ============================================================
   EXPLAINER — Local Storage & Backup
   ============================================================ */

import {
  state,
  LOCAL_BACKUP_KEY_LEGACY,
  API_KEY_CACHE_KEY_PREFIX,
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

    const currentUpdated = new Date(current.updated_at || current.created_at || 0).getTime();
    const candidateUpdated = new Date(project.updated_at || project.created_at || 0).getTime();
    byId.set(project.id, candidateUpdated >= currentUpdated ? project : current);
  });

  return Array.from(byId.values()).sort((a, b) =>
    new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
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
