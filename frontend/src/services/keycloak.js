/**
 * Keycloak Authentication Service
 */

import Keycloak from 'keycloak-js'

const keycloakConfig = {
  url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8080',
  realm: import.meta.env.VITE_KEYCLOAK_REALM || 'druppie',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'druppie-frontend',
}

let keycloakInstance = null
let keycloakAvailable = false

// Token storage keys
const TOKEN_KEY = 'kc_token'
const REFRESH_TOKEN_KEY = 'kc_refresh_token'
const ID_TOKEN_KEY = 'kc_id_token'

const saveTokens = (token, refreshToken, idToken) => {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  if (refreshToken) sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
  if (idToken) sessionStorage.setItem(ID_TOKEN_KEY, idToken)
}

const loadTokens = () => ({
  token: sessionStorage.getItem(TOKEN_KEY),
  refreshToken: sessionStorage.getItem(REFRESH_TOKEN_KEY),
  idToken: sessionStorage.getItem(ID_TOKEN_KEY),
})

const clearTokens = () => {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(REFRESH_TOKEN_KEY)
  sessionStorage.removeItem(ID_TOKEN_KEY)
}

/**
 * Check if Keycloak server is available and ready
 * @param {number} timeout - Timeout in milliseconds
 * @returns {Promise<boolean>} - True if Keycloak is ready
 */
const checkKeycloakHealth = async (timeout = 10000) => {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    // Try the realm endpoint which should be available when Keycloak is ready
    const response = await fetch(
      `${keycloakConfig.url}/realms/${keycloakConfig.realm}`,
      {
        method: 'GET',
        signal: controller.signal,
      }
    )
    clearTimeout(timeoutId)
    return response.ok
  } catch (error) {
    clearTimeout(timeoutId)
    // Health check failure is expected when Keycloak is unavailable
    return false
  }
}

/**
 * Wait for Keycloak to become available with retries
 * @param {number} maxRetries - Maximum number of retries
 * @param {number} retryDelay - Delay between retries in milliseconds
 * @returns {Promise<boolean>} - True if Keycloak became available
 */
const waitForKeycloak = async (maxRetries = 5, retryDelay = 3000) => {
  for (let i = 0; i < maxRetries; i++) {
    const isHealthy = await checkKeycloakHealth()
    if (isHealthy) {
      return true
    }
    if (i < maxRetries - 1) {
      await new Promise(resolve => setTimeout(resolve, retryDelay))
    }
  }
  return false
}

export const initKeycloak = async () => {
  if (keycloakInstance && keycloakInstance.authenticated !== undefined) {
    return keycloakInstance
  }

  keycloakInstance = new Keycloak(keycloakConfig)

  const savedTokens = loadTokens()

  // Adopting a previously stored session must NOT trigger a Keycloak redirect.
  // The branch-env dev workspace serves this app via Vite on a separate host
  // (<slug>-dev.rijnland.dev) while Keycloak lives on the base env host, so a
  // hot-reload (Vite currently does this as a full page refresh) would
  // otherwise re-run `check-sso` and bounce through a cross-origin Keycloak
  // redirect on every edit — surfacing as "not authenticated" flashes and
  // 401s even though the user is logged in. When we already hold tokens we
  // adopt them directly and only refresh; check-sso is used solely for a cold
  // first load with no stored session.
  const hasStoredSession = Boolean(savedTokens.token && savedTokens.refreshToken)
  const initOptions = { checkLoginIframe: false }
  if (hasStoredSession) {
    initOptions.token = savedTokens.token
    initOptions.refreshToken = savedTokens.refreshToken
    // Re-adopt the stored idToken too, so keycloakInstance.idToken is
    // populated immediately after a reload — logout() needs it as the
    // id_token_hint for a clean (non-interactive) single logout.
    if (savedTokens.idToken) initOptions.idToken = savedTokens.idToken
  } else {
    initOptions.onLoad = 'check-sso'
    initOptions.silentCheckSsoFallback = true
  }

  try {
    let authenticated = await keycloakInstance.init(initOptions)

    // A stored access token may already be expired after an idle period; the
    // refresh token usually still works, so force a refresh before giving up.
    if (!authenticated && hasStoredSession) {
      try {
        authenticated = await keycloakInstance.updateToken(-1)
      } catch {
        authenticated = false
      }
    }

    if (authenticated) {
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken, keycloakInstance.idToken)
    } else {
      clearTokens()
    }

    keycloakInstance.onTokenExpired = () => {
      keycloakInstance.updateToken(30).then(() => {
        saveTokens(keycloakInstance.token, keycloakInstance.refreshToken, keycloakInstance.idToken)
      }).catch(() => {
        clearTokens()
        keycloakInstance.logout()
      })
    }

    return keycloakInstance
  } catch (error) {
    clearTokens()
    if (keycloakInstance) {
      keycloakInstance.authenticated = false
    }
    return keycloakInstance || { authenticated: false }
  }
}

/**
 * Check if Keycloak server is available
 * @returns {boolean}
 */
export const isKeycloakAvailable = () => keycloakAvailable

export const getKeycloak = () => keycloakInstance

export const login = () => {
  if (keycloakInstance) {
    keycloakInstance.login()
  }
}

export const logout = () => {
  clearTokens()
  if (keycloakInstance) {
    keycloakInstance.logout({
      redirectUri: window.location.origin,
      id_token_hint: keycloakInstance.idToken,
    })
  }
}

export const getToken = () => {
  return keycloakInstance?.token
}

export const ensureValidToken = async (minValidity = 30) => {
  if (!keycloakInstance || !keycloakInstance.authenticated) {
    return false
  }
  try {
    const refreshed = await keycloakInstance.updateToken(minValidity)
    if (refreshed) {
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken, keycloakInstance.idToken)
    }
    return true
  } catch (error) {
    return false
  }
}

export const redirectToLogin = () => {
  keycloakInstance?.login?.()
}

export const isAuthenticated = () => {
  return keycloakInstance?.authenticated || false
}

export const getUserInfo = () => {
  if (!keycloakInstance?.authenticated) {
    return null
  }

  const tokenParsed = keycloakInstance.tokenParsed

  return {
    id: tokenParsed?.sub,
    username: tokenParsed?.preferred_username,
    email: tokenParsed?.email,
    firstName: tokenParsed?.given_name,
    lastName: tokenParsed?.family_name,
    roles: tokenParsed?.realm_access?.roles || [],
  }
}

export const hasRole = (role) => {
  const user = getUserInfo()
  if (!user) return false
  return user.roles.includes(role) || user.roles.includes('admin')
}

export const hasAnyRole = (...roles) => {
  const user = getUserInfo()
  if (!user) return false
  if (user.roles.includes('admin')) return true
  return roles.some(role => user.roles.includes(role))
}
