#!/usr/bin/env node
/** Generates frontend/config.js from env (for Vercel build). */
const fs = require('fs');
const path = require('path');

const url = process.env.EXPLAINER_SUPABASE_URL || '';
const key = process.env.EXPLAINER_SUPABASE_ANON_KEY || '';

const outDir = path.join(__dirname, '..', 'frontend');
const outFile = path.join(outDir, 'config.js');
const content = `// Generated at build time from EXPLAINER_SUPABASE_* env vars. Do not commit secrets.
window.EXPLAINER_SUPABASE_URL = ${JSON.stringify(url)};
window.EXPLAINER_SUPABASE_ANON_KEY = ${JSON.stringify(key)};
`;

if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(outFile, content, 'utf8');
console.log('Generated frontend/config.js');
