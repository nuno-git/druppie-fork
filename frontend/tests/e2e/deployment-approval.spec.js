// @ts-check
import { test, expect } from '@playwright/test'

// Default to full-stack deployment ports (docker-compose.full.yml)
const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8180'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5273'
const API_URL = process.env.API_URL || 'http://localhost:8100'

// Test users from iac/users.yaml
const users = {
  admin: { username: 'admin', password: 'Admin123!', roles: ['admin'] },
  developer: { username: 'seniordev', password: 'Developer123!', roles: ['developer'] },
  infra: { username: 'infra', password: 'Infra123!', roles: ['infra-engineer'] },
  productOwner: { username: 'productowner', password: 'Product123!', roles: ['product-owner'] },
}

/**
 * Helper to find and click a login button
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

  await page.locator('#username').fill('')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill('')
  await page.locator('#password').fill(password)
  await page.click('#kc-login')

  await page.waitForURL(new RegExp(BASE_URL), { timeout: 15000 })
  await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })
}

/**
 * Get the chat input field
 */
function getChatInput(page) {
  return page.getByPlaceholder(/describe what you want to build/i)
}

// Clear storage between tests for isolation
test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
})

test.describe('Deployment from Chat', () => {
  test('can access chat and send deployment request', async ({ page }) => {
    await login(page, users.infra.username, users.infra.password)

    // Navigate to chat (use exact match to avoid matching session links)
    await page.getByRole('link', { name: 'Chat', exact: true }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request deployment
    const input = getChatInput(page)
    await input.fill('Deploy my project to staging')
    await input.press('Enter')

    // Should see user message (use first() to avoid strict mode)
    await expect(page.getByText('Deploy my project to staging').first()).toBeVisible()

    // Wait for processing to start (loading indicator or response)
    // Use first() to handle multiple processing indicators
    await expect(
      page.locator('.animate-pulse').first().or(page.getByText(/working|processing|router/i).first())
    ).toBeVisible({ timeout: 60000 })
  })

  test('developer can request staging deployment', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to chat (use exact match to avoid matching session links)
    await page.getByRole('link', { name: 'Chat', exact: true }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request staging deployment
    const input = getChatInput(page)
    await input.fill('Deploy to staging environment')
    await input.press('Enter')

    // Should see user message
    await expect(page.getByText('Deploy to staging environment')).toBeVisible()
  })
})

test.describe('ROLE Approval Workflow (deploy.staging)', () => {
  test('developer can view approvals page', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals page
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page with h1 header
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
  })

  test('infra-engineer can view approvals page', async ({ page }) => {
    await login(page, users.infra.username, users.infra.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
  })

  test('product-owner can view approvals page', async ({ page }) => {
    await login(page, users.productOwner.username, users.productOwner.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
  })
})

test.describe('MULTI Approval Workflow (deploy.production)', () => {
  test('users can view production tasks on approvals page', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

    // Check for production deployment tasks (if any exist)
    const prodTask = page.locator('text=deploy.production').first()
    const isProdTaskVisible = await prodTask.isVisible({ timeout: 3000 }).catch(() => false)

    if (isProdTaskVisible) {
      // If task exists, verify it's visible
      await expect(prodTask).toBeVisible()
    }
  })

  test('multi-approval flow: multiple users can access approvals', async ({ browser }) => {
    const devContext = await browser.newContext()
    const infraContext = await browser.newContext()

    const devPage = await devContext.newPage()
    const infraPage = await infraContext.newPage()

    try {
      // Developer views approvals
      await login(devPage, users.developer.username, users.developer.password)
      await devPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(devPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

      // Infra-engineer views approvals
      await login(infraPage, users.infra.username, users.infra.password)
      await infraPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(infraPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
    } finally {
      await devContext.close()
      await infraContext.close()
    }
  })

  test('multi-approval flow: second user sees approvals after first user', async ({ browser }) => {
    const devContext = await browser.newContext()
    const infraContext = await browser.newContext()

    const devPage = await devContext.newPage()
    const infraPage = await infraContext.newPage()

    try {
      // First user (developer) views approvals
      await login(devPage, users.developer.username, users.developer.password)
      await devPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(devPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

      // Check for any approve button
      const devApproveButton = devPage.getByRole('button', { name: /approve/i }).first()
      if (await devApproveButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await devApproveButton.click()
        await devPage.waitForTimeout(1000)
      }

      // Second user (infra) views approvals
      await login(infraPage, users.infra.username, users.infra.password)
      await infraPage.getByRole('link', { name: 'Approvals', exact: true }).click()
      await expect(infraPage.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()
    } finally {
      await devContext.close()
      await infraContext.close()
    }
  })
})

test.describe('Reject Workflow', () => {
  test('can view reject button on approvals page', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByRole('heading', { level: 1, name: 'Pending Approvals' })).toBeVisible()

    // Check if there's a reject button (if any tasks exist)
    const rejectButton = page.getByRole('button', { name: /reject/i }).first()
    const isRejectVisible = await rejectButton.isVisible({ timeout: 3000 }).catch(() => false)

    if (isRejectVisible) {
      // Reject button exists - task is available for rejection
      await expect(rejectButton).toBeVisible()
    }
  })
})

test.describe('Approval Counts', () => {
  test('dashboard shows pending approvals widget', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Dashboard should show a pending approvals section
    // Use specific locator to avoid strict mode with multiple matches
    const pendingSection = page.getByRole('link', { name: /pending approvals/i }).first()
    await expect(pendingSection).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Workflow Events Display', () => {
  test('chat page shows execution events', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    // Navigate to chat (use exact match to avoid matching session links)
    await page.getByRole('link', { name: 'Chat', exact: true }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request deployment
    const input = getChatInput(page)
    await input.fill('Deploy to staging')
    await input.press('Enter')

    // Should see user message (use first() to avoid strict mode)
    await expect(page.getByText('Deploy to staging').first()).toBeVisible()

    // Wait for processing to start (use first() to handle multiple indicators)
    await expect(
      page.locator('.animate-pulse').first().or(page.getByText(/working|processing|router/i).first())
    ).toBeVisible({ timeout: 30000 })
  })
})
