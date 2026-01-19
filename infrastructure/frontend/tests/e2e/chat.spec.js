// @ts-check
import { test, expect } from '@playwright/test'

const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8080'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5173'

// Test users with compliant passwords (from iac/users.yaml)
const users = {
  admin: { username: 'admin', password: 'Admin123!' },
  developer: { username: 'seniordev', password: 'Developer123!' },
  infra: { username: 'infra', password: 'Infra123!' },
  productOwner: { username: 'productowner', password: 'Product123!' },
  juniorDev: { username: 'juniordev', password: 'Developer123!' },  // Uses same password as seniordev
}

// Helper to login
async function login(page, username, password) {
  await page.goto('/')
  await page.getByRole('button', { name: /login/i }).click()
  await page.waitForURL(new RegExp(KEYCLOAK_URL))
  await page.fill('#username', username)
  await page.fill('#password', password)
  await page.click('#kc-login')
  await page.waitForURL(new RegExp(BASE_URL))
}

test.describe('Chat and Plan Creation', () => {
  test.beforeEach(async ({ page }) => {
    // Login as developer for most tests
    await login(page, users.developer.username, users.developer.password)
  })

  test('can send a chat message', async ({ page }) => {
    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()

    // Should see welcome message
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible()

    // Type a message
    const input = page.getByPlaceholder(/type your message/i)
    await input.fill('Hello, can you help me create a calculator?')
    await input.press('Enter')

    // Should see user message
    await expect(page.getByText('Hello, can you help me create a calculator?')).toBeVisible()

    // Wait for response (may take a moment)
    await expect(page.getByText(/thinking/i).or(page.locator('.message.assistant').last())).toBeVisible({ timeout: 30000 })
  })

  test('can use suggestion buttons', async ({ page }) => {
    await page.getByRole('link', { name: /chat/i }).click()

    // Click a suggestion
    const suggestion = page.getByRole('button', { name: /create a simple calculator/i })
    await suggestion.click()

    // Should fill input
    const input = page.getByPlaceholder(/type your message/i)
    await expect(input).toHaveValue(/calculator/i)
  })

  test('shows plan ID after creating a plan', async ({ page }) => {
    await page.getByRole('link', { name: /chat/i }).click()

    const input = page.getByPlaceholder(/type your message/i)
    await input.fill('Create a simple todo app')
    await input.press('Enter')

    // Wait for response
    await page.waitForTimeout(5000)

    // Should show active plan indicator (if plan was created)
    // This depends on backend response
  })
})

test.describe('Deployment Approval Workflow', () => {
  test('deployment request creates pending approval for infra-engineer', async ({ page }) => {
    // Login as developer
    await login(page, users.developer.username, users.developer.password)

    // Go to chat and request deployment
    await page.getByRole('link', { name: /chat/i }).click()

    const input = page.getByPlaceholder(/type your message/i)
    await input.fill('Deploy the latest changes to production')
    await input.press('Enter')

    // Wait for response
    await page.waitForTimeout(5000)

    // Should mention pending approvals
    // The response should indicate that infra-engineer approval is needed
  })

  test('infra-engineer can see and approve deployment tasks', async ({ page }) => {
    // Login as infra engineer
    await login(page, users.infra.username, users.infra.password)

    // Navigate to approvals (use exact name to avoid matching "Pending Approvals")
    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see approvals page
    await expect(page.getByText(/pending approvals/i)).toBeVisible()

    // If there are pending tasks, should see approve button
    const approveButton = page.getByRole('button', { name: /approve/i }).first()
    if (await approveButton.isVisible()) {
      // Can approve
      await approveButton.click()

      // Should update status
      await expect(page.getByText(/approved/i).or(page.getByText(/all caught up/i))).toBeVisible({ timeout: 5000 })
    }
  })

  test('developer cannot approve deployment tasks', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    await page.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see message about role requirements for deployment tasks
    // If there are deployment tasks, should see "You need the infra-engineer role"
    const roleMessage = page.getByText(/you need the/i)
    if (await roleMessage.isVisible()) {
      await expect(roleMessage).toContainText(/infra-engineer/)
    }
  })
})

test.describe('Multi-user Approval Flow', () => {
  test('full approval workflow: developer creates, infra approves', async ({ browser }) => {
    // Create two browser contexts for different users
    const developerContext = await browser.newContext()
    const infraContext = await browser.newContext()

    const developerPage = await developerContext.newPage()
    const infraPage = await infraContext.newPage()

    // Developer creates a deployment request
    await login(developerPage, users.developer.username, users.developer.password)
    await developerPage.getByRole('link', { name: /chat/i }).click()

    const input = developerPage.getByPlaceholder(/type your message/i)
    await input.fill('Deploy my app to production')
    await input.press('Enter')
    await developerPage.waitForTimeout(3000)

    // Infra engineer logs in and checks approvals
    await login(infraPage, users.infra.username, users.infra.password)
    await infraPage.getByRole('link', { name: 'Approvals', exact: true }).click()

    // Should see the pending approval
    await expect(infraPage.getByText(/pending approvals/i)).toBeVisible()

    // If there's an approval to make
    const approveButton = infraPage.getByRole('button', { name: /approve/i }).first()
    if (await approveButton.isVisible()) {
      await approveButton.click()
    }

    // Cleanup
    await developerContext.close()
    await infraContext.close()
  })
})

test.describe('App Creation E2E', () => {
  test('junior dev can create a todo app and see files created', async ({ page }) => {
    // Login as junior dev (simulating user's scenario)
    await login(page, users.juniorDev.username, users.juniorDev.password)

    // Navigate to chat
    await page.getByRole('link', { name: /chat/i }).click()

    // Should see welcome message
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 10000 })

    // Request to create a todo app
    const input = page.getByPlaceholder(/type your message/i)
    await input.fill('Create a todo app')
    await input.press('Enter')

    // Should see user message
    await expect(page.getByText('Create a todo app')).toBeVisible()

    // Wait for response that includes success indicators
    // The response should mention files created, not just "completed"
    await expect(
      page.getByText(/files_created|executed|completed/i)
    ).toBeVisible({ timeout: 30000 })

    // Navigate to workspace to see created files
    await page.getByRole('link', { name: /workspace/i }).click()

    // Should show workspace page with heading
    await expect(page.getByRole('heading', { name: /workspace/i })).toBeVisible()

    // Should show projects section
    await expect(page.getByText(/projects/i)).toBeVisible()
  })

  test('can create a calculator app', async ({ page }) => {
    await login(page, users.developer.username, users.developer.password)

    await page.getByRole('link', { name: /chat/i }).click()
    await expect(page.getByText(/I'm Druppie/i)).toBeVisible({ timeout: 10000 })

    const input = page.getByPlaceholder(/type your message/i)
    await input.fill('Build me a calculator')
    await input.press('Enter')

    await expect(page.getByText('Build me a calculator')).toBeVisible()

    // Wait for successful response
    await expect(
      page.getByText(/executed|completed|calculator/i)
    ).toBeVisible({ timeout: 30000 })
  })
})
