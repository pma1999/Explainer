/**
 * Unit tests for landing.js YouTube helpers.
 */
import { describe, it, expect } from 'vitest';
import {
  extractYouTubeVideoId,
  isValidYouTubeUrl,
  normalizeWebUrl,
  isValidWebUrl,
  isExplainerProviderSupportedForSource,
  validateExplainerProviderSelection,
} from '../../frontend/js/landing.js';

describe('landing.js', () => {
  describe('extractYouTubeVideoId', () => {
    it('extracts from youtube.com/watch?v= format', () => {
      expect(extractYouTubeVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
    });

    it('extracts from youtu.be/ format', () => {
      expect(extractYouTubeVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
    });

    it('extracts from youtube.com/embed/ format', () => {
      expect(extractYouTubeVideoId('https://www.youtube.com/embed/dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
    });

    it('extracts bare 11-char id', () => {
      expect(extractYouTubeVideoId('dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
    });

    it('returns null for invalid URLs', () => {
      expect(extractYouTubeVideoId('https://example.com')).toBeNull();
      expect(extractYouTubeVideoId('not a url')).toBeNull();
      expect(extractYouTubeVideoId('')).toBeNull();
    });
  });

  describe('isValidYouTubeUrl', () => {
    it('returns true for valid URLs', () => {
      expect(isValidYouTubeUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ')).toBe(true);
      expect(isValidYouTubeUrl('dQw4w9WgXcQ')).toBe(true);
    });

    it('returns false for invalid', () => {
      expect(isValidYouTubeUrl('')).toBe(false);
      expect(isValidYouTubeUrl('   ')).toBe(false);
      expect(isValidYouTubeUrl('https://vimeo.com/123')).toBe(false);
    });
  });

  describe('normalizeWebUrl', () => {
    it('normalizes valid public http/https URLs and drops fragments', () => {
      expect(normalizeWebUrl('https://example.com/article#section')).toBe('https://example.com/article');
      expect(normalizeWebUrl('http://example.com/path?q=1#hash')).toBe('http://example.com/path?q=1');
    });

    it('returns null for invalid or unsupported URLs', () => {
      expect(normalizeWebUrl('')).toBeNull();
      expect(normalizeWebUrl('nota-url')).toBeNull();
      expect(normalizeWebUrl('ftp://example.com/file.txt')).toBeNull();
    });
  });

  describe('isValidWebUrl', () => {
    it('accepts valid public http/https URLs', () => {
      expect(isValidWebUrl('https://www.error500.net/p/la-tecnologia-clave-para-la-guerra')).toBe(true);
      expect(isValidWebUrl('http://example.com/docs')).toBe(true);
    });

    it('rejects invalid URLs', () => {
      expect(isValidWebUrl('')).toBe(false);
      expect(isValidWebUrl('google.com')).toBe(false);
      expect(isValidWebUrl('javascript:alert(1)')).toBe(false);
    });
  });

  describe('isExplainerProviderSupportedForSource', () => {
    it('allows Gemini for every source', () => {
      expect(isExplainerProviderSupportedForSource('pdf', 'gemini')).toBe(true);
      expect(isExplainerProviderSupportedForSource('web', 'gemini')).toBe(true);
      expect(isExplainerProviderSupportedForSource('youtube', 'gemini')).toBe(true);
    });

    it('disables OpenRouter for YouTube only', () => {
      expect(isExplainerProviderSupportedForSource('pdf', 'openrouter')).toBe(true);
      expect(isExplainerProviderSupportedForSource('web', 'openrouter')).toBe(true);
      expect(isExplainerProviderSupportedForSource('youtube', 'openrouter')).toBe(false);
    });
  });

  describe('validateExplainerProviderSelection', () => {
    it('requires Gemini key for any execution', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'gemini',
        hasGeminiKey: false,
        hasOpenRouterKey: false,
      })).toMatch(/Gemini/i);
    });

    it('requires OpenRouter key when OpenRouter (Qwen) explainer is selected', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: false,
      })).toMatch(/OpenRouter/i);
    });

    it('rejects OpenRouter on YouTube even with both keys', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'youtube',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: true,
      })).toMatch(/YouTube/i);
    });

    it('accepts OpenRouter for web when both keys exist', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: true,
      })).toBeNull();
    });
  });
});
