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
const checkKeycloakHealth = async (timeout = 5000) => {
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
    console.log('Keycloak health check failed:', error.message)
    return false
  }
}

/**
 * Wait for Keycloak to become available with retries
 * @param {number} maxRetries - Maximum number of retries
 * @param {number} retryDelay - Delay between retries in milliseconds
 * @returns {Promise<boolean>} - True if Keycloak became available
 */
const waitForKeycloak = async (maxRetries = 3, retryDelay = 2000) => {
  for (let i = 0; i < maxRetries; i++) {
    console.log(`Checking Keycloak availability (attempt ${i + 1}/${maxRetries})...`)
    const isHealthy = await checkKeycloakHealth()
    if (isHealthy) {
      console.log('Keycloak is available')
      return true
    }
    if (i < maxRetries - 1) {
      console.log(`Keycloak not ready, retrying in ${retryDelay}ms...`)
      await new Promise(resolve => setTimeout(resolve, retryDelay))
    }
  }
  console.log('Keycloak is not available after retries')
  return false
}

export const initKeycloak = async () => {
  if (keycloakInstance && keycloakInstance.authenticated !== undefined) {
    return keycloakInstance
  }

  // First, check if Keycloak is available
  keycloakAvailable = await waitForKeycloak(3, 2000)

  if (!keycloakAvailable) {
    console.log('Keycloak server is not available - app will run in unauthenticated mode')
    clearTokens()
    // Return a mock keycloak object that allows showing login button
    keycloakInstance = {
      authenticated: false,
      login: () => {
        // Try to redirect to Keycloak login anyway - it might work by then
        window.location.href = `${keycloakConfig.url}/realms/${keycloakConfig.realm}/protocol/openid-connect/auth?client_id=${keycloakConfig.clientId}&redirect_uri=${encodeURIComponent(window.location.origin)}&response_type=code&scope=openid`
      },
      logout: () => {
        clearTokens()
        window.location.reload()
      },
    }
    return keycloakInstance
  }

  keycloakInstance = new Keycloak(keycloakConfig)

  // Load saved tokens
  const savedTokens = loadTokens()

  try {
    // Add timeout for Keycloak init - longer timeout since we already verified availability
    const initPromise = keycloakInstance.init({
      onLoad: 'check-sso',
      silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
      checkLoginIframe: false,
      token: savedTokens.token,
      refreshToken: savedTokens.refreshToken,
      // Shorter silent SSO timeout since Keycloak is confirmed available
      silentCheckSsoFallback: false,
    })

    const timeoutPromise = new Promise((_, reject) => {
      // 15 second timeout for init after health check passed
      setTimeout(() => reject(new Error('Keycloak init timeout')), 15000)
    })

    const authenticated = await Promise.race([initPromise, timeoutPromise])

    if (authenticated) {
      // Save tokens on successful auth
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
    } else {
      console.log('User is not authenticated')
      clearTokens()
    }

    // Setup token refresh
    keycloakInstance.onTokenExpired = () => {
      keycloakInstance.updateToken(30).then(() => {
        // Save refreshed tokens
        saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
      }).catch(() => {
        console.log('Failed to refresh token')
        clearTokens()
        keycloakInstance.logout()
      })
    }

    return keycloakInstance
  } catch (error) {
    console.error('Keycloak initialization failed:', error)
    // Clear any invalid stored tokens
    clearTokens()
    // Return the keycloak instance with authenticated: false
    // This allows the login button to work even if silent SSO failed
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
