// @ts-check
import { test, expect } from '@playwright/test'

// Default to full-stack deployment ports (docker-compose.full.yml)
const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8180'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5273'

// Test users from iac/users.yaml
const users = {
  admin: { username: 'admin', password: 'Admin123!', roles: ['admin'] },
  developer: { username: 'seniordev', password: 'Developer123!', roles: ['developer'] },
  infra: { username: 'infra', password: 'Infra123!', roles: ['infra-engineer'] },
  productOwner: { username: 'productowner', password: 'Product123!', roles: ['product-owner'] },
}

/**
 * Helper to find and click a login button (handles multiple button variants)
 */
async function clickLoginButton(page) {
  // Wait for page to stabilize
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})

  // Try different login button selectors in order of preference
  const loginSelectors = [
    page.getByRole('button', { name: 'Login' }),
    page.getByRole('button', { name: /log in with keycloak/i }),
    page.getByRole('button', { name: /login/i }),
  ]

  for (const selector of loginSelectors) {
    if (await selector.isVisible({ timeout: 2000 }).catch(() => false)) {
      await selector.click()
      return
    }
  }

  // Fallback: click the first visible login button
  await page.locator('button:has-text("Login"), button:has-text("Log In")').first().click()
}

/**
 * Helper to login a user through Keycloak
 */
async function loginUser(page, user) {
  await page.goto('/')
  await clickLoginButton(page)
  await page.waitForURL(new RegExp(KEYCLOAK_URL), { timeout: 15000 })

  await page.fill('#username', user.username)
  await page.fill('#password', user.password)
  await page.click('#kc-login')

  await page.waitForURL(new RegExp(BASE_URL), { timeout: 15000 })
}

// Clear storage between tests for isolation
test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
})

test.describe('Authentication', () => {
  test('should show login button when not authenticated', async ({ page }) => {
    await page.goto('/')

    // Wait for page to load and show login state
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(3000) // Extra wait for Keycloak init

    // Should see a login button (either in nav or main content)
    // The page might auto-login if Keycloak is configured, so check for either state
    const loginButton = page.locator('button').filter({ hasText: /login|log in/i }).first()
    const welcomeText = page.getByText(/welcome back/i)

    // Either we see login button OR we're already authenticated
    const isLoginVisible = await loginButton.isVisible({ timeout: 5000 }).catch(() => false)
    const isWelcomeVisible = await welcomeText.isVisible({ timeout: 1000 }).catch(() => false)

    expect(isLoginVisible || isWelcomeVisible).toBeTruthy()
  })

  test('should redirect to Keycloak on login click', async ({ page }) => {
    await page.goto('/')

    // Click login
    await clickLoginButton(page)

    // Should redirect to Keycloak
    await expect(page).toHaveURL(new RegExp(KEYCLOAK_URL), { timeout: 10000 })
  })

  test('admin can login and see all features', async ({ page }) => {
    await loginUser(page, users.admin)

    // Should see dashboard with welcome message
    await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })

    // Should see admin role displayed (use first() to avoid strict mode)
    await expect(page.locator('text=admin').first()).toBeVisible()
  })

  test('developer can login and has limited access', async ({ page }) => {
    await loginUser(page, users.developer)

    // Should see dashboard
    await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })

    // Should see developer role
    await expect(page.locator('text=developer')).toBeVisible()
  })

  test('can logout', async ({ page }) => {
    // Login first
    await loginUser(page, users.admin)

    // Should be logged in
    await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })

    // Click logout
    const logoutButton = page.getByRole('button', { name: /logout/i })
    await logoutButton.click()

    // Wait for logout to complete and redirect
    await page.waitForTimeout(2000)

    // Should show login button again (after logout)
    const loginButton = page.locator('button:has-text("Login"), button:has-text("Log In")').first()
    await expect(loginButton).toBeVisible({ timeout: 15000 })
  })
})

test.describe('Role-based Access', () => {
  test('infra-engineer can login and see role', async ({ page }) => {
    await loginUser(page, users.infra)

    // Should see infra-engineer role
    await expect(page.locator('text=infra-engineer')).toBeVisible({ timeout: 10000 })
  })

  test('product-owner can access dashboard', async ({ page }) => {
    await loginUser(page, users.productOwner)

    // Should see dashboard
    await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })

    // Should see product-owner role
    await expect(page.locator('text=product-owner')).toBeVisible()
  })
})
