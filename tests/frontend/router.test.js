/**
 * Router unit tests - parseRoute and buildHash for all route types.
 */
import { describe, it, expect } from 'vitest';
import { parseRoute, buildHash, VALID_TABS } from '../../frontend/js/router.js';

describe('parseRoute', () => {
  it('returns landing for empty or root hash', () => {
    expect(parseRoute('')).toEqual({ view: 'landing' });
    expect(parseRoute('#')).toEqual({ view: 'landing' });
    expect(parseRoute('#/')).toEqual({ view: 'landing' });
    expect(parseRoute('/')).toEqual({ view: 'landing' });
  });

  it('returns projects for #/projects', () => {
    expect(parseRoute('#/projects')).toEqual({ view: 'projects' });
    expect(parseRoute('/projects')).toEqual({ view: 'projects' });
  });

  it('returns project route with projectId only', () => {
    expect(parseRoute('#/p/abc123')).toEqual({
      view: 'project',
      projectId: 'abc123',
    });
  });

  it('returns project route with partId and tab', () => {
    expect(parseRoute('#/p/abc123/s/2/t/explicacion')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 2,
      tab: 'explicacion',
    });
    expect(parseRoute('#/p/abc123/s/5/t/recorrido')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 5,
      tab: 'recorrido',
    });
    expect(parseRoute('#/p/abc123/s/1/t/recursos')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 1,
      tab: 'recursos',
    });
    expect(parseRoute('#/p/abc123/s/4/t/esquema')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 4,
      tab: 'esquema',
    });
  });

  it('defaults tab to explicacion when partId present but tab missing', () => {
    expect(parseRoute('#/p/abc123/s/2')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 2,
      tab: 'explicacion',
    });
  });

  it('ignores invalid partId or tab in project route', () => {
    expect(parseRoute('#/p/abc123/s/0')).toEqual({
      view: 'project',
      projectId: 'abc123',
    });
    expect(parseRoute('#/p/abc123/s/abc')).toEqual({
      view: 'project',
      projectId: 'abc123',
    });
    expect(parseRoute('#/p/abc123/s/2/t/invalid')).toEqual({
      view: 'project',
      projectId: 'abc123',
      partId: 2,
      tab: 'explicacion',
    });
  });

  it('returns shared route with token only', () => {
    expect(parseRoute('#/s/token-xyz')).toEqual({
      view: 'shared',
      shareToken: 'token-xyz',
    });
  });

  it('returns shared route with partId and tab', () => {
    expect(parseRoute('#/s/token123/s/2/t/explicacion')).toEqual({
      view: 'shared',
      shareToken: 'token123',
      partId: 2,
      tab: 'explicacion',
    });
    expect(parseRoute('#/s/token123/s/3/t/recorrido')).toEqual({
      view: 'shared',
      shareToken: 'token123',
      partId: 3,
      tab: 'recorrido',
    });
    expect(parseRoute('#/s/token123/s/1/t/recursos')).toEqual({
      view: 'shared',
      shareToken: 'token123',
      partId: 1,
      tab: 'recursos',
    });
    expect(parseRoute('#/s/token123/s/4/t/esquema')).toEqual({
      view: 'shared',
      shareToken: 'token123',
      partId: 4,
      tab: 'esquema',
    });
  });

  it('defaults tab to explicacion in shared when partId present', () => {
    expect(parseRoute('#/s/token123/s/2')).toEqual({
      view: 'shared',
      shareToken: 'token123',
      partId: 2,
      tab: 'explicacion',
    });
  });

  it('extracts subsectionId in project route', () => {
    expect(parseRoute('#/p/abc/s/2/t/explicacion/u/subsec-2-0-1')).toEqual({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'explicacion',
      subsectionId: 'subsec-2-0-1',
    });
  });

  it('extracts subsectionId in shared route', () => {
    expect(parseRoute('#/s/sharetoken/s/3/t/recorrido/u/subsec-3-1-0')).toEqual({
      view: 'shared',
      shareToken: 'sharetoken',
      partId: 3,
      tab: 'recorrido',
      subsectionId: 'subsec-3-1-0',
    });
  });

  it('returns null for unknown routes', () => {
    expect(parseRoute('#/unknown')).toBeNull();
    expect(parseRoute('#/p')).toBeNull();
    expect(parseRoute('#/s')).toBeNull();
  });
});

describe('buildHash', () => {
  it('returns #/ for landing or invalid', () => {
    expect(buildHash(null)).toBe('#/');
    expect(buildHash({})).toBe('#/');
    expect(buildHash({ view: 'landing' })).toBe('#/');
  });

  it('returns #/projects for projects view', () => {
    expect(buildHash({ view: 'projects' })).toBe('#/projects');
  });

  it('returns project hash with partId and tab', () => {
    expect(buildHash({ view: 'project', projectId: 'abc' })).toBe('#/p/abc');
    expect(buildHash({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'explicacion',
    })).toBe('#/p/abc/s/2/t/explicacion');
    expect(buildHash({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'recorrido',
    })).toBe('#/p/abc/s/2/t/recorrido');
    expect(buildHash({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'esquema',
    })).toBe('#/p/abc/s/2/t/esquema');
  });

  it('defaults tab to explicacion when invalid in project', () => {
    expect(buildHash({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'invalid',
    })).toBe('#/p/abc/s/2/t/explicacion');
  });

  it('returns shared hash with token, partId and tab', () => {
    expect(buildHash({ view: 'shared', shareToken: 'tok' })).toBe('#/s/tok');
    expect(buildHash({
      view: 'shared',
      shareToken: 'tok',
      partId: 2,
      tab: 'recorrido',
    })).toBe('#/s/tok/s/2/t/recorrido');
  });

  it('appends subsectionId in project hash', () => {
    expect(buildHash({
      view: 'project',
      projectId: 'abc',
      partId: 2,
      tab: 'explicacion',
      subsectionId: 'subsec-2-0-1',
    })).toBe('#/p/abc/s/2/t/explicacion/u/subsec-2-0-1');
  });

  it('appends subsectionId in shared hash', () => {
    expect(buildHash({
      view: 'shared',
      shareToken: 'sharetoken',
      partId: 3,
      tab: 'recorrido',
      subsectionId: 'subsec-3-1-0',
    })).toBe('#/s/sharetoken/s/3/t/recorrido/u/subsec-3-1-0');
  });

  it('returns #/ for missing projectId or shareToken', () => {
    expect(buildHash({ view: 'project' })).toBe('#/');
    expect(buildHash({ view: 'shared' })).toBe('#/');
  });
});

describe('VALID_TABS', () => {
  it('contains every supported tab', () => {
    expect(VALID_TABS).toEqual(['explicacion', 'recorrido', 'recursos', 'esquema']);
  });
});
