#!/usr/bin/env node

import { chromium } from 'playwright';

const url = process.argv[2];

if (!url) {
  console.error('Missing URL argument');
  process.exit(1);
}

const NAVIGATION_TIMEOUT_MS = 45_000;
const NETWORK_IDLE_TIMEOUT_MS = 15_000;

async function main() {
  const browser = await chromium.launch({
    headless: true,
  });

  const context = await browser.newContext({
    locale: 'es-ES',
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
  });

  const page = await context.newPage();
  await page.route('**/*', (route) => {
    const resourceType = route.request().resourceType();
    if (['image', 'media', 'font'].includes(resourceType)) {
      return route.abort();
    }
    return route.continue();
  });

  try {
    const response = await page.goto(url, {
      waitUntil: 'domcontentloaded',
      timeout: NAVIGATION_TIMEOUT_MS,
    });

    await page.waitForLoadState('networkidle', {
      timeout: NETWORK_IDLE_TIMEOUT_MS,
    }).catch(() => {});

    const contentType = response?.headers()?.['content-type'] ?? 'text/html';
    const payload = {
      requestedUrl: url,
      resolvedUrl: page.url(),
      statusCode: response?.status() ?? 200,
      contentType,
      title: await page.title(),
      html: await page.content(),
    };

    process.stdout.write(JSON.stringify(payload));
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((error) => {
  console.error(String(error));
  process.exit(1);
});
