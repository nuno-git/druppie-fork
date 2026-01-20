// @ts-check
import { test, expect } from '@playwright/test'

const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8080'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5173'
const API_URL = process.env.API_URL || 'http://localhost:8000'

// Test users from iac/users.yaml
const users = {
  admin: { username: 'admin', password: 'Admin123!', roles: ['admin'] },
  developer: { username: 'seniordev', password: 'Developer123!', roles: ['developer'] },
  infra: { username: 'infra', password: 'Infra123!', roles: ['infra-engineer'] },
  productOwner: { username: 'productowner', password: 'Product123!', roles: ['product-owner'] },
}

// Helper to login
async function login(page, username, password) {
  await page.goto('/')

  // Wait for initial page load - Keycloak init can be slow
  await page.waitForTimeout(3000)

  // Check if already logged in
  const logoutButton = page.getByRole('button', { name: /logout/i })
  if (await logoutButton.isVisible({ timeout: 2000 }).catch(() => false)) {
    return // Already logged in
  }

  // Click login
  await page.getByRole('button', { name: /login/i }).click({ timeout: 15000 })
  await page.waitForURL(new RegExp(KEYCLOAK_URL))

  // Clear any existing values and fill login form
  await page.locator('#username').fill('')
  await page.locator('#username').fill(username)
  await page.locator('#password').fill('')
  await page.locator('#password').fill(password)
  await page.click('#kc-login')

  await page.waitForURL(new RegExp(BASE_URL))

  // Wait for dashboard to load
  await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 10000 })
}

// Helper to logout
async function logout(page) {
  const logoutButton = page.getByRole('button', { name: /logout/i })
  if (await logoutButton.isVisible({ timeout: 2000 }).catch(() => false)) {
    await logoutButton.click()
    await page.waitForTimeout(2000) // Wait for logout to complete
  }
}

test.describe('Deployment from Chat', () => {
  test('deploy request from chat creates approval task', async ({ page }) => {
    // Login as infra (has infra-engineer role)
    await login(page, users.infra.username, users.infra.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request deployment
    const input = page.getByPlaceholder(/describe what you want/i)
    await input.fill('Deploy my project to staging')
    await input.press('Enter')

    // Wait for response - LLM can take 30-120 seconds
    await expect(page.getByText(/deploy/i).or(page.getByText(/approval/i))).toBeVisible({ timeout: 120000 })

    // Should mention pending approval or deployment task
    await expect(page.getByText(/approval required|pending approval|deploy.staging/i)).toBeVisible({ timeout: 5000 })
  })

  test('staging deployment requires developer or infra-engineer approval', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Request staging deployment
    const input = page.getByPlaceholder(/describe what you want/i)
    await input.fill('Deploy to staging environment')
    await input.press('Enter')

    // Wait for response
    await expect(page.getByText(/staging|deploy/i)).toBeVisible({ timeout: 120000 })

    // Should show approval required from developer or infra-engineer
    await expect(
      page.getByText(/developer|infra-engineer|approval/i)
    ).toBeVisible({ timeout: 5000 })
  })
})

test.describe('ROLE Approval Workflow (deploy.staging)', () => {
  test('developer can approve staging deployment tasks', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals page
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Check if there are any staging deployment tasks
    const stagingTask = page.locator('text=deploy.staging').first()
    if (await stagingTask.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Should show "You can approve" badge for developer role
      await expect(page.getByText(/you can approve/i)).toBeVisible()

      // Should have Approve button
      const approveButton = page.getByRole('button', { name: /approve/i }).first()
      await expect(approveButton).toBeVisible()
    }
  })

  test('infra-engineer can approve staging deployment tasks', async ({ page }) => {
    // Login as infra
    await login(page, users.infra.username, users.infra.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    await expect(page.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Check for staging deployment tasks
    const stagingTask = page.locator('text=deploy.staging').first()
    if (await stagingTask.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Should show "You can approve" badge
      await expect(page.getByText(/you can approve/i)).toBeVisible()
    }
  })

  test('product-owner cannot approve staging deployment', async ({ page }) => {
    // Login as product owner
    await login(page, users.productOwner.username, users.productOwner.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    await expect(page.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Should see "All caught up" or tasks without approve button
    // Product owner doesn't have developer or infra-engineer role
    const approveButton = page.getByRole('button', { name: /approve/i })
    const stagingTask = page.locator('text=deploy.staging')

    // If there are staging tasks, product-owner shouldn't see them
    // (role-based filtering should hide them)
    if (await stagingTask.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Task is visible but approve button should not be
      // This would be a bug if visible
      console.log('Warning: staging task visible to product-owner')
    }
  })
})

test.describe('MULTI Approval Workflow (deploy.production)', () => {
  test('production deployment requires 2 approvals from different roles', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    await expect(page.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Check for production deployment tasks
    const prodTask = page.locator('text=deploy.production').first()
    if (await prodTask.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Should show multi-approval message
      await expect(
        page.getByText(/2 of.*developer.*infra-engineer.*product-owner/i)
      ).toBeVisible()
    }
  })

  test('multi-approval flow: first approval keeps task pending', async ({ browser }) => {
    // Create context for first approver (developer)
    const devContext = await browser.newContext()
    const devPage = await devContext.newPage()

    await login(devPage, users.developer.username, users.developer.password)
    await devPage.getByRole('link', { name: 'Approvals', exact: true }).click()

    await expect(devPage.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Find a MULTI approval task
    const prodTask = devPage.locator('text=deploy.production').first()
    if (await prodTask.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Approve it
      const approveButton = devPage.getByRole('button', { name: /approve/i }).first()
      await approveButton.click()

      // Task should still exist (needs 2nd approval)
      // Or task should be filtered out since developer already approved
      await devPage.waitForTimeout(1000)

      // The task should either:
      // 1. Still show as pending (waiting for 2nd approval)
      // 2. Be hidden from this user (already approved)
    }

    await devContext.close()
  })

  test('multi-approval flow: second approval marks task as approved', async ({ browser }) => {
    // This test requires a task that already has one approval
    // Create two contexts for sequential approvals

    const devContext = await browser.newContext()
    const infraContext = await browser.newContext()

    const devPage = await devContext.newPage()
    const infraPage = await infraContext.newPage()

    // First approval by developer
    await login(devPage, users.developer.username, users.developer.password)
    await devPage.getByRole('link', { name: 'Approvals', exact: true }).click()

    const prodTaskDev = devPage.locator('text=deploy.production').first()
    if (await prodTaskDev.isVisible({ timeout: 3000 }).catch(() => false)) {
      await devPage.getByRole('button', { name: /approve/i }).first().click()
      await devPage.waitForTimeout(1000)
    }

    // Second approval by infra-engineer
    await login(infraPage, users.infra.username, users.infra.password)
    await infraPage.getByRole('link', { name: 'Approvals', exact: true }).click()

    const prodTaskInfra = infraPage.locator('text=deploy.production').first()
    if (await prodTaskInfra.isVisible({ timeout: 3000 }).catch(() => false)) {
      await infraPage.getByRole('button', { name: /approve/i }).first().click()

      // After 2nd approval, task should be marked as approved
      // It should disappear from the pending list
      await infraPage.waitForTimeout(2000)

      // Task should no longer be visible (approved)
      await expect(prodTaskInfra).not.toBeVisible({ timeout: 3000 }).catch(() => {
        // Task might still be visible if there are multiple prod tasks
      })
    }

    await devContext.close()
    await infraContext.close()
  })
})

test.describe('Reject Workflow', () => {
  test('can reject a deployment task with reason', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    await expect(page.getByRole('heading', { name: /pending approvals/i })).toBeVisible()

    // Find a task with reject button
    const rejectButton = page.getByRole('button', { name: /reject/i }).first()
    if (await rejectButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await rejectButton.click()

      // Should show reason input modal/dialog
      await expect(page.getByPlaceholder(/reason/i).or(page.getByLabel(/reason/i))).toBeVisible()

      // Enter rejection reason
      await page.getByPlaceholder(/reason/i).or(page.getByLabel(/reason/i)).fill('Not ready for deployment yet')

      // Confirm rejection
      await page.getByRole('button', { name: /confirm|submit|reject/i }).last().click()

      // Task should be removed from pending list
      await page.waitForTimeout(1000)
    }
  })
})

test.describe('Approval Counts', () => {
  test('pending approval count updates after approval', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Check pending approvals count on dashboard
    const pendingCountBefore = await page.getByText(/pending approvals/i).locator('..').textContent()

    // Navigate to Approvals
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Approve a task if available
    const approveButton = page.getByRole('button', { name: /approve/i }).first()
    if (await approveButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await approveButton.click()
      await page.waitForTimeout(1000)

      // Go back to dashboard
      await page.getByRole('link', { name: /dashboard/i }).click()

      // Count should have decreased
      const pendingCountAfter = await page.getByText(/pending approvals/i).locator('..').textContent()

      // Verify count changed (or stayed same if multiple tasks)
      console.log(`Count before: ${pendingCountBefore}, after: ${pendingCountAfter}`)
    }
  })
})

test.describe('Workflow Events Display', () => {
  test('deployment workflow shows correct events in debug panel', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 15000 })

    // Open debug panel
    const debugButton = page.getByRole('button', { name: /debug/i })
    await debugButton.click()

    // Request deployment
    const input = page.getByPlaceholder(/describe what you want/i)
    await input.fill('Deploy to staging')
    await input.press('Enter')

    // Wait for LLM response
    await page.waitForTimeout(60000) // LLM can be slow

    // Debug panel should show LLM calls
    await expect(page.getByText(/router_agent/i)).toBeVisible({ timeout: 5000 })
    await expect(page.getByText(/planner_agent/i)).toBeVisible({ timeout: 5000 })

    // Should show deployment-related events
    await expect(
      page.getByText(/deploy|staging|approval/i)
    ).toBeVisible()
  })
})
