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

export const initKeycloak = async () => {
  if (keycloakInstance) {
    return keycloakInstance
  }

  keycloakInstance = new Keycloak(keycloakConfig)

  // Load saved tokens
  const savedTokens = loadTokens()

  try {
    // Add timeout for Keycloak init
    const initPromise = keycloakInstance.init({
      onLoad: 'check-sso',
      silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
      checkLoginIframe: false,
      token: savedTokens.token,
      refreshToken: savedTokens.refreshToken,
    })

    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error('Keycloak init timeout')), 30000)
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
    // Return a mock keycloak that allows showing login button
    return { authenticated: false }
  }
}

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
