/* ============================================================
   EXPLAINER — Share Project Modal
   Create, copy, and revoke share links
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, toast } from './dom.js';
import { api } from './api.js';

export function initShareModal() {
  const modal = $('modal-share');
  const openBtn = $('btn-open-share');
  const closeBtn = $('btn-close-share');
  const linkInput = $('share-link-input');
  const copyBtn = $('btn-copy-share-link');
  const copyBtnText = $('share-copy-btn-text');
  const revokeBtn = $('btn-revoke-share');

  if (!modal || !openBtn) return;

  function closeModal() {
    modal?.closest('.modal-overlay')?.classList.add('hidden');
  }

  function openModal() {
    modal?.closest('.modal-overlay')?.classList.remove('hidden');
  }

  openBtn.addEventListener('click', async () => {
    if (!state.currentProjectId || state.isSharedView) return;
    const project = state.currentProject;
    if (project?.status !== 'completed') {
      toast('Solo se pueden compartir proyectos completados', 'error');
      return;
    }

    let shareUrl = '';
    if (project?.share_token) {
      const base = window.location.origin + window.location.pathname;
      shareUrl = `${base}#/s/${project.share_token}`;
    } else {
      try {
        const res = await api(`/api/projects/${state.currentProjectId}/share`, { method: 'POST' });
        shareUrl = res.share_url || '';
        if (res.share_token && state.currentProject) {
          state.currentProject.share_token = res.share_token;
        }
      } catch (err) {
        toast(err.message || 'Error al crear el enlace', 'error');
        return;
      }
    }

    if (linkInput) linkInput.value = shareUrl;
    openModal();
  });

  closeBtn?.addEventListener('click', closeModal);
  modal?.closest('.modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === modal.closest('.modal-overlay')) closeModal();
  });

  copyBtn?.addEventListener('click', async () => {
    const url = linkInput?.value;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      if (copyBtnText) copyBtnText.textContent = '¡Copiado!';
      toast('Enlace copiado al portapapeles', 'success');
      setTimeout(() => {
        if (copyBtnText) copyBtnText.textContent = 'Copiar enlace';
      }, 2000);
    } catch (_) {
      toast('No se pudo copiar el enlace', 'error');
    }
  });

  revokeBtn?.addEventListener('click', async () => {
    if (!state.currentProjectId) return;
    if (!confirm('¿Revocar el enlace? Las personas que lo tengan dejarán de poder ver el proyecto.')) return;
    try {
      await api(`/api/projects/${state.currentProjectId}/share`, { method: 'DELETE' });
      if (state.currentProject) state.currentProject.share_token = null;
      toast('Enlace revocado', 'success');
      closeModal();
    } catch (err) {
      toast(err.message || 'Error al revocar', 'error');
    }
  });
}
