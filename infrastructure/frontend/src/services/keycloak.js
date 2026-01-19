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

export const initKeycloak = async () => {
  if (keycloakInstance) {
    return keycloakInstance
  }

  keycloakInstance = new Keycloak(keycloakConfig)

  try {
    const authenticated = await keycloakInstance.init({
      onLoad: 'check-sso',
      silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
      checkLoginIframe: false,
    })

    if (!authenticated) {
      console.log('User is not authenticated')
    }

    // Setup token refresh
    keycloakInstance.onTokenExpired = () => {
      keycloakInstance.updateToken(30).catch(() => {
        console.log('Failed to refresh token')
        keycloakInstance.logout()
      })
    }

    return keycloakInstance
  } catch (error) {
    console.error('Keycloak initialization failed:', error)
    throw error
  }
}

export const getKeycloak = () => keycloakInstance

export const login = () => {
  if (keycloakInstance) {
    keycloakInstance.login()
  }
}

export const logout = () => {
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
