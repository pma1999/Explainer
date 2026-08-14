/**
 * Unit tests for auth session storage behavior in state.js.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import {
  AUTH_PERSISTENCE_PREFERENCE_KEY,
  createSupabaseAuthStorage,
  setRememberSessionPreference,
  state,
  CODEX_LINK_CACHE_KEY_PREFIX,
} from '../../frontend/js/state.js';

const AUTH_KEY = 'sb-test-auth-token';

describe('state.js auth session storage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('stores the auth session in sessionStorage when remember me is disabled', () => {
    const storage = createSupabaseAuthStorage();

    setRememberSessionPreference(false);
    storage.setItem(AUTH_KEY, 'session-value');

    expect(sessionStorage.getItem(AUTH_KEY)).toBe('session-value');
    expect(localStorage.getItem(AUTH_KEY)).toBeNull();
    expect(localStorage.getItem(AUTH_PERSISTENCE_PREFERENCE_KEY)).toBe('0');
  });

  it('stores the auth session in localStorage when remember me is enabled', () => {
    const storage = createSupabaseAuthStorage();

    setRememberSessionPreference(true);
    storage.setItem(AUTH_KEY, 'persistent-value');

    expect(localStorage.getItem(AUTH_KEY)).toBe('persistent-value');
    expect(sessionStorage.getItem(AUTH_KEY)).toBeNull();
    expect(localStorage.getItem(AUTH_PERSISTENCE_PREFERENCE_KEY)).toBe('1');
  });

  it('infers remember me for legacy persisted sessions already stored in localStorage', () => {
    const storage = createSupabaseAuthStorage();

    localStorage.setItem(AUTH_KEY, 'legacy-value');

    expect(storage.getItem(AUTH_KEY)).toBe('legacy-value');
    expect(localStorage.getItem(AUTH_PERSISTENCE_PREFERENCE_KEY)).toBe('1');
  });

  it('does not revive a stale localStorage session when remember me is explicitly disabled', () => {
    const storage = createSupabaseAuthStorage();

    setRememberSessionPreference(false);
    localStorage.setItem(AUTH_KEY, 'stale-local-session');

    expect(storage.getItem(AUTH_KEY)).toBeNull();
  });

  it('clears auth session state from both browser storages on removeItem', () => {
    const storage = createSupabaseAuthStorage();

    localStorage.setItem(AUTH_KEY, 'local-value');
    sessionStorage.setItem(AUTH_KEY, 'session-value');

    storage.removeItem(AUTH_KEY);

    expect(localStorage.getItem(AUTH_KEY)).toBeNull();
    expect(sessionStorage.getItem(AUTH_KEY)).toBeNull();
  });

  it('exposes the codex link state fields and cache key prefix', () => {
    expect(state).toHaveProperty('hasCodexLink', false);
    expect(state).toHaveProperty('codexLinkStatus', 'loading');
    expect(state).toHaveProperty('codexPlanType', null);
    expect(CODEX_LINK_CACHE_KEY_PREFIX).toBe('explainer.codexLinkStatus.v1.');
  });
});
