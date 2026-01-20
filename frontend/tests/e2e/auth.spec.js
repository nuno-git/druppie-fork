// @ts-check
import { test, expect } from '@playwright/test'

const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8080'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5173'

// Test users from iac/users.yaml
const users = {
  admin: { username: 'admin', password: 'Admin123!', roles: ['admin'] },
  developer: { username: 'seniordev', password: 'Developer123!', roles: ['developer'] },
  infra: { username: 'infra', password: 'Infra123!', roles: ['infra-engineer'] },
  productOwner: { username: 'productowner', password: 'Product123!', roles: ['product-owner'] },
}

test.describe('Authentication', () => {
  test('should show login button when not authenticated', async ({ page }) => {
    await page.goto('/')

    // Should see login button (wait up to 15s for Keycloak init timeout)
    await expect(page.getByRole('button', { name: /login/i })).toBeVisible({ timeout: 15000 })
  })

  test('should redirect to Keycloak on login click', async ({ page }) => {
    await page.goto('/')

    // Click login
    await page.getByRole('button', { name: /login/i }).click()

    // Should redirect to Keycloak
    await expect(page).toHaveURL(new RegExp(KEYCLOAK_URL))
  })

  test('admin can login and see all features', async ({ page }) => {
    // Navigate to app
    await page.goto('/')

    // Click login
    await page.getByRole('button', { name: /login/i }).click()

    // Wait for Keycloak login page
    await page.waitForURL(new RegExp(KEYCLOAK_URL))

    // Fill login form
    await page.fill('#username', users.admin.username)
    await page.fill('#password', users.admin.password)
    await page.click('#kc-login')

    // Wait for redirect back to app
    await page.waitForURL(new RegExp(BASE_URL))

    // Should see dashboard
    await expect(page.getByText(/welcome back/i)).toBeVisible()

    // Should see admin badge in header
    await expect(page.getByText('Admin', { exact: true })).toBeVisible()

    // Should see navigation items
    await expect(page.getByRole('heading', { name: /welcome back/i })).toBeVisible()
  })

  test('developer can login and has limited access', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /login/i }).click()
    await page.waitForURL(new RegExp(KEYCLOAK_URL))

    await page.fill('#username', users.developer.username)
    await page.fill('#password', users.developer.password)
    await page.click('#kc-login')

    await page.waitForURL(new RegExp(BASE_URL))

    // Should see dashboard
    await expect(page.getByText(/welcome back/i)).toBeVisible()

    // Should see developer role
    await expect(page.getByText('developer')).toBeVisible()
  })

  test('can logout', async ({ page }) => {
    // Login first
    await page.goto('/')
    await page.getByRole('button', { name: /login/i }).click()
    await page.waitForURL(new RegExp(KEYCLOAK_URL))

    await page.fill('#username', users.admin.username)
    await page.fill('#password', users.admin.password)
    await page.click('#kc-login')
    await page.waitForURL(new RegExp(BASE_URL))

    // Click logout
    await page.getByRole('button', { name: /logout/i }).click()

    // Should redirect to Keycloak and back, showing login button
    await expect(page.getByRole('button', { name: /login/i })).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Role-based Access', () => {
  test('infra-engineer can approve deployment tasks', async ({ page }) => {
    // Login as infra engineer
    await page.goto('/')
    await page.getByRole('button', { name: /login/i }).click({ timeout: 15000 })
    await page.waitForURL(new RegExp(KEYCLOAK_URL))

    await page.fill('#username', users.infra.username)
    await page.fill('#password', users.infra.password)
    await page.click('#kc-login')
    await page.waitForURL(new RegExp(BASE_URL))

    // Should see infra-engineer role in user's roles
    await expect(page.getByText('infra-engineer')).toBeVisible()
  })

  test('product-owner can view plans but not approve deployments', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /login/i }).click()
    await page.waitForURL(new RegExp(KEYCLOAK_URL))

    await page.fill('#username', users.productOwner.username)
    await page.fill('#password', users.productOwner.password)
    await page.click('#kc-login')
    await page.waitForURL(new RegExp(BASE_URL))

    // Navigate to plans
    await page.getByRole('link', { name: /plans/i }).click()

    // Should see plans page
    await expect(page.getByText(/execution plans/i)).toBeVisible()
  })
})
