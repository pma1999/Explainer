/**
 * Unit tests for landing.js YouTube helpers.
 */
import { describe, it, expect } from 'vitest';
import { extractYouTubeVideoId, isValidYouTubeUrl } from '../../frontend/js/landing.js';

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
});
