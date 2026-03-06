/**
 * Unit tests for dom.js formatters and utilities.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  formatDate,
  formatBytes,
  statusLabel,
  formatIconForResource,
  escHtml,
  nl2p,
} from '../../frontend/js/dom.js';

describe('dom.js', () => {
  describe('formatDate', () => {
    it('returns empty string for null/undefined', () => {
      expect(formatDate(null)).toBe('');
      expect(formatDate(undefined)).toBe('');
    });

    it('formats ISO date in Spanish locale', () => {
      const result = formatDate('2024-03-15T12:00:00Z');
      expect(result).toMatch(/\d{1,2}/);
      expect(result).toMatch(/mar|abr|may|jun|jul|ago|sep|oct|nov|dic|ene|feb/);
      expect(result).toMatch(/2024/);
    });
  });

  describe('formatBytes', () => {
    it('formats bytes < 1024 as B', () => {
      expect(formatBytes(0)).toBe('0 B');
      expect(formatBytes(500)).toBe('500 B');
      expect(formatBytes(1023)).toBe('1023 B');
    });

    it('formats bytes >= 1024 as KB', () => {
      expect(formatBytes(1024)).toBe('1.0 KB');
      expect(formatBytes(2048)).toBe('2.0 KB');
      expect(formatBytes(1536)).toBe('1.5 KB');
    });

    it('formats bytes >= 1024*1024 as MB', () => {
      expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
      expect(formatBytes(2.5 * 1024 * 1024)).toBe('2.5 MB');
    });
  });

  describe('statusLabel', () => {
    it('returns Spanish labels for known statuses', () => {
      expect(statusLabel('pending')).toBe('Pendiente');
      expect(statusLabel('uploading')).toBe('Subiendo');
      expect(statusLabel('segmenting')).toBe('Segmentando');
      expect(statusLabel('processing')).toBe('Procesando');
      expect(statusLabel('completed')).toBe('Completado');
      expect(statusLabel('error')).toBe('Error');
    });

    it('returns raw status for unknown', () => {
      expect(statusLabel('unknown')).toBe('unknown');
    });
  });

  describe('formatIconForResource', () => {
    it('returns emoji for known formats', () => {
      expect(formatIconForResource('libro_texto_articulo')).toBe('📖');
      expect(formatIconForResource('documental_pelicula_serie')).toBe('🎬');
      expect(formatIconForResource('sitio_web_recurso_digital')).toBe('🌐');
      expect(formatIconForResource('podcast_audio')).toBe('🎧');
      expect(formatIconForResource('curso_conferencia_material_educativo')).toBe('🎓');
    });

    it('returns default pin for unknown', () => {
      expect(formatIconForResource('unknown')).toBe('📌');
    });
  });

  describe('escHtml', () => {
    it('returns empty string for null/undefined', () => {
      expect(escHtml(null)).toBe('');
      expect(escHtml(undefined)).toBe('');
    });

    it('escapes HTML special characters', () => {
      expect(escHtml('&')).toBe('&amp;');
      expect(escHtml('<')).toBe('&lt;');
      expect(escHtml('>')).toBe('&gt;');
      expect(escHtml('"')).toBe('&quot;');
      expect(escHtml("'")).toBe('&#39;');
      expect(escHtml('<script>alert(1)</script>')).toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
    });

    it('leaves safe text unchanged', () => {
      expect(escHtml('Hello World')).toBe('Hello World');
    });
  });

  describe('nl2p', () => {
    it('returns empty string for null/undefined', () => {
      expect(nl2p(null)).toBe('');
      expect(nl2p(undefined)).toBe('');
    });

    it('wraps paragraphs in <p> tags', () => {
      const result = nl2p('First para\n\nSecond para');
      expect(result).toContain('<p>');
      expect(result).toContain('First para');
      expect(result).toContain('Second para');
    });

    it('escapes HTML in content', () => {
      const result = nl2p('Test <script>');
      expect(result).toContain('&lt;script&gt;');
    });
  });
});
