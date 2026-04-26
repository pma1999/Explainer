#!/usr/bin/env node
/** Generates frontend/config.js from env (for Vercel build). */
const fs = require('fs');
const path = require('path');

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const env = {};
  const content = fs.readFileSync(filePath, 'utf8');
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim();
    env[key] = value;
  }
  return env;
}

const envFile = loadEnvFile(path.join(__dirname, '..', '.env'));
const env = { ...envFile, ...process.env };

const url = env.EXPLAINER_SUPABASE_URL || env.SUPABASE_URL || '';
const key = env.EXPLAINER_SUPABASE_ANON_KEY || env.SUPABASE_ANON_KEY || '';

const outDir = path.join(__dirname, '..', 'frontend');
const outFile = path.join(outDir, 'config.js');
const content = `// Generated at build time from EXPLAINER_SUPABASE_* env vars. Do not commit secrets.
window.EXPLAINER_SUPABASE_URL = ${JSON.stringify(url)};
window.EXPLAINER_SUPABASE_ANON_KEY = ${JSON.stringify(key)};
`;

if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(outFile, content, 'utf8');
console.log('Generated frontend/config.js');
