/**
 * Druppie Core - React Hook for Druppie Platform Integration
 *
 * Provides:
 * - Keycloak authentication via Druppie
 * - MCP tool access through Druppie's governance layer
 * - Real-time updates via WebSocket
 */

import { useState, useEffect, useCallback, createContext, useContext } from 'react';

// Druppie Platform Configuration
const DRUPPIE_URL = window.DRUPPIE_URL || 'http://localhost:8000';
const DRUPPIE_WS_URL = DRUPPIE_URL.replace('http', 'ws');

// Context for global Druppie state
const DruppieContext = createContext(null);

/**
 * Druppie Provider Component
 * Wrap your app with this to enable Druppie integration
 */
export function DruppieProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);
  const [socket, setSocket] = useState(null);

  // Initialize - check for existing session
  useEffect(() => {
    const checkSession = async () => {
      const savedToken = localStorage.getItem('druppie_token');
      if (savedToken) {
        try {
          const response = await fetch(`${DRUPPIE_URL}/api/user`, {
            headers: { Authorization: `Bearer ${savedToken}` },
          });
          if (response.ok) {
            const userData = await response.json();
            setUser(userData);
            setToken(savedToken);
          } else {
            localStorage.removeItem('druppie_token');
          }
        } catch (err) {
          console.error('Session check failed:', err);
        }
      }
      setLoading(false);
    };
    checkSession();
  }, []);

  // Login redirect to Druppie/Keycloak
  const login = useCallback(() => {
    // Redirect to Druppie login page
    const returnUrl = encodeURIComponent(window.location.href);
    window.location.href = `${DRUPPIE_URL}/auth/login?return_to=${returnUrl}`;
  }, []);

  // Logout
  const logout = useCallback(() => {
    localStorage.removeItem('druppie_token');
    setUser(null);
    setToken(null);
  }, []);

  // API call helper with auth
  const apiCall = useCallback(async (endpoint, options = {}) => {
    const headers = {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...options.headers,
    };

    const response = await fetch(`${DRUPPIE_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }, [token]);

  // Execute MCP tool through Druppie governance
  const executeTool = useCallback(async (toolName, params) => {
    return apiCall('/api/mcp/execute', {
      method: 'POST',
      body: JSON.stringify({ tool: toolName, params }),
    });
  }, [apiCall]);

  // Check if user has permission for a tool
  const checkPermission = useCallback(async (toolName) => {
    return apiCall('/api/mcp/check', {
      method: 'POST',
      body: JSON.stringify({ tool: toolName }),
    });
  }, [apiCall]);

  const value = {
    user,
    token,
    loading,
    isAuthenticated: !!user,
    login,
    logout,
    apiCall,
    executeTool,
    checkPermission,
  };

  return (
    <DruppieContext.Provider value={value}>
      {children}
    </DruppieContext.Provider>
  );
}

/**
 * Hook to access Druppie functionality
 */
export function useDruppie() {
  const context = useContext(DruppieContext);
  if (!context) {
    throw new Error('useDruppie must be used within a DruppieProvider');
  }
  return context;
}

/**
 * Component that requires authentication
 * Redirects to login if not authenticated
 */
export function RequireAuth({ children }) {
  const { isAuthenticated, loading, login } = useDruppie();

  if (loading) {
    return (
      <div className="druppie-loading">
        <div className="druppie-spinner"></div>
        <p>Checking authentication...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="druppie-login-prompt">
        <h2>Authentication Required</h2>
        <p>Please log in to access this application.</p>
        <button onClick={login} className="druppie-login-btn">
          Login with Druppie
        </button>
      </div>
    );
  }

  return children;
}

export default useDruppie;
