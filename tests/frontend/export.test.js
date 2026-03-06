/**
 * Unit tests for export.js utilities.
 */
import { describe, it, expect } from 'vitest';
import {
  sanitizeFolderName,
  buildSectionFolderName,
  prefillFromProjectName,
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
});
