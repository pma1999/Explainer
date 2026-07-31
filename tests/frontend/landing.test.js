/**
 * Unit tests for landing.js YouTube helpers.
 */
import { beforeEach, describe, it, expect, vi } from 'vitest';
import {
  extractYouTubeVideoId,
  isValidYouTubeUrl,
  normalizeWebUrl,
  isValidWebUrl,
  isExplainerProviderSupportedForSource,
  isValidDeepSeekModel,
  isValidOpenRouterModel,
  isPresetOpenRouterModel,
  DEEPSEEK_MODEL_V4_FLASH,
  DEEPSEEK_MODEL_V4_PRO,
  OPENROUTER_MODEL_MIMO,
  OPENROUTER_MODEL_MIMO_PRO,
  OPENROUTER_MODEL_DEEPSEEK_V4_FLASH,
  validateExplainerProviderSelection,
  DEFAULT_TARGET_LANGUAGE,
  SUPPORTED_TARGET_LANGUAGES,
  isValidTargetLanguage,
  formatModelPrice,
  formatContextLength,
  formatEndpointMeta,
  buildEndpointSummaryChips,
} from '../../frontend/js/landing.js';

// vi.hoisted ensures mockState is initialized before vi.mock factory runs (hoisting order)
const mockState = vi.hoisted(() => ({
  hasApiKey: true,
  hasOpenRouterKey: false,
  hasMistralKey: false,
  hasDeepSeekKey: false,
  hasTavilyKey: false,
  user: null,
}));

vi.mock('../../frontend/js/state.js', () => ({ state: mockState }));
vi.mock('../../frontend/js/dom.js', () => ({
  $: (id) => document.getElementById(id),
  show: (el) => el && el.classList && el.classList.remove('hidden'),
  hide: (el) => el && el.classList && el.classList.add('hidden'),
  formatBytes: (b) => `${b} B`,
  toast: vi.fn(),
}));
vi.mock('../../frontend/js/api.js', () => ({ api: vi.fn() }));
vi.mock('../../frontend/js/storage.js', () => ({
  invalidateProjectsCache: vi.fn(),
  loadBackupAsync: vi.fn(async () => ({ projects: [] })),
  mergeProjects: vi.fn((a, b) => [...a, ...b]),
  syncProjectsToBackup: vi.fn(async () => ({ ok: true })),
}));
vi.mock('../../frontend/js/auth.js', () => ({
  updateApiKeyUI: vi.fn(),
  showSettings: vi.fn(),
}));

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

    it('disables OpenRouter and DeepSeek direct for YouTube only', () => {
      expect(isExplainerProviderSupportedForSource('pdf', 'openrouter')).toBe(true);
      expect(isExplainerProviderSupportedForSource('web', 'openrouter')).toBe(true);
      expect(isExplainerProviderSupportedForSource('youtube', 'openrouter')).toBe(false);
      expect(isExplainerProviderSupportedForSource('pdf', 'deepseek')).toBe(true);
      expect(isExplainerProviderSupportedForSource('web', 'deepseek')).toBe(true);
      expect(isExplainerProviderSupportedForSource('youtube', 'deepseek')).toBe(false);
    });
  });

  describe('isValidOpenRouterModel', () => {
    it('accepts all supported OpenRouter model choices', () => {
      expect(isValidOpenRouterModel(OPENROUTER_MODEL_MIMO_PRO)).toBe(true);
      expect(isValidOpenRouterModel(OPENROUTER_MODEL_MIMO)).toBe(true);
      expect(isValidOpenRouterModel(OPENROUTER_MODEL_DEEPSEEK_V4_FLASH)).toBe(true);
    });

    it('rejects unsupported OpenRouter model ids', () => {
      expect(isValidOpenRouterModel('qwen/qwen3.6-plus')).toBe(false);
      expect(isValidOpenRouterModel('')).toBe(false);
    });
  });

  describe('isPresetOpenRouterModel', () => {
    it('returns true for all three preset model ids', () => {
      expect(isPresetOpenRouterModel(OPENROUTER_MODEL_MIMO_PRO)).toBe(true);
      expect(isPresetOpenRouterModel(OPENROUTER_MODEL_MIMO)).toBe(true);
      expect(isPresetOpenRouterModel(OPENROUTER_MODEL_DEEPSEEK_V4_FLASH)).toBe(true);
    });

    it('returns false for the custom sentinel value', () => {
      expect(isPresetOpenRouterModel('__custom__')).toBe(false);
    });

    it('returns false for arbitrary strings', () => {
      expect(isPresetOpenRouterModel('qwen/qwen3.6-plus')).toBe(false);
      expect(isPresetOpenRouterModel('')).toBe(false);
    });
  });

  describe('isValidDeepSeekModel', () => {
    it('accepts supported DeepSeek direct model choices', () => {
      expect(isValidDeepSeekModel(DEEPSEEK_MODEL_V4_PRO)).toBe(true);
      expect(isValidDeepSeekModel(DEEPSEEK_MODEL_V4_FLASH)).toBe(true);
    });

    it('rejects unsupported DeepSeek direct model ids', () => {
      expect(isValidDeepSeekModel('deepseek-chat')).toBe(false);
      expect(isValidDeepSeekModel('')).toBe(false);
    });
  });

  describe('validateExplainerProviderSelection', () => {
    it('requires Gemini key for Gemini execution', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'gemini',
        hasGeminiKey: false,
        hasOpenRouterKey: false,
      })).toMatch(/Gemini/i);
    });

    it('requires OpenRouter key when OpenRouter explainer is selected', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: false,
      })).toMatch(/OpenRouter/i);
    });

    it('requires Gemini key for OpenRouter compatibility', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'openrouter',
        hasGeminiKey: false,
        hasOpenRouterKey: true,
      })).toMatch(/Gemini/i);
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

    it('requires Mistral when OpenRouter is selected for PDFs', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: true,
        hasMistralKey: false,
      })).toMatch(/Mistral/i);
    });

    it('does not require Mistral when OpenRouter is selected for web URLs', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'openrouter',
        hasGeminiKey: true,
        hasOpenRouterKey: true,
        hasMistralKey: false,
      })).toBeNull();
    });

    it('accepts DeepSeek direct for web without Gemini when DeepSeek and Tavily keys exist', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'deepseek',
        hasGeminiKey: false,
        hasDeepSeekKey: true,
        hasTavilyKey: true,
        hasMistralKey: false,
      })).toBeNull();
    });

    it('requires DeepSeek key when DeepSeek direct is selected', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'deepseek',
        hasGeminiKey: false,
        hasDeepSeekKey: false,
        hasTavilyKey: true,
      })).toMatch(/DeepSeek/i);
    });

    it('requires Tavily key when DeepSeek direct is selected', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'web',
        provider: 'deepseek',
        hasGeminiKey: false,
        hasDeepSeekKey: true,
        hasTavilyKey: false,
      })).toMatch(/Tavily/i);
    });

    it('requires Mistral when DeepSeek direct is selected for PDFs', () => {
      expect(validateExplainerProviderSelection({
        sourceType: 'pdf',
        provider: 'deepseek',
        hasGeminiKey: false,
        hasDeepSeekKey: true,
        hasTavilyKey: true,
        hasMistralKey: false,
      })).toMatch(/Mistral/i);
    });
  });

  describe('target language selection', () => {
    it('defaults to Spain Spanish and validates supported languages', () => {
      expect(DEFAULT_TARGET_LANGUAGE).toBe('es-ES');
      expect(SUPPORTED_TARGET_LANGUAGES).toContain('es-ES');
      expect(isValidTargetLanguage('es-ES')).toBe(true);
      expect(isValidTargetLanguage('en')).toBe(true);
      expect(isValidTargetLanguage('xx')).toBe(false);
    });
  });

  describe('formatModelPrice', () => {
    it('returns Gratis when price is exactly 0', () => {
      expect(formatModelPrice(0)).toBe('Gratis');
    });

    it('formats a small per-token price as $/1M with 2 significant figures', () => {
      // 0.0000005 per token = 0.5 per million
      expect(formatModelPrice(0.0000005)).toBe('$0.5/1M');
    });

    it('formats a typical per-token price (e.g. 0.000001) correctly', () => {
      // 0.000001 per token = 1.0 per million → 2 sig figs = "1" after parseFloat
      expect(formatModelPrice(0.000001)).toBe('$1/1M');
    });

    it('formats a larger per-token price (e.g. 0.0000015) correctly', () => {
      // 0.0000015 per token = 1.5 per million
      expect(formatModelPrice(0.0000015)).toBe('$1.5/1M');
    });

    it('formats a price that rounds to a round number', () => {
      // 0.000002 per token = 2.0 per million → "2" after parseFloat
      expect(formatModelPrice(0.000002)).toBe('$2/1M');
    });

    it('never returns $0.00 for a non-zero price — multiplies by 1e6', () => {
      const result = formatModelPrice(0.0000001);
      expect(result).not.toBe('$0/1M');
      expect(result).toMatch(/^\$[\d.]+\/1M$/);
    });
  });

  describe('formatContextLength', () => {
    it('returns 128K ctx for 128000', () => {
      expect(formatContextLength(128000)).toBe('128K ctx');
    });

    it('returns empty string for 0', () => {
      expect(formatContextLength(0)).toBe('');
    });

    it('returns empty string for undefined', () => {
      expect(formatContextLength(undefined)).toBe('');
    });

    it('returns empty string for null', () => {
      expect(formatContextLength(null)).toBe('');
    });

    it('rounds to nearest 1K', () => {
      expect(formatContextLength(32768)).toBe('33K ctx');
      expect(formatContextLength(8192)).toBe('8K ctx');
    });

    it('handles 1M token context', () => {
      expect(formatContextLength(1000000)).toBe('1000K ctx');
    });
  });

  describe('formatEndpointMeta', () => {
    it('renders context only when no other endpoint values are present', () => {
      expect(formatEndpointMeta({ context_length: 128000 })).toBe('128K ctx');
    });

    it('renders context plus max completion and max prompt tokens', () => {
      const meta = formatEndpointMeta({
        context_length: 128000,
        max_completion_tokens: 16384,
        max_prompt_tokens: 120000,
      });
      expect(meta).toBe('128K ctx · 16K max out · 120K max in');
    });

    it('renders input/output endpoint pricing', () => {
      const meta = formatEndpointMeta({
        prompt_price: 0.0000005,
        completion_price: 0.0000015,
      });
      expect(meta).toBe('$0.5/1M in · $1.5/1M out');
    });

    it('joins every present segment with the separator', () => {
      const meta = formatEndpointMeta({
        context_length: 128000,
        max_completion_tokens: 16384,
        max_prompt_tokens: 120000,
        prompt_price: 0.0000005,
        completion_price: 0.0000015,
      });
      expect(meta).toBe('128K ctx · 16K max out · 120K max in · $0.5/1M in · $1.5/1M out');
    });

    it('omits pricing when the endpoint lacks both a positive prompt and completion price', () => {
      // 0 prices mean "absent" on the backend (defaults to 0.0); never label as exact.
      expect(formatEndpointMeta({ context_length: 128000, prompt_price: 0, completion_price: 0 }))
        .toBe('128K ctx');
    });

    it('returns empty string for a falsy endpoint', () => {
      expect(formatEndpointMeta(null)).toBe('');
      expect(formatEndpointMeta(undefined)).toBe('');
    });

    it('ignores non-positive or non-finite max-token values', () => {
      expect(formatEndpointMeta({ context_length: 128000, max_completion_tokens: 0, max_prompt_tokens: -10 }))
        .toBe('128K ctx');
    });
  });

  describe('buildEndpointSummaryChips', () => {
    it('includes provider_name, tag, context, max tokens and prices for a full endpoint row', () => {
      expect(buildEndpointSummaryChips({
        tag: 'novita/fp8',
        provider_name: 'Novita',
        context_length: 128000,
        max_completion_tokens: 16384,
        max_prompt_tokens: 120000,
        prompt_price: 0.0000005,
        completion_price: 0.0000015,
      })).toEqual([
        'Novita',
        'novita/fp8',
        '128K ctx',
        '16K max out',
        '120K max in',
        '$0.5/1M in · $1.5/1M out',
      ]);
    });

    it('absent endpoint values produce no misleading exact chip — only identity chips', () => {
      // No context, no max tokens, no prices → only provider_name + tag remain.
      expect(buildEndpointSummaryChips({ tag: 'novita/fp8', provider_name: 'Novita' }))
        .toEqual(['Novita', 'novita/fp8']);
    });

    it('omits the pricing chip when both prompt and completion prices are zero/absent', () => {
      expect(buildEndpointSummaryChips({
        tag: 'novita/fp8',
        provider_name: 'Novita',
        context_length: 128000,
        prompt_price: 0,
        completion_price: 0,
      })).toEqual(['Novita', 'novita/fp8', '128K ctx']);
    });

    it('falls back to tag when provider_name is missing', () => {
      const chips = buildEndpointSummaryChips({ tag: 'novita/fp8', context_length: 128000 });
      // provider_name falls back to tag, then the explicit tag chip is also added
      expect(chips).toContain('novita/fp8');
      expect(chips).toContain('128K ctx');
      expect(chips.some((c) => /\$|in ·|out/.test(c))).toBe(false);
    });

    it('returns an empty array for a falsy endpoint', () => {
      expect(buildEndpointSummaryChips(null)).toEqual([]);
      expect(buildEndpointSummaryChips(undefined)).toEqual([]);
    });
  });

});

// ---------------------------------------------------------------------------
// persistModelSelector / restoreModelSelector — pure validation unit tests
// Each test uses a fresh module instance via vi.resetModules() + dynamic import
// so module-level vars start at their initialized defaults.
// ---------------------------------------------------------------------------
describe('persistModelSelector / restoreModelSelector', () => {
  const SELECTOR_KEY = 'explainer.modelSelector.v1';

  let persistModelSelector;
  let restoreModelSelector;

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    mockState.hasApiKey = true;
    mockState.hasOpenRouterKey = false;
    mockState.hasDeepSeekKey = false;

    const mod = await import('../../frontend/js/landing.js');
    persistModelSelector = mod.persistModelSelector;
    restoreModelSelector = mod.restoreModelSelector;
  });

  it('corrupt JSON in localStorage does not throw and leaves defaults', () => {
    localStorage.setItem(SELECTOR_KEY, '{bad json!');
    expect(() => restoreModelSelector()).not.toThrow();
    // Module vars remain at defaults → persist should save gemini defaults
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
    expect(saved.deepseekModel).toBe('deepseek-v4-pro');
  });

  it('missing key in localStorage is a no-op and does not throw', () => {
    // localStorage is empty (cleared in beforeEach)
    expect(() => restoreModelSelector()).not.toThrow();
    // State unchanged: persist writes defaults
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
  });

  it('invalid explainerProvider falls back to gemini', () => {
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'notavalidprovider',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
  });

  it('openrouter provider with missing key falls back to gemini', () => {
    mockState.hasOpenRouterKey = false; // key unavailable
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'openrouter',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
  });

  it('deepseek provider with missing key falls back to gemini', () => {
    mockState.hasDeepSeekKey = false;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'deepseek',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
  });

  it('valid gemini preset round-trip', () => {
    const original = {
      explainerProvider: 'gemini',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    };
    localStorage.setItem(SELECTOR_KEY, JSON.stringify(original));
    const result = restoreModelSelector();
    expect(result).toBeNull(); // no async custom restore needed
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('gemini');
    expect(saved.openrouterMode).toBe('preset');
    expect(saved.openrouterModel).toBe('xiaomi/mimo-v2.5-pro');
    expect(saved.deepseekModel).toBe('deepseek-v4-pro');
  });

  it('valid openrouter preset round-trip when key is available', () => {
    mockState.hasOpenRouterKey = true;
    const original = {
      explainerProvider: 'openrouter',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    };
    localStorage.setItem(SELECTOR_KEY, JSON.stringify(original));
    const result = restoreModelSelector();
    expect(result).toBeNull();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('openrouter');
    expect(saved.openrouterModel).toBe('xiaomi/mimo-v2.5');
  });

  it('valid deepseek round-trip when key is available', () => {
    mockState.hasDeepSeekKey = true;
    const original = {
      explainerProvider: 'deepseek',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-flash',
    };
    localStorage.setItem(SELECTOR_KEY, JSON.stringify(original));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.explainerProvider).toBe('deepseek');
    expect(saved.deepseekModel).toBe('deepseek-v4-flash');
  });

  it('invalid openrouterModel falls back to mimo-pro default', () => {
    mockState.hasOpenRouterKey = true;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'openrouter',
      openrouterMode: 'preset',
      openrouterModel: 'not-a-valid-model',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.openrouterModel).toBe('xiaomi/mimo-v2.5-pro');
  });

  it('invalid deepseekModel falls back to v4-pro default', () => {
    mockState.hasDeepSeekKey = true;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'deepseek',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'invalid-model',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.deepseekModel).toBe('deepseek-v4-pro');
  });

  it('custom mode with valid customOpenrouterModel returns pendingCustomModel', () => {
    mockState.hasOpenRouterKey = true;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'openrouter',
      openrouterMode: 'custom',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: 'qwen/qwen3.6-plus',
      openrouterProvider: 'deepseek',
      openrouterProviderOnly: true,
      deepseekModel: 'deepseek-v4-pro',
    }));
    const result = restoreModelSelector();
    expect(result).not.toBeNull();
    expect(result.pendingCustomModel).toBe('qwen/qwen3.6-plus');
    expect(result.pendingProvider).toBe('deepseek');
  });

  it('custom mode with empty customOpenrouterModel falls back to preset', () => {
    mockState.hasOpenRouterKey = true;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'openrouter',
      openrouterMode: 'custom',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: '', // empty → treat as no custom model
      openrouterProvider: '',
      openrouterProviderOnly: false,
      deepseekModel: 'deepseek-v4-pro',
    }));
    const result = restoreModelSelector();
    expect(result).toBeNull(); // falls back to preset path
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(saved.openrouterMode).toBe('preset');
  });

  it('openrouterProviderOnly is coerced to boolean', () => {
    mockState.hasOpenRouterKey = true;
    localStorage.setItem(SELECTOR_KEY, JSON.stringify({
      explainerProvider: 'openrouter',
      openrouterMode: 'preset',
      openrouterModel: 'xiaomi/mimo-v2.5-pro',
      customOpenrouterModel: null,
      openrouterProvider: '',
      openrouterProviderOnly: 1, // truthy non-boolean
      deepseekModel: 'deepseek-v4-pro',
    }));
    restoreModelSelector();
    persistModelSelector();
    const saved = JSON.parse(localStorage.getItem(SELECTOR_KEY));
    expect(typeof saved.openrouterProviderOnly).toBe('boolean');
    expect(saved.openrouterProviderOnly).toBe(true);
  });
});
