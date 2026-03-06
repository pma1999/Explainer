/* ============================================================
   EXPLAINER — DOM Helpers & Formatters
   ============================================================ */

export const $ = (id) => document.getElementById(id);
export const show = (el) => el && el.classList.remove('hidden');
export const hide = (el) => el && el.classList.add('hidden');

let _onViewChange = null;
export function setViewChangeCallback(fn) {
  _onViewChange = fn;
}

export function showView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  $(viewId).classList.add('active');
  if (_onViewChange) _onViewChange();
}

export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export function statusLabel(status) {
  const map = {
    pending: 'Pendiente', uploading: 'Subiendo', segmenting: 'Segmentando',
    processing: 'Procesando', completed: 'Completado', error: 'Error',
  };
  return map[status] || status;
}

export function formatIconForResource(format) {
  const map = {
    libro_texto_articulo: '📖',
    documental_pelicula_serie: '🎬',
    sitio_web_recurso_digital: '🌐',
    podcast_audio: '🎧',
    curso_conferencia_material_educativo: '🎓',
  };
  return map[format] || '📌';
}

export function toast(msg, type = '') {
  const container = $('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 3000);
  setTimeout(() => el.remove(), 3400);
}

export function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function nl2p(str) {
  if (!str) return '';
  return str.split(/\n\n+/)
    .map(p => p.trim())
    .filter(Boolean)
    .map(p => `<p>${escHtml(p)}</p>`)
    .join('');
}
