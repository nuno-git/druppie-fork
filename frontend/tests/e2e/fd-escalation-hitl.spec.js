// @ts-check
//
// E2E: FD-escalation HITL review surfaces (BA + Architect).
//
// These flows require a session that is already paused in the escalation state
// machine, which only the backend can produce. The spec drives the UI against a
// session seeded via the evaluations setup test, then asserts the review cards
// render and act. If the backend is not running locally the spec is skipped
// automatically (see the `beforeAll` health check).
//
// Run scoped:
//   npx playwright test tests/e2e/fd-escalation-hitl.spec.js
import { test, expect } from '@playwright/test'

const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'http://localhost:8180'
const BASE_URL = process.env.BASE_URL || 'http://localhost:5273'
const API_URL = process.env.API_URL || 'http://localhost:8100'

const ADMIN = { username: 'admin', password: 'Admin123!' }

async function clickLoginButton(page) {
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {})
  const loginButton = page.locator('button:has-text("Login"), button:has-text("Log In")').first()
  await loginButton.click()
}

async function login(page, { username, password }) {
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

async function getToken(request) {
  const resp = await request.post(`${KEYCLOAK_URL.replace(/\/$/, '')}/realms/druppie/protocol/openid-connect/token`, {
    form: {
      grant_type: 'password',
      client_id: 'druppie-frontend',
      username: ADMIN.username,
      password: ADMIN.password,
    },
  })
  const body = await resp.json()
  return body.access_token
}

async function backendUp(request) {
  try {
    const resp = await request.get(`${API_URL.replace(/\/$/, '')}/health`, { timeout: 5000 })
    return resp.ok()
  } catch {
    return false
  }
}

// Find the most recent session in an escalation HITL status.
async function findEscalationSession(request, token, status) {
  const resp = await request.get(`${API_URL.replace(/\/$/, '')}/api/sessions?limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const sessions = await resp.json()
  return (sessions.items || []).find((s) => s.status === status) || null
}

test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
})

test.describe('FD escalation HITL', () => {
  test('BA review card — escalate is disabled until a post-HITL rejection', async ({ page, request }) => {
    test.skip(!(await backendUp(request)), 'backend not running locally')

    const token = await getToken(request)
    const session = await findEscalationSession(request, token, 'paused_ba_hitl')
    test.skip(!session, 'no paused_ba_hitl session available to test against')

    await login(page, ADMIN)
    await page.goto(`/?session=${session.id}`)

    const card = page.locator('text=Business analyst review').locator('..')
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByRole('button', { name: /escalate/i })).toBeDisabled()
    await expect(card.getByRole('button', { name: /iterate|ready|terminate/i })).toHaveCount(3)
  })

  test('Architect review card — reject reveals next-on-reject chooser', async ({ page, request }) => {
    test.skip(!(await backendUp(request)), 'backend not running locally')

    const token = await getToken(request)
    const session = await findEscalationSession(request, token, 'paused_architect_hitl')
    test.skip(!session, 'no paused_architect_hitl session available to test against')

    await login(page, ADMIN)
    await page.goto(`/?session=${session.id}`)

    const card = page.locator('text=Architect review').locator('..')
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(card.getByRole('button', { name: /back to ba review|terminate session/i })).toHaveCount(0)
    await card.getByRole('button', { name: /reject/i }).click()
    await expect(card.getByRole('button', { name: /back to ba review/i })).toBeVisible()
    await expect(card.getByRole('button', { name: /terminate session/i })).toBeVisible()
  })
})
