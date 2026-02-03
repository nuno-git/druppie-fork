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
let keycloakInitialized = false  // Add this flag to prevent re-initialization

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
    // Note: We use 'no-cors' mode because Keycloak may not have CORS headers configured
    // In no-cors mode, we can't read the response, but if the fetch succeeds, 
    // we know the server is reachable
    const response = await fetch(
      `${keycloakConfig.url}/realms/${keycloakConfig.realm}`,
      {
        method: 'GET',
        signal: controller.signal,
        mode: 'no-cors',
      }
    )
    clearTimeout(timeoutId)
    // If fetch doesn't throw, the server is reachable
    return true
  } catch (error) {
    clearTimeout(timeoutId)
    // Network error or timeout
    console.log('[KC Health] Health check failed:', error.message)
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
  console.log('[KC Init] waitForKeycloak called with', maxRetries, 'retries')
  // Try to actually check if Keycloak is available using fetch
  // This helps us know if we should try to initialize keycloak-js
  for (let i = 0; i < maxRetries; i++) {
    try {
      // Use no-cors mode to work around CORS issues
      const response = await fetch(`${keycloakConfig.url}/health/ready`, {
        mode: 'no-cors',
        signal: AbortSignal.timeout ? AbortSignal.timeout(3000) : undefined,
      })
      console.log('[KC Init] Health check passed')
      return true
    } catch (error) {
      console.log('[KC Init] Health check failed (attempt', i + 1, '):', error.message)
      if (i < maxRetries - 1) {
        await new Promise(resolve => setTimeout(resolve, retryDelay))
      }
    }
  }
  console.log('[KC Init] All health checks failed')
  return false
}

export const initKeycloak = async () => {
  console.log('[KC Init] Starting Keycloak initialization')
  console.log('[KC Init] Already initialized:', keycloakInitialized)
  console.log('[KC Init] Instance exists:', !!keycloakInstance)
  
  // Prevent multiple initialization attempts
  if (keycloakInitialized && keycloakInstance) {
    console.log('[KC Init] Keycloak already initialized, returning existing instance')
    return keycloakInstance
  }
  
  if (keycloakInitialized) {
    console.log('[KC Init] Initialization already attempted, returning mock instance')
    return keycloakInstance || { authenticated: false }
  }
  
  keycloakInitialized = true
  
  console.log('[KC Init] Config:', keycloakConfig)
  console.log('[KC Init] Current URL:', window.location.href)

  // First, check if Keycloak is available
  console.log('[KC Init] Checking Keycloak health...')
  keycloakAvailable = await waitForKeycloak(3, 2000)
  console.log('[KC Init] Keycloak available:', keycloakAvailable)

  if (!keycloakAvailable) {
    console.warn('[KC Init] Keycloak unavailable - using mock authentication')
    // Keycloak unavailable - app will run in unauthenticated mode
    clearTokens()
    // Return a mock keycloak object that allows showing login button
    keycloakInstance = {
      authenticated: false,
      login: () => {
        console.log('[KC Mock] Mock login called')
        // Try to redirect to Keycloak login anyway - it might work by then
        const loginUrl = `${keycloakConfig.url}/realms/${keycloakConfig.realm}/protocol/openid-connect/auth?client_id=${keycloakConfig.clientId}&redirect_uri=${encodeURIComponent(window.location.origin)}&response_type=code&scope=openid`
        console.log('[KC Mock] Redirecting to:', loginUrl)
        window.location.href = loginUrl
      },
      logout: () => {
        clearTokens()
        window.location.reload()
      },
    }
    return keycloakInstance
  }

  console.log('[KC Init] Creating Keycloak instance with config:', {
    url: keycloakConfig.url,
    realm: keycloakConfig.realm,
    clientId: keycloakConfig.clientId,
  })
  
  keycloakInstance = new Keycloak(keycloakConfig)
  console.log('[KC Init] Keycloak instance created, type:', keycloakInstance?.constructor?.name)

  // Load saved tokens
  const savedTokens = loadTokens()
  console.log('[KC Init] Loaded saved tokens:', !!savedTokens.token)

  try {
    // Add timeout for Keycloak init - longer timeout since we already verified availability
    console.log('[KC Init] Starting Keycloak.init() with options:')
    const initOptions = {
      onLoad: 'login-optional',  // Don't auto-redirect, just check silently
      checkLoginIframe: false,
      silentCheckSsoFallback: false,
    }
    console.log('[KC Init] Init options:', initOptions)
    
    const initPromise = keycloakInstance.init(initOptions)

    const timeoutPromise = new Promise((_, reject) => {
      // 30 second timeout for init after health check passed (increased for slow VMs)
      setTimeout(() => reject(new Error('Keycloak init timeout')), 30000)
    })

    const authenticated = await Promise.race([initPromise, timeoutPromise])
    console.log('[KC Init] Keycloak init completed, authenticated:', authenticated)
    console.log('[KC Init] Keycloak token:', !!keycloakInstance?.token)
    console.log('[KC Init] Keycloak token parsed:', keycloakInstance?.tokenParsed)

    if (authenticated) {
      // Save tokens on successful auth
      saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
      console.log('[KC Init] Tokens saved')
    } else {
      clearTokens()
      console.log('[KC Init] Not authenticated, tokens cleared')
    }

    // Setup token refresh
    keycloakInstance.onTokenExpired = () => {
      console.log('[KC Init] Token expired, attempting refresh')
      keycloakInstance.updateToken(30).then(() => {
        // Save refreshed tokens
        saveTokens(keycloakInstance.token, keycloakInstance.refreshToken)
        console.log('[KC Init] Token refreshed')
      }).catch((err) => {
        console.error('[KC Init] Failed to refresh Keycloak token:', err)
        clearTokens()
        keycloakInstance.logout()
      })
    }

    console.log('[KC Init] Keycloak initialization successful')
    return keycloakInstance
  } catch (error) {
    console.error('[KC Init] Keycloak initialization failed:', error)
    console.error('[KC Init] Error message:', error.message)
    console.error('[KC Init] Error stack:', error.stack)
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
  console.log('[Login] Login function called')
  console.log('[Login] Keycloak config:', keycloakConfig)
  console.log('[Login] Keycloak instance ready:', !!keycloakInstance)
  
  if (!keycloakInstance) {
    console.error('[Login] Keycloak instance not available')
    // Direct redirect as fallback
    window.location.href = `${keycloakConfig.url}/realms/${keycloakConfig.realm}/protocol/openid-connect/auth?client_id=${keycloakConfig.clientId}&redirect_uri=${encodeURIComponent(window.location.origin)}&response_type=code&scope=openid`
    return
  }
  
  console.log('[Login] Calling keycloakInstance.login()')
  try {
    keycloakInstance.login({
      scope: 'openid profile email',
    })
  } catch (e) {
    console.error('[Login] Error calling login():', e)
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
