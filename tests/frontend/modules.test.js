/**
 * Module load tests - verify all frontend modules load without errors.
 */
import { describe, it, expect } from 'vitest';

describe('Module loading', () => {
  it('loads state.js', async () => {
    const { state, supabaseClient } = await import('../../frontend/js/state.js');
    expect(state).toBeDefined();
    expect(state).toHaveProperty('currentProjectId');
    expect(supabaseClient).toBeNull();
  });

  it('loads dom.js', async () => {
    const dom = await import('../../frontend/js/dom.js');
    expect(dom.formatDate).toBeTypeOf('function');
    expect(dom.formatBytes).toBeTypeOf('function');
    expect(dom.escHtml).toBeTypeOf('function');
  });

  it('loads api.js', async () => {
    const api = await import('../../frontend/js/api.js');
    expect(api.api).toBeTypeOf('function');
    expect(api.getAccessToken).toBeTypeOf('function');
  });

  it('loads storage.js', async () => {
    const storage = await import('../../frontend/js/storage.js');
    expect(storage.mergeProjects).toBeTypeOf('function');
    expect(storage.loadLocalBackup).toBeTypeOf('function');
  });

  it('loads auth.js', async () => {
    const auth = await import('../../frontend/js/auth.js');
    expect(auth.initAuth).toBeTypeOf('function');
    expect(auth.refreshApiKeyStatus).toBeTypeOf('function');
  });

  it('loads landing.js', async () => {
    const landing = await import('../../frontend/js/landing.js');
    expect(landing.initLanding).toBeTypeOf('function');
    expect(landing.extractYouTubeVideoId).toBeTypeOf('function');
  });

  it('loads projects.js', async () => {
    const projects = await import('../../frontend/js/projects.js');
    expect(projects.loadProjectsView).toBeTypeOf('function');
    expect(projects.openProjectView).toBeTypeOf('function');
  });

  it('loads projectView.js', async () => {
    const pv = await import('../../frontend/js/projectView.js');
    expect(pv.renderProjectView).toBeTypeOf('function');
    expect(pv.renderSidebarNav).toBeTypeOf('function');
  });

  it('loads sse.js', async () => {
    const sse = await import('../../frontend/js/sse.js');
    expect(sse.startSSE).toBeTypeOf('function');
    expect(sse.stopPolling).toBeTypeOf('function');
  });

  it('loads export.js', async () => {
    const exp = await import('../../frontend/js/export.js');
    expect(exp.exportProjectsBackup).toBeTypeOf('function');
    expect(exp.importProjectsBackup).toBeTypeOf('function');
  });

  it('loads main.js without syntax errors', async () => {
    await import('../../frontend/js/main.js');
    // If we get here, the module loaded and bootstrap ran without throwing
  });
});
