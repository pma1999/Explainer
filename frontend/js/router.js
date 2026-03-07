/* ============================================================
   EXPLAINER — Hash-based Router (ES Module)
   URL format: #/ | #/projects | #/p/{projectId} | #/p/{projectId}/s/{partId}/t/{tab}
   Shared: #/s/{token} | #/s/{token}/s/{partId}/t/{tab}
   ============================================================ */

export const VALID_TABS = ['explicacion', 'recorrido', 'recursos'];

/**
 * Parse the current location hash into a route object.
 * @param {string} [hash] - Optional hash string (defaults to location.hash)
 * @returns {{ view: string, projectId?: string, shareToken?: string, partId?: number, tab?: string } | null}
 */
export function parseRoute(hash) {
  const h = (hash !== undefined ? hash : (typeof location !== 'undefined' ? location.hash : '')) || '';
  const hashStr = h.replace(/^#/, '').trim();
  if (!hashStr || hashStr === '/') {
    return { view: 'landing' };
  }

  const segments = hashStr.replace(/^\/+/, '').split('/').filter(Boolean);

  if (segments[0] === 'projects') {
    return { view: 'projects' };
  }

  if (segments[0] === 's' && segments[1]) {
    const route = { view: 'shared', shareToken: segments[1] };
    if (segments[2] === 's' && segments[3]) {
      const partId = Number(segments[3]);
      if (!Number.isNaN(partId) && partId > 0) {
        route.partId = partId;
      }
    }
    if (route.partId && segments[4] === 't' && segments[5]) {
      const tab = segments[5].toLowerCase();
      if (VALID_TABS.includes(tab)) {
        route.tab = tab;
      }
    }
    if (route.partId && !route.tab) {
      route.tab = 'explicacion';
    }
    return route;
  }

  if (segments[0] === 'p' && segments[1]) {
    const route = {
      view: 'project',
      projectId: segments[1],
    };

    if (segments[2] === 's' && segments[3]) {
      const partId = Number(segments[3]);
      if (!Number.isNaN(partId) && partId > 0) {
        route.partId = partId;
      }
    }

    if (route.partId && segments[4] === 't' && segments[5]) {
      const tab = segments[5].toLowerCase();
      if (VALID_TABS.includes(tab)) {
        route.tab = tab;
      }
    }

    if (route.partId && !route.tab) {
      route.tab = 'explicacion';
    }

    return route;
  }

  return null;
}

/**
 * Build hash string from route object.
 * @param {{ view: string, projectId?: string, shareToken?: string, partId?: number, tab?: string }} route
 * @returns {string}
 */
export function buildHash(route) {
  if (!route || !route.view) return '#/';

  if (route.view === 'landing') return '#/';
  if (route.view === 'projects') return '#/projects';

  if (route.view === 'shared' && route.shareToken) {
    let hash = `#/s/${route.shareToken}`;
    if (route.partId) {
      hash += `/s/${route.partId}`;
      hash += `/t/${route.tab && VALID_TABS.includes(route.tab) ? route.tab : 'explicacion'}`;
    }
    return hash;
  }

  if (route.view === 'project' && route.projectId) {
    let hash = `#/p/${route.projectId}`;
    if (route.partId) {
      hash += `/s/${route.partId}`;
      hash += `/t/${route.tab && VALID_TABS.includes(route.tab) ? route.tab : 'explicacion'}`;
    }
    return hash;
  }

  return '#/';
}

/**
 * Update location.hash (adds history entry).
 * @param {{ view: string, projectId?: string, shareToken?: string, partId?: number, tab?: string }} route
 */
export function pushRoute(route) {
  const hash = buildHash(route);
  if (typeof location !== 'undefined' && location.hash !== hash) {
    location.hash = hash;
  }
}

/**
 * Replace location.hash without adding history entry.
 * @param {{ view: string, projectId?: string, shareToken?: string, partId?: number, tab?: string }} route
 */
export function replaceRoute(route) {
  const hash = buildHash(route);
  if (typeof location !== 'undefined' && typeof history !== 'undefined' && location.hash !== hash) {
    const url = location.pathname + location.search + hash;
    history.replaceState(null, '', url);
  }
}

/**
 * Initialize router with callback for route changes.
 * @param {(route: object) => void} onRoute - Called when hash changes
 * @returns {{ pushRoute: function, replaceRoute: function, parseRoute: function }}
 */
export function initRouter(onRoute) {
  const handleHashChange = () => {
    const route = parseRoute();
    if (route && typeof onRoute === 'function') {
      onRoute(route);
    }
  };

  if (typeof window !== 'undefined') {
    window.addEventListener('hashchange', handleHashChange);
  }

  return {
    pushRoute,
    replaceRoute,
    parseRoute,
  };
}
