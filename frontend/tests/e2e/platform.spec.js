// @ts-check
import { test, expect } from '@playwright/test'

const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8380'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5473'

async function loginAsAdmin(page) {
  await page.goto('/')
  // Click login button
  const loginBtn = page.locator('button').filter({ hasText: /login|log in/i }).first()
  await loginBtn.waitFor({ timeout: 15000 })
  await loginBtn.click()
  // Keycloak login
  await page.waitForURL(new RegExp(KEYCLOAK_URL), { timeout: 15000 })
  await page.fill('#username', 'admin')
  await page.fill('#password', 'Admin123!')
  await page.click('#kc-login')
  await page.waitForURL(new RegExp(BASE_URL), { timeout: 15000 })
}

test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
})

test.describe('Platform Dashboard', () => {
  test('page loads and shows containers', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/admin/platform')

    // Page title
    await expect(page.getByRole('heading', { name: 'Platform' })).toBeVisible({ timeout: 10000 })

    // Stats row should show container counts
    await expect(page.getByText('Containers')).toBeVisible()
    await expect(page.getByText('Running')).toBeVisible()

    // Should show at least one container row with state/health chips
    await expect(page.getByText(/running|exited|created/i).first()).toBeVisible({ timeout: 10000 })
  })

  test('search filters containers', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/admin/platform')
    await expect(page.getByRole('heading', { name: 'Platform' })).toBeVisible({ timeout: 10000 })

    // Wait for data to load
    await expect(page.getByText('e2e-platform-app-1')).toBeVisible({ timeout: 10000 })

    // Type a search term that won't match
    const searchInput = page.getByPlaceholder(/search/i)
    await searchInput.fill('nonexistent-container-xyz')
    // Should show no results
    await expect(page.getByText('No deployments match')).toBeVisible({ timeout: 5000 })

    // Clear and search for our test container
    await searchInput.clear()
    await searchInput.fill('e2e-platform')
    // Should show the test container
    await expect(page.getByText('e2e-platform-app-1')).toBeVisible({ timeout: 5000 })
  })

  test('restart triggers a toast', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/admin/platform')
    await expect(page.getByRole('heading', { name: 'Platform' })).toBeVisible({ timeout: 10000 })

    // Wait for the test container to appear
    await expect(page.getByText('e2e-platform-app-1')).toBeVisible({ timeout: 10000 })

    // Click the restart button (RotateCw icon) for the container row
    const row = page.locator('tr', { hasText: 'e2e-platform-app-1' })
    await row.getByTitle('Restart').click()

    // Should show a success toast
    await expect(page.getByText(/restarted.*e2e-platform-app-1/i)).toBeVisible({ timeout: 10000 })
  })

  test('wipe dialog confirms and updates table', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/admin/platform')
    await expect(page.getByRole('heading', { name: 'Platform' })).toBeVisible({ timeout: 10000 })

    // Wait for data
    await expect(page.getByText('e2e-platform-app-1')).toBeVisible({ timeout: 10000 })

    // Click the Wipe button on the project group
    await page.getByRole('button', { name: 'Wipe' }).first().click()

    // Confirmation dialog should appear
    await expect(page.getByText(/cannot be undone/i)).toBeVisible({ timeout: 5000 })

    // Click confirm
    await page.getByRole('button', { name: 'Wipe' }).last().click()

    // Container should disappear from the table within 5s polling cycle
    await expect(page.getByText('e2e-platform-app-1')).not.toBeVisible({ timeout: 10000 })
  })
})
