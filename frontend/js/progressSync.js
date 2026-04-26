/* ============================================================
   EXPLAINER — Reading Progress Sync
   ============================================================ */

import { state } from './state.js';
import { api } from './api.js';
import { loadBackupAsync, syncProjectsToBackup } from './storage.js';

export const SUBSECTION_PROGRESS_FLUSH_DEBOUNCE_MS = 15000;
export const SUBSECTION_PROGRESS_MIN_FLUSH_INTERVAL_MS = 60000;
const SUBSECTION_PROGRESS_RETRY_MS = 60000;
const LOCAL_PROGRESS_BACKUP_DEBOUNCE_MS = 1000;

const pendingByKey = new Map();
let flushTimer = null;
let backupTimer = null;
let inFlightFlush = null;
let lastFlushAt = 0;
let lifecycleInitialized = false;

function normalizePartId(partId) {
  const n = Number(partId);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function progressTimeMs(progress) {
  const value = progress?.last_read_at;
  const time = value ? new Date(value).getTime() : 0;
  return Number.isFinite(time) ? time : 0;
}

function unionStrings(a = [], b = []) {
  const out = [];
  const seen = new Set();
  [...a, ...b].forEach((value) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    out.push(value);
  });
  return out;
}

function mergeReadingProgress(localProgress = {}, serverProgress = {}) {
  const localTime = progressTimeMs(localProgress);
  const serverTime = progressTimeMs(serverProgress);
  const merged = serverTime >= localTime
    ? { ...localProgress, ...serverProgress }
    : { ...serverProgress, ...localProgress };

  merged.completed_subsections = unionStrings(
    serverProgress.completed_subsections,
    localProgress.completed_subsections,
  );
  return merged;
}

function pendingKey(projectId, partId, tab) {
  return `${projectId}::${partId}::${tab || 'explicacion'}`;
}

function getOrCreatePending(projectId, partId, tab) {
  const key = pendingKey(projectId, partId, tab);
  let entry = pendingByKey.get(key);
  if (!entry) {
    entry = {
      projectId,
      partId,
      tab: tab || 'explicacion',
      completed_subsection_ids: new Set(),
      last_subsection_id: null,
      last_subsection_at: 0,
    };
    pendingByKey.set(key, entry);
  }
  return entry;
}

function mergePendingEntry(entry) {
  const pending = getOrCreatePending(entry.projectId, entry.partId, entry.tab);
  entry.completed_subsection_ids.forEach((id) => pending.completed_subsection_ids.add(id));
  if (entry.last_subsection_id && entry.last_subsection_at >= pending.last_subsection_at) {
    pending.last_subsection_id = entry.last_subsection_id;
    pending.last_subsection_at = entry.last_subsection_at;
  }
}

function serializePendingEntry(entry) {
  const completed = Array.from(entry.completed_subsection_ids);
  if (!entry.last_subsection_id && completed.length === 0) return null;

  const payload = {
    part_id: entry.partId,
    tab: entry.tab || 'explicacion',
  };
  if (entry.last_subsection_id) {
    payload.last_subsection_id = entry.last_subsection_id;
  }
  if (completed.length > 0) {
    payload.completed_subsection_ids = completed;
  }
  return payload;
}

async function writeCurrentProjectProgressToBackup() {
  const userId = state.user?.id;
  const project = state.currentProject;
  const projectId = state.currentProjectId || project?.id;
  if (!userId || !project || !projectId) return;

  const backup = await loadBackupAsync(userId);
  const projects = Array.isArray(backup?.projects) ? backup.projects : [];
  let found = false;
  const nextProjects = projects.map((p) => {
    if (p?.id !== projectId) return p;
    found = true;
    return {
      ...p,
      reading_progress: project.reading_progress || {},
      updated_at: project.updated_at,
    };
  });
  if (!found) {
    nextProjects.unshift(project);
  }
  await syncProjectsToBackup(nextProjects, userId);
}

function scheduleLocalProgressBackup() {
  if (backupTimer) clearTimeout(backupTimer);
  backupTimer = setTimeout(() => {
    backupTimer = null;
    writeCurrentProjectProgressToBackup().catch(() => {});
  }, LOCAL_PROGRESS_BACKUP_DEBOUNCE_MS);
}

export function recordSubsectionProgress({
  subsection_id,
  part_id,
  tab = 'explicacion',
  completed,
  is_last_read,
}) {
  if (!state.currentProject || !subsection_id) return false;

  const partId = normalizePartId(part_id);
  const projectId = state.currentProjectId || state.currentProject.id;
  if (!projectId || !partId) return false;

  const nowIso = new Date().toISOString();
  const progress = { ...(state.currentProject.reading_progress || {}) };
  const completedSubsections = unionStrings(progress.completed_subsections, []);
  let changed = false;

  if (completed === true && !completedSubsections.includes(subsection_id)) {
    completedSubsections.push(subsection_id);
    progress.completed_subsections = completedSubsections;
    changed = true;
  } else if (completed === false && completedSubsections.includes(subsection_id)) {
    progress.completed_subsections = completedSubsections.filter((id) => id !== subsection_id);
    changed = true;
  } else if (progress.completed_subsections) {
    progress.completed_subsections = completedSubsections;
  }

  if (is_last_read) {
    progress.last_subsection = {
      part_id: partId,
      subsection_id,
      tab: tab || 'explicacion',
    };
    progress.last_read_at = nowIso;
    changed = true;
  }

  if (!changed) return false;

  state.currentProject.reading_progress = progress;
  state.currentProject.updated_at = nowIso;
  scheduleLocalProgressBackup();

  if (!state.user?.id || state.isSharedView) return true;
  const entry = getOrCreatePending(projectId, partId, tab || 'explicacion');
  if (completed === true) {
    entry.completed_subsection_ids.add(subsection_id);
  }
  if (is_last_read) {
    entry.last_subsection_id = subsection_id;
    entry.last_subsection_at = Date.now();
  }
  scheduleSubsectionProgressFlush();
  return true;
}

export function scheduleSubsectionProgressFlush(delayMs = SUBSECTION_PROGRESS_FLUSH_DEBOUNCE_MS) {
  if (pendingByKey.size === 0) return;
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(() => {
    flushTimer = null;
    flushSubsectionProgress().catch(() => {});
  }, delayMs);
}

export async function flushSubsectionProgress({ force = false, keepalive = false } = {}) {
  if (pendingByKey.size === 0) return { ok: true, skipped: true };
  if (!state.user?.id || state.isSharedView) {
    pendingByKey.clear();
    return { ok: true, skipped: true };
  }
  if (inFlightFlush) return inFlightFlush;

  const now = Date.now();
  if (!force && lastFlushAt > 0 && now - lastFlushAt < SUBSECTION_PROGRESS_MIN_FLUSH_INTERVAL_MS) {
    const remaining = SUBSECTION_PROGRESS_MIN_FLUSH_INTERVAL_MS - (now - lastFlushAt);
    scheduleSubsectionProgressFlush(Math.max(remaining, 1000));
    return { ok: true, deferred: true };
  }

  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    scheduleSubsectionProgressFlush(SUBSECTION_PROGRESS_RETRY_MS);
    return { ok: false, offline: true };
  }

  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }

  const entries = Array.from(pendingByKey.values());
  pendingByKey.clear();

  inFlightFlush = (async () => {
    let ok = true;
    for (const entry of entries) {
      const payload = serializePendingEntry(entry);
      if (!payload) continue;
      try {
        const updated = await api(`/api/projects/${entry.projectId}/progress/subsection`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          keepalive,
        });
        lastFlushAt = Date.now();
        const currentProjectId = state.currentProjectId || state.currentProject?.id;
        if (updated?.reading_progress && state.currentProject && currentProjectId === entry.projectId) {
          state.currentProject.reading_progress = mergeReadingProgress(
            state.currentProject.reading_progress || {},
            updated.reading_progress,
          );
          if (updated.updated_at) {
            state.currentProject.updated_at = updated.updated_at;
          }
          scheduleLocalProgressBackup();
        }
      } catch (_) {
        ok = false;
        mergePendingEntry(entry);
      }
    }
    if (!ok) {
      scheduleSubsectionProgressFlush(SUBSECTION_PROGRESS_RETRY_MS);
    }
    return { ok };
  })();

  try {
    return await inFlightFlush;
  } finally {
    inFlightFlush = null;
    if (pendingByKey.size > 0 && !flushTimer) {
      scheduleSubsectionProgressFlush();
    }
  }
}

export function initProgressSyncLifecycle() {
  if (lifecycleInitialized) return;
  lifecycleInitialized = true;

  window.flushSubsectionProgress = flushSubsectionProgress;

  const flushForExit = () => {
    flushSubsectionProgress({ force: true, keepalive: true }).catch(() => {});
  };

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushForExit();
  });
  window.addEventListener('pagehide', flushForExit);
  window.addEventListener('online', () => {
    flushSubsectionProgress({ force: true }).catch(() => {});
  });
  window.addEventListener('explainer:online', () => {
    flushSubsectionProgress({ force: true }).catch(() => {});
  });
}
