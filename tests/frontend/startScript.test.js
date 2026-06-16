import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

describe('start.bat', () => {
  it('uses CRLF line endings so cmd.exe parses every command correctly', () => {
    const script = fs.readFileSync(path.join(repoRoot, 'start.bat'));
    const lfWithoutCr = script.filter((byte, index) => byte === 0x0a && script[index - 1] !== 0x0d);

    expect(lfWithoutCr).toHaveLength(0);
  });

  it('generates frontend Supabase config before starting Uvicorn', () => {
    const script = fs.readFileSync(path.join(repoRoot, 'start.bat'), 'utf8');

    const generateConfigIndex = script.search(/node\s+scripts[\\/]generate-config\.cjs/i);
    const uvicornIndex = script.indexOf('python -m uvicorn');

    expect(generateConfigIndex).toBeGreaterThanOrEqual(0);
    expect(uvicornIndex).toBeGreaterThanOrEqual(0);
    expect(generateConfigIndex).toBeLessThan(uvicornIndex);
  });
});
