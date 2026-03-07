/* ============================================================
   EXPLAINER — Backup & Obsidian Export
   ============================================================ */

import { state } from './state.js';
import { $, show, hide, toast, escHtml } from './dom.js';
import { api } from './api.js';
import {
  loadBackupAsync,
  mergeProjects,
  syncProjectsToBackup,
  payloadToJsonFile,
  invalidateProjectsCache,
} from './storage.js';
import { loadProjectsView } from './projects.js';

export async function exportProjectsBackup() {
  try {
    const local = await loadBackupAsync(state.user?.id);
    const localProjects = local.projects;
    let payload = { version: 1, exported_at: new Date().toISOString(), projects: localProjects };

    try {
      const serverPayload = await api('/api/projects/export');
      payload = {
        ...serverPayload,
        projects: mergeProjects(serverPayload.projects || [], localProjects),
      };
    } catch (_) {}

    const syncResult = await syncProjectsToBackup(payload.projects, state.user?.id);
    if (!syncResult.ok && syncResult.quotaExceeded) {
      toast('Backup exportado, pero no se pudo guardar copia local (almacenamiento lleno).', 'warning');
    }

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `explainer-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Backup exportado', 'success');
  } catch (err) {
    toast('Error exportando backup: ' + err.message, 'error');
  }
}

export async function importProjectsBackup(file) {
  try {
    const parsed = JSON.parse(await file.text());
    if (!parsed || !Array.isArray(parsed.projects)) {
      throw new Error('Formato inválido: el backup no contiene una lista de proyectos');
    }

    const local = await loadBackupAsync(state.user?.id);
    const localMerged = mergeProjects(parsed.projects, local.projects);
    const syncResult = await syncProjectsToBackup(localMerged, state.user?.id);
    if (!syncResult.ok && syncResult.quotaExceeded) {
      toast('Importación guardada en archivo, pero no se pudo guardar copia local (almacenamiento lleno).', 'warning');
    }

    const fd = new FormData();
    fd.append('file', payloadToJsonFile(parsed, file.name || 'explainer-import.json'));

    const result = await api('/api/projects/import', { method: 'POST', body: fd });
    invalidateProjectsCache();
    toast(`Importación completada: ${result.imported} importados, ${result.skipped} omitidos`, 'success');
    loadProjectsView();
  } catch (err) {
    toast('Error importando backup: ' + err.message, 'error');
  }
}

export function sanitizeFolderName(raw) {
  return raw
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
}

export function buildSectionFolderName(numero, titulo) {
  return `${String(numero).padStart(2, '0')} - ${sanitizeFolderName(titulo)}`;
}

export function prefillFromProjectName(projectName) {
  if (!projectName) return { autor: '', obra: '' };
  const parts = projectName.split(/[-—]/);
  if (parts.length >= 2) {
    return { autor: parts[0].trim(), obra: parts.slice(1).join('-').trim() };
  }
  return { autor: '', obra: projectName.trim() };
}

function loadJSZip() {
  if (window.JSZip) return Promise.resolve(window.JSZip);
  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';
    script.onload = () => resolve(window.JSZip || null);
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
}

function triggerDownload(blob, filename) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      resolve();
    }, 800);
  });
}

function formatExplicacionMd(data, autor, obra, partName) {
  let md = '';
  if (data.introduccion) {
    md += `> [!summary] Introducción\n> ${data.introduccion.replace(/\n/g, '\n> ')}\n\n---\n\n`;
  }
  md += `# DESARROLLO TEMÁTICO DETALLADO\n\n`;
  if (data.desarrollo && data.desarrollo.length > 0) {
    data.desarrollo.forEach((sec, i) => {
      md += `## ${i + 1}. ${sec.titulo_seccion}\n\n`;
      if (sec.explicacion_introductoria) {
        md += `${sec.explicacion_introductoria}\n\n`;
      }
      if (sec.subsecciones && sec.subsecciones.length > 0) {
        sec.subsecciones.forEach((subsec, j) => {
          md += `### ${i + 1}.${j + 1}. ${subsec.titulo_subseccion}\n\n`;
          md += `${subsec.explicacion_detallada}\n\n`;
        });
      }
      md += `---\n\n`;
    });
  }
  if (data.conclusion) {
    md += `> [!summary] Conclusión\n> ${data.conclusion.replace(/\n/g, '\n> ')}\n\n`;
  }
  if (data.conexiones_contextuales && data.conexiones_contextuales.length > 0) {
    md += `\n---\n\n## Conexiones Contextuales\n\n`;
    data.conexiones_contextuales.forEach(cx => {
      md += `### ${cx.seccion_temario_relacionada}\n\n${cx.descripcion_conexion}\n\n`;
    });
  }
  return md.trim() + '\n';
}

function formatRecorridoMd(data, autor, obra, partName) {
  let md = `# ${autor} — Recorrido Anotado (${partName})\n\n`;
  md += `> [!summary] Introducción orientadora\n> Recorrido analítico correspondiente a la sección **${partName}** de la obra **${obra}** por **${autor}**.\n\n---\n\n`;
  md += `## Recorrido Anotado\n\n`;

  if (data.recorrido_anotado && data.recorrido_anotado.length > 0) {
    data.recorrido_anotado.forEach(entry => {
      if (entry.cita_textual && entry.cita_textual.trim().length > 0) {
        md += `> [!quote] ${autor}, *${obra}*, ${entry.ubicacion}\n> «${entry.cita_textual.replace(/\n/g, '\n> ')}»\n\n`;
      } else {
        md += `> [!quote] ${autor}, *${obra}*, ${entry.ubicacion}\n> *(Contenido no citado textualmente)*\n\n`;
      }
      if (entry.traduccion) {
        md += `> [!cite]- **Traducción**\n> «${entry.traduccion.replace(/\n/g, '\n> ')}»\n\n`;
      }
      if (entry.apuntes_traductologicos) {
        md += `> *Apunte traductológico:* ${entry.apuntes_traductologicos}\n\n`;
      }
      if (entry.anotacion) {
        md += `> [!info]+ **Anotación**\n> ${entry.anotacion.replace(/\n/g, '\n> ')}\n\n`;
      }
      md += `---\n\n`;
    });
  }

  if (data.sintesis_de_cobertura) {
    md += `## Síntesis de Cobertura\n\n`;
    md += `> [!summary] Alcance del recorrido\n`;
    const s = data.sintesis_de_cobertura;
    if (s.secciones_procesadas) md += `> **Secciones procesadas:** ${s.secciones_procesadas}\n`;
    if (s.alcance) md += `> **Alcance:** ${s.alcance}\n`;
    if (s.contenido_excluido) md += `> **Contenido excluido:** ${s.contenido_excluido}\n`;
    if (s.idioma_original) md += `> **Idioma original:** ${s.idioma_original}\n>\n`;
    if (s.observaciones_globales) {
      md += `> [!abstract] Observaciones globales\n> ${s.observaciones_globales.replace(/\n/g, '\n> ')}\n\n`;
    }
  }
  return md.trim() + '\n';
}

function formatRecursosMd(data, autor, obra, partName) {
  let md = `# MAPA DE RECURSOS: ${data.titulo_mapa || partName}\n\n`;
  md += `**Autor:** ${autor}  \n**Obra:** *${obra}*\n\n---\n\n`;
  if (data.vision_general) {
    md += `${data.vision_general}\n\n---\n\n`;
  }
  if (data.ejes_tematicos && data.ejes_tematicos.length > 0) {
    data.ejes_tematicos.forEach((eje, i) => {
      md += `## ${i + 1}. ${eje.nombre_eje}\n\n`;
      if (eje.recursos && eje.recursos.length > 0) {
        eje.recursos.forEach(r => {
          const tipoIcon = r.formato === 'documental' ? '🎬' : r.formato?.includes('video') ? '🎥' : r.formato?.includes('podcast') ? '🎧' : '📚';
          md += `> [!tip]+ ${tipoIcon} ${r.titulo}\n`;
          md += `> **Autor/Creador:** ${r.autor_creador}  \n`;
          if (r.tipo_y_datos) md += `> **Tipo:** ${r.tipo_y_datos}  \n`;
          if (r.idioma) md += `> **Idioma:** ${r.idioma}  \n`;
          md += `> \n`;
          if (r.conexion_con_texto) {
            md += `> **Conexión con el texto:**  \n> ${r.conexion_con_texto.replace(/\n/g, '\n> ')}\n> \n`;
          }
          if (r.nivel_y_accesibilidad) {
            md += `> **Nivel y accesibilidad:**  \n> ${r.nivel_y_accesibilidad.replace(/\n/g, '\n> ')}\n`;
          }
          if (r.nota) {
            md += `> \n> **Nota:** ${r.nota.replace(/\n/g, '\n> ')}\n`;
          }
          md += `\n---\n\n`;
        });
      }
    });
  }
  if (data.nota_de_integridad) {
    md += `> [!abstract] Nota de integridad\n> ${data.nota_de_integridad.replace(/\n/g, '\n> ')}\n\n---\n\n`;
  }
  const d = new Date();
  md += `**Fecha de creación:** ${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}\n`;
  return md.trim() + '\n';
}

function buildFullExportSections(autor, obra) {
  const project = state.currentProject;
  if (!project?.segmentation?.partes) return null;

  const sections = [];
  for (const parte of project.segmentation.partes) {
    const partData = project.partes_contenido?.[String(parte.numero)];
    if (!partData || partData.status !== 'completed') continue;

    const folderName = buildSectionFolderName(parte.numero, parte.titulo);
    const files = [];

    if (partData.explainer) {
      files.push({
        filename: 'explicacion.md',
        content: formatExplicacionMd(partData.explainer, autor, obra, parte.titulo)
      });
    }
    if (partData.recorrido) {
      files.push({
        filename: 'recorrido-anotado.md',
        content: formatRecorridoMd(partData.recorrido, autor, obra, parte.titulo)
      });
    }
    if (partData.resources) {
      files.push({
        filename: 'recursos.md',
        content: formatRecursosMd(partData.resources, autor, obra, parte.titulo)
      });
    }

    if (files.length > 0) sections.push({ folderName, files });
  }

  return sections.length > 0 ? sections : null;
}

async function exportViaDirectoryPicker(sections) {
  const rootHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
  for (const section of sections) {
    const dirHandle = await rootHandle.getDirectoryHandle(section.folderName, { create: true });
    for (const file of section.files) {
      const fileHandle = await dirHandle.getFileHandle(file.filename, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(new Blob([file.content], { type: 'text/markdown;charset=utf-8' }));
      await writable.close();
    }
  }
}

async function exportViaZip(sections, projectName) {
  const JSZip = await loadJSZip();
  if (!JSZip) return false;

  const zip = new JSZip();
  for (const section of sections) {
    for (const file of section.files) {
      zip.file(`${section.folderName}/${file.filename}`, file.content);
    }
  }

  const blob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
  await triggerDownload(blob, `${sanitizeFolderName(projectName || 'proyecto')}-obsidian.zip`);
  return true;
}

async function exportViaSequentialDownload(sections) {
  for (const section of sections) {
    for (const file of section.files) {
      const blob = new Blob([file.content], { type: 'text/markdown;charset=utf-8' });
      await triggerDownload(blob, `${section.folderName} — ${file.filename}`);
    }
  }
}

export function initObsidianExport() {
  const modal = $('modal-export-obsidian');
  const btnOpen = $('btn-open-export');
  const btnClose = $('btn-close-export');
  const btnCopy = $('btn-copy-obsidian');
  const form = $('form-export-obsidian');
  const inputAutor = $('export-autor');
  const inputObra = $('export-obra');

  if (!modal || !btnOpen || !btnClose || !btnCopy || !form) return;

  btnOpen.addEventListener('click', () => {
    if (state.currentProject && state.currentProject.name) {
      const { autor, obra } = prefillFromProjectName(state.currentProject.name);
      inputAutor.value = autor;
      inputObra.value = obra;
    } else {
      inputAutor.value = '';
      inputObra.value = '';
    }
    show(modal);
  });

  const closeModal = () => hide(modal);
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  const getExportData = () => {
    if (!state.currentProject || !state.currentPartId) {
      toast('No hay contenido seleccionado para exportar.', 'error');
      return null;
    }

    const partData = state.currentProject.partes_contenido?.[String(state.currentPartId)];
    if (!partData) {
      toast('El contenido de esta parte aún no está listo.', 'warning');
      return null;
    }

    const parte = state.currentProject.segmentation?.partes?.find(p => p.numero === state.currentPartId);
    const partName = parte?.titulo || `Parte ${state.currentPartId}`;
    const autor = inputAutor.value.trim() || 'Desconocido';
    const obra = inputObra.value.trim() || 'Desconocida';

    const scope = document.querySelector('input[name="export-scope"]:checked')?.value || 'current';
    const tabs = scope === 'current' ? [state.activeTab] : ['explicacion', 'recorrido', 'recursos'];

    const files = [];
    if (tabs.includes('explicacion') && partData.explainer) {
      files.push({
        markdown: formatExplicacionMd(partData.explainer, autor, obra, partName),
        filename: 'explicacion.md'
      });
    }
    if (tabs.includes('recorrido') && partData.recorrido) {
      files.push({
        markdown: formatRecorridoMd(partData.recorrido, autor, obra, partName),
        filename: 'recorrido-anotado.md'
      });
    }
    if (tabs.includes('recursos') && partData.resources) {
      files.push({
        markdown: formatRecursosMd(partData.resources, autor, obra, partName),
        filename: 'recursos.md'
      });
    }

    if (files.length === 0) {
      toast('No se encontró contenido en las pestañas seleccionadas.', 'warning');
      return null;
    }
    return files;
  };

  btnCopy.addEventListener('click', () => {
    const files = getExportData();
    if (!files) return;
    const textToCopy = files.map(f => f.markdown).join('\n\n\n======================================================\n\n\n');
    navigator.clipboard.writeText(textToCopy).then(() => {
      toast(files.length > 1 ? 'Todos copiados al portapapeles' : 'Copiado al portapapeles', 'success');
      closeModal();
    }).catch(err => {
      toast('Error al copiar: ' + err, 'error');
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const files = getExportData();
    if (!files) return;

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

    try {
      if (window.showDirectoryPicker && !isMobile) {
        try {
          const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
          for (const file of files) {
            const fileHandle = await dirHandle.getFileHandle(file.filename, { create: true });
            const writable = await fileHandle.createWritable();
            const blob = new Blob([file.markdown], { type: 'text/markdown;charset=utf-8' });
            await writable.write(blob);
            await writable.close();
          }
          toast(`Exportados ${files.length} archivo(s) a la carpeta de Obsidian`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 1 (Native Folder) falló:', err);
        }
      }

      const fileObjects = files.map(f => new File([f.markdown], f.filename, { type: 'text/plain' }));
      if (navigator.canShare && navigator.canShare({ files: fileObjects })) {
        try {
          await navigator.share({
            title: `Explainer: ${files.length} archivos`,
            files: fileObjects
          });
          toast(`Enviado a Obsidian / Compartir`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 2 (Native Share) falló:', err);
        }
      }

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        await new Promise(resolve => setTimeout(resolve, i * 1000));
        const blob = new Blob([file.markdown], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = file.filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 30000);
      }

      toast(`Descargando ${files.length} archivo(s)`, 'info');
      closeModal();

    } catch (globalErr) {
      console.error('Export Error:', globalErr);
      toast('Error durante la exportación: ' + globalErr.message, 'error');
    }
  });
}

export function initFullProjectExport() {
  const modal = $('modal-full-export');
  const btnOpen = $('btn-open-full-export');
  const btnClose = $('btn-close-full-export');
  const form = $('form-full-export');
  const inputAutor = $('full-export-autor');
  const inputObra = $('full-export-obra');
  const summaryText = $('full-export-summary-text');
  const sectionList = $('full-export-section-list');
  const btnSubmit = $('btn-do-full-export');

  if (!modal || !btnOpen) return;

  btnOpen.addEventListener('click', () => {
    const project = state.currentProject;
    if (!project) return;

    const { autor, obra } = prefillFromProjectName(project.name);
    inputAutor.value = autor;
    inputObra.value = obra;

    const partes = project.segmentation?.partes ?? [];
    const readyCount = partes.filter(p =>
      project.partes_contenido?.[String(p.numero)]?.status === 'completed'
    ).length;
    summaryText.textContent = readyCount === partes.length
      ? `${readyCount} secciones · ${readyCount * 3} archivos listos para exportar`
      : `${readyCount} de ${partes.length} secciones listas · ${readyCount * 3} archivos`;

    sectionList.innerHTML = partes.map(parte => {
      const isReady = project.partes_contenido?.[String(parte.numero)]?.status === 'completed';
      return `<div class="export-section-row${isReady ? ' ready' : ''}">
        <span class="row-dot"></span>
        <span>${escHtml(buildSectionFolderName(parte.numero, parte.titulo))}</span>
      </div>`;
    }).join('');

    btnSubmit.disabled = readyCount === 0;
    show(modal);
  });

  const closeModal = () => hide(modal);
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!state.currentProject) return;

    const autor = inputAutor.value.trim() || 'Desconocido';
    const obra = inputObra.value.trim() || 'Desconocida';
    const sections = buildFullExportSections(autor, obra);

    if (!sections) {
      toast('No hay secciones completadas para exportar.', 'warning');
      return;
    }

    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const btnText = btnSubmit.querySelector('.btn-text');
    const origText = btnText.textContent;
    btnSubmit.disabled = true;
    btnText.textContent = 'Exportando...';

    try {
      if (window.showDirectoryPicker && !isMobile) {
        try {
          await exportViaDirectoryPicker(sections);
          toast(`Proyecto exportado: ${sections.length} secciones en tu vault de Obsidian`, 'success');
          closeModal();
          return;
        } catch (err) {
          if (err.name === 'AbortError') { closeModal(); return; }
          console.warn('Strategy 1 (showDirectoryPicker) falló:', err);
        }
      }

      try {
        const ok = await exportViaZip(sections, state.currentProject.name);
        if (ok) {
          const total = sections.reduce((n, s) => n + s.files.length, 0);
          toast(`ZIP descargado: ${sections.length} secciones, ${total} archivos`, 'success');
          closeModal();
          return;
        }
        console.warn('Strategy 2: JSZip no disponible, usando descarga plana');
      } catch (err) {
        console.warn('Strategy 2 (JSZip) falló:', err);
      }

      const total = sections.reduce((n, s) => n + s.files.length, 0);
      toast(`Descargando ${total} archivos...`, 'info');
      await exportViaSequentialDownload(sections);
      toast('Descarga completada.', 'success');
      closeModal();

    } catch (globalErr) {
      console.error('Full project export error:', globalErr);
      toast('Error durante la exportación: ' + globalErr.message, 'error');
    } finally {
      btnSubmit.disabled = false;
      btnText.textContent = origText;
    }
  });
}
