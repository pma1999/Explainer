#!/usr/bin/env node
/**
 * Runs all tests: frontend unit (Vitest), backend (pytest), E2E (Playwright).
 * Exit code 1 if any suite fails.
 */
import { spawn } from 'child_process';

function run(cmd, args) {
  return new Promise((resolve) => {
    const proc = spawn(cmd, args, {
      stdio: 'inherit',
      shell: true,
    });
    proc.on('close', (code) => resolve(code));
  });
}

async function main() {
  console.log('\n=== Explainer Test Suite ===\n');
  console.log('1. Frontend unit tests (Vitest)...\n');

  const unitCode = await run('npm', ['run', 'test']);
  if (unitCode !== 0) {
    console.error('\nFrontend unit tests failed.');
    process.exit(1);
  }

  console.log('\n2. Backend tests (pytest)...\n');
  const backendCode = await run('npm', ['run', 'test:backend']);
  if (backendCode !== 0) {
    console.error('\nBackend tests failed.');
    process.exit(1);
  }

  console.log('\n3. E2E tests (Playwright)...\n');
  const e2eCode = await run('npm', ['run', 'test:e2e']);
  if (e2eCode !== 0) {
    console.error('\nE2E tests failed.');
    process.exit(1);
  }

  console.log('\n=== All tests passed ===\n');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
