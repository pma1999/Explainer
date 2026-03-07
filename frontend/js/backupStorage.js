/* ============================================================
   EXPLAINER — Backup Storage (IndexedDB + localStorage fallback)
   ============================================================
   Primary: IndexedDB (~50MB+ quota on mobile)
   Fallback: localStorage (when IndexedDB unavailable)
   Last resort: lite backup (metadata only) when localStorage quota exceeded
   ============================================================ */

const DB_NAME = 'explainer';
const DB_VERSION = 1;
const STORE_NAME = 'projects_backup';

function getBackupKey(userId) {
  return userId ? `explainer.projects.backup.v1.${userId}` : null;
}

function isQuotaExceededError(err) {
  return err?.name === 'QuotaExceededError' || err?.code === 22;
}

function projectToLite(p) {
  if (!p) return null;
  return {
    id: p.id,
    name: p.name,
    description: p.description,
    status: p.status,
    segmentation: p.segmentation,
    created_at: p.created_at,
    updated_at: p.updated_at,
    usage: p.usage,
    reading_progress: p.reading_progress,
  };
}

function buildPayload(projects, lite = false) {
  const list = Array.isArray(projects) ? projects : [];
  return {
    version: 1,
    exported_at: new Date().toISOString(),
    lite: lite,
    projects: lite ? list.map(projectToLite).filter(Boolean) : list,
  };
}

function openDB() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB not available'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onerror = () => reject(req.error);
    req.onsuccess = () => resolve(req.result);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
  });
}

async function loadFromIndexedDB(userId) {
  const key = `backup_v1_${userId}`;
  const db = await openDB();
  try {
    const raw = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    if (!raw) return null;
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return parsed?.projects ? parsed : null;
  } finally {
    db.close();
  }
}

function loadFromLocalStorage(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.projects ? parsed : null;
  } catch (_) {
    return null;
  }
}

async function saveToIndexedDB(userId, payload) {
  const key = `backup_v1_${userId}`;
  const value = JSON.stringify(payload);
  const db = await openDB();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    return { ok: true };
  } finally {
    db.close();
  }
}

function saveToLocalStorage(key, value, opts = {}) {
  try {
    localStorage.setItem(key, value);
    return { ok: true };
  } catch (err) {
    if (isQuotaExceededError(err)) {
      return tryLiteBackup(key, value, opts);
    }
    return { ok: false };
  }
}

function tryLiteBackup(key, fullValue, opts = {}) {
  let payload;
  try {
    payload = JSON.parse(fullValue);
  } catch (_) {
    return { ok: false, quotaExceeded: true };
  }
  const projects = payload?.projects;
  if (!Array.isArray(projects)) return { ok: false, quotaExceeded: true };
  const litePayload = buildPayload(projects, true);
  const liteValue = JSON.stringify(litePayload);
  try {
    localStorage.setItem(key, liteValue);
    if (opts.onQuotaExceeded) opts.onQuotaExceeded();
    return { ok: true, usedLite: true };
  } catch (_) {
    if (opts.onQuotaExceeded) opts.onQuotaExceeded();
    return { ok: false, quotaExceeded: true };
  }
}

/**
 * Load backup for user. Tries IndexedDB first, falls back to localStorage.
 * @param {string|null} userId
 * @returns {Promise<{ version: number, projects: Array, lite?: boolean }>}
 */
export async function loadBackup(userId) {
  if (!userId) return { version: 1, projects: [] };
  const key = getBackupKey(userId);
  if (!key) return { version: 1, projects: [] };

  try {
    const parsed = await loadFromIndexedDB(userId);
    if (parsed) return parsed;
  } catch (_) {}

  const parsed = loadFromLocalStorage(key);
  if (parsed) return parsed;

  return { version: 1, projects: [] };
}

/**
 * Save backup for user. Tries IndexedDB first, falls back to localStorage.
 * On localStorage QuotaExceededError, tries lite backup (metadata only).
 * @param {string|null} userId
 * @param {{ projects: Array }} payload
 * @param {{ onQuotaExceeded?: () => void }} opts
 * @returns {Promise<{ ok: boolean, usedLite?: boolean, quotaExceeded?: boolean }>}
 */
export async function saveBackup(userId, payload, opts = {}) {
  if (!userId) return { ok: true };
  const key = getBackupKey(userId);
  if (!key) return { ok: true };

  const safePayload = buildPayload(payload?.projects, false);
  const value = JSON.stringify(safePayload);

  try {
    await saveToIndexedDB(userId, safePayload);
    return { ok: true };
  } catch (_) {
    return saveToLocalStorage(key, value, opts);
  }
}
