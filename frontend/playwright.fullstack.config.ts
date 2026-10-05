import { defineConfig, devices } from '@playwright/test';

// Opt-in development acceptance: real API, database, compiler and durable worker.
export default defineConfig({
  testDir: './e2e-fullstack',
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:4183', trace: 'retain-on-failure' },
  projects: [{ name: 'fullstack-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    { command: 'node e2e-fullstack/server.mjs', url: 'http://127.0.0.1:8183/health/ready', reuseExistingServer: false, timeout: 60_000 },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4183 --strictPort',
      url: 'http://127.0.0.1:4183', reuseExistingServer: false,
      env: {
        VITE_API_BASE_URL: 'http://127.0.0.1:8183', VITE_OIDC_ISSUER: '', VITE_OIDC_CLIENT_ID: '',
        VITE_OIDC_AUTHORIZATION_ENDPOINT: '', VITE_OIDC_TOKEN_ENDPOINT: '', VITE_OIDC_LOGOUT_ENDPOINT: '',
      },
    },
  ],
});
