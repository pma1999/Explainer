/**
 * Unit tests for export.js utilities.
 */
import { describe, it, expect } from 'vitest';
import {
  sanitizeFolderName,
  buildSectionFolderName,
  prefillFromProjectName,
  formatRecorridoMd,
  formatRecursosMd,
} from '../../frontend/js/export.js';

describe('export.js', () => {
  describe('sanitizeFolderName', () => {
    it('strips diacritics', () => {
      expect(sanitizeFolderName('Ética')).toBe('Etica');
      expect(sanitizeFolderName('Niño')).toBe('Nino');
    });

    it('replaces spaces with hyphens', () => {
      expect(sanitizeFolderName('hello world')).toBe('hello-world');
    });

    it('removes invalid filesystem characters', () => {
      expect(sanitizeFolderName('test<>:"/\\|?*')).not.toMatch(/[<>:"/\\|?*]/);
    });

    it('collapses multiple hyphens', () => {
      expect(sanitizeFolderName('a   b')).toBe('a-b');
    });

    it('trims leading/trailing hyphens', () => {
      expect(sanitizeFolderName('  test  ')).toBe('test');
    });

    it('caps length at 60', () => {
      const long = 'a'.repeat(100);
      expect(sanitizeFolderName(long)).toHaveLength(60);
    });
  });

  describe('buildSectionFolderName', () => {
    it('zero-pads section number', () => {
      expect(buildSectionFolderName(3, 'Title')).toMatch(/^03 - /);
      expect(buildSectionFolderName(12, 'Title')).toMatch(/^12 - /);
    });

    it('sanitizes title', () => {
      const result = buildSectionFolderName(1, 'Ética de la Virtud');
      expect(result).toMatch(/01 - .*Etica/);
    });
  });

  describe('prefillFromProjectName', () => {
    it('returns empty for null/undefined', () => {
      expect(prefillFromProjectName(null)).toEqual({ autor: '', obra: '' });
      expect(prefillFromProjectName(undefined)).toEqual({ autor: '', obra: '' });
    });

    it('splits on hyphen', () => {
      expect(prefillFromProjectName('Autor - Obra')).toEqual({ autor: 'Autor', obra: 'Obra' });
    });

    it('splits on em dash', () => {
      expect(prefillFromProjectName('Autor — Obra')).toEqual({ autor: 'Autor', obra: 'Obra' });
    });

    it('joins multiple parts as obra', () => {
      expect(prefillFromProjectName('Autor - Obra Parte 1')).toEqual({
        autor: 'Autor',
        obra: 'Obra Parte 1',
      });
    });

    it('returns single part as obra when no separator', () => {
      expect(prefillFromProjectName('Solo Obra')).toEqual({ autor: '', obra: 'Solo Obra' });
    });
  });

  describe('formatRecorridoMd', () => {
    it('exports annotated quotes with the Obsidian annotation callout', () => {
      const md = formatRecorridoMd({
        recorrido_anotado: [{
          ubicacion: 'p. 44',
          cita_textual: 'Original quote',
          traduccion: 'Traducción al castellano',
          apuntes_traductologicos: 'Matiz de traducción.',
          anotacion: 'Primera línea.\nSegunda línea.',
        }],
      }, 'Autor', 'Obra', 'Parte I');

      expect(md).toContain('> [!quote] Autor, *Obra*, p. 44\n> «Original quote»');
      expect(md).toContain('>\n> **Traducción:** «Traducción al castellano»');
      expect(md).toContain('> [!note]- Apunte traductológico\n> Matiz de traducción.');
      expect(md).toContain('> [!annotation]+ Anotación\n> Primera línea.\n> Segunda línea.');
      expect(md).not.toContain('[!info]');
      expect(md).not.toContain('**Anotación**');
    });

    it('omits the location comma when the quote has no page or location', () => {
      const md = formatRecorridoMd({
        recorrido_anotado: [{
          ubicacion: '',
          cita_textual: '"Cita ya entrecomillada"',
          traduccion: '',
          apuntes_traductologicos: '',
          anotacion: 'Anotación breve.',
        }],
      }, 'Autor', 'Obra', 'Parte I');

      expect(md).toContain('> [!quote] Autor, *Obra*\n> «Cita ya entrecomillada»');
      expect(md).not.toContain('Autor, *Obra*, \n');
      expect(md).not.toContain('undefined');
    });
  });

  describe('formatRecursosMd', () => {
    it('includes an actionable URL line when the resource has an http(s) url', () => {
      const md = formatRecursosMd({
        titulo_mapa: 'Mapa',
        ejes_tematicos: [{
          nombre_eje: 'Contexto',
          recursos: [{
            titulo: 'Artículo en línea',
            autor_creador: 'Autor X',
            url: 'https://example.com/articulo',
          }],
        }],
      }, 'Autor', 'Obra', 'Parte I');

      expect(md).toContain('> **URL:** [Artículo en línea](https://example.com/articulo)  \n');
      expect(md).toContain('> **Autor/Creador:** Autor X  \n');
    });

    it('omits the URL line when url is missing or not http(s)', () => {
      const md = formatRecursosMd({
        titulo_mapa: 'Mapa',
        ejes_tematicos: [{
          nombre_eje: 'Contexto',
          recursos: [
            { titulo: 'Sin URL', autor_creador: 'A' },
            { titulo: 'Raro', autor_creador: 'B', url: 'ftp://servidor/archivo' },
          ],
        }],
      }, 'Autor', 'Obra', 'Parte I');

      expect(md).not.toContain('**URL:**');
    });
  });
});
