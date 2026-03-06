/** @type {import('vitest').UserConfig} */
export default {
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/frontend/setup.js'],
    include: ['tests/frontend/**/*.test.js'],
    globals: true,
  },
  resolve: {
    alias: {
      // Resolve frontend modules from project root
    },
  },
};
