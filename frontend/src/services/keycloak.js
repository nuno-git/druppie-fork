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

const saveTokens = (token, refreshToken) => {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

const loadTokens = () => ({
  token: localStorage.getItem(TOKEN_KEY),
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
})

const clearTokens = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
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

  try {
    const authenticated = await keycloakInstance.init({
      onLoad: 'check-sso',
      checkLoginIframe: false,
      token: savedTokens.token,
      refreshToken: savedTokens.refreshToken,
      silentCheckSsoFallback: true,
    })

    if (authenticated) {
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
    } else {
      clearTokens()
    }

    keycloakInstance.onTokenExpired = () => {
      keycloakInstance.updateToken(30).then(() => {
        saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
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
    keycloakInstance.logout()
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
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
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
