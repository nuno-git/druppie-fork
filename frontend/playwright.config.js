// @ts-check
import { defineConfig, devices } from '@playwright/test'

// Default to full-stack deployment ports (docker-compose.full.yml)
const BASE_URL = process.env.BASE_URL || 'http://localhost:5273'
const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8180'

/**
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  timeout: 60000,

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // When using full-stack docker-compose, don't start a dev server
  // Tests will connect to running containers
  webServer: process.env.USE_DEV_SERVER
    ? {
        command: 'npm run dev',
        url: 'http://localhost:5173',
        reuseExistingServer: true,
        timeout: 120000,
      }
    : undefined,
})
