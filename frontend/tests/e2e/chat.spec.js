// @ts-check
import { test, expect } from '@playwright/test'

// Default to full-stack deployment ports (docker-compose.full.yml)
const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8180'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5273'

// Test users with compliant passwords (from iac/users.yaml)
const users = {
  admin: { username: 'admin', password: 'Admin123!' },
  developer: { username: 'seniordev', password: 'Developer123!' },
  infra: { username: 'infra', password: 'Infra123!' },
  productOwner: { username: 'productowner', password: 'Product123!' },
  juniorDev: { username: 'juniordev', password: 'Junior123!' },
}

/**
 * Helper to find and click a login button (handles multiple button variants)
 */
async function clickLoginButton(page) {
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})

  const loginButton = page.locator('button:has-text("Login"), button:has-text("Log In")').first()
  await loginButton.click()
}

/**
 * Helper to login a user through Keycloak
 */
async function login(page, username, password) {
  await page.goto('/')
  await clickLoginButton(page)
  await page.waitForURL(new RegExp(KEYCLOAK_URL), { timeout: 15000 })
  await page.fill('#username', username)
  await page.fill('#password', password)
  await page.click('#kc-login')
  await page.waitForURL(new RegExp(BASE_URL), { timeout: 15000 })
}

/**
 * Get the chat input field
 */
function getChatInput(page) {
  // Match the actual placeholder text
  return page.getByPlaceholder(/describe what you want to build/i)
}

// Clear storage between tests for isolation
test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
})

test.describe('Chat and Plan Creation', () => {
  test('can send a chat message', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()

    // Should see welcome message from Druppie
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Type a message
    const input = getChatInput(page)
    await input.fill('Hello, can you help me create a calculator?')
    await input.press('Enter')

    // Should see user message
    await expect(page.getByText('Hello, can you help me create a calculator?')).toBeVisible()

    // Wait for response (may take a moment with LLM)
    // Use first() to avoid strict mode violation when multiple processing indicators exist
    await expect(
      page.locator('.animate-pulse').first().or(page.getByText(/router|agent|tool/i).first())
    ).toBeVisible({ timeout: 60000 })
  })

  test('shows suggestion buttons on empty chat', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    await page.getByRole('link', { name: /chat/i }).click()

    // Wait for page to load
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Should see suggestion buttons (partial match)
    const suggestions = page.locator('button').filter({ hasText: /calculator|todo|weather|shopping/i })
    await expect(suggestions.first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Deployment Approval Workflow', () => {
  test('infra-engineer can see and approve deployment tasks', async ({ page }) => {
    await login(page, users.infra.username, users.infra.password)

    // Navigate to approvals using exact name to avoid strict mode issues
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Wait for page to load
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})

    // Should see the approvals page header (h1 specifically)
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

    // Check if there are any approve buttons
    const approveButton = page.getByRole('button', { name: /approve/i }).first()
    if (await approveButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      // Has pending approvals to approve
      await approveButton.click()
      await expect(page.getByText(/approved|success/i)).toBeVisible({ timeout: 5000 })
    } else {
      // No pending approvals - that's okay
      await expect(page.getByText(/no pending approvals|all caught up/i)).toBeVisible()
    }
  })

  test('developer can view approvals page', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see the page loads
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
  })
})

test.describe('Multi-user Approval Flow', () => {
  test('multiple users can access approvals page', async ({ browser }) => {
    // Create two browser contexts for different users
    const developerContext = await browser.newContext()
    const infraContext = await browser.newContext()

    const developerPage = await developerContext.newPage()
    const infraPage = await infraContext.newPage()

    try {
      // Developer logs in and checks approvals
      await login(developerPage, users.developer.username, users.developer.password)
      await developerPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(developerPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

      // Infra engineer logs in and checks approvals
      await login(infraPage, users.infra.username, users.infra.password)
      await infraPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(infraPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
    } finally {
      await developerContext.close()
      await infraContext.close()
    }
  })
})

test.describe('App Creation E2E', () => {
  test('junior dev can access chat and send a message', async ({ page }) => {
    await login(page, users.juniorDev.username, users.juniorDev.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()

    // Should see welcome message
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request to create a todo app
    const input = getChatInput(page)
    await input.fill('Create a todo app')
    await input.press('Enter')

    // Should see user message in chat (use first to avoid strict mode)
    await expect(page.getByText('Create a todo app').first()).toBeVisible()

    // Wait for any response (loading indicator or actual response)
    // Use first() to handle multiple processing indicators
    await expect(
      page.locator('.animate-pulse').first().or(page.getByText(/working|processing|router/i).first())
    ).toBeVisible({ timeout: 30000 })
  })

  test('developer can send chat message', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    await page.getByRole('link', { name: /chat/i }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    const input = getChatInput(page)
    await input.fill('Build me a calculator')
    await input.press('Enter')

    // Use first() to avoid strict mode violation
    await expect(page.getByText('Build me a calculator').first()).toBeVisible()

    // Wait for processing to start
    await expect(
      page.locator('.animate-pulse').first().or(page.getByText(/working|processing|router/i).first())
    ).toBeVisible({ timeout: 30000 })
  })
})
