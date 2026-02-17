/**
 * Druppie Governance Platform - Main Application
 */

import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Shield, LogIn } from 'lucide-react'

import { initKeycloak, login, getUserInfo, hasRole } from './services/keycloak'
import { ToastProvider } from './components/Toast'
import ErrorBoundary from './components/ErrorBoundary'
import NavRail from './components/NavRail'

// Pages
import Dashboard from './pages/Dashboard'
import Tasks from './pages/Tasks'
import Chat from './pages/Chat'
import DebugMCP from './pages/DebugMCP'
import DebugProjects from './pages/DebugProjects'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Settings from './pages/Settings'
import AdminDatabase from './pages/AdminDatabase'

// Auth context
const AuthContext = React.createContext(null)

export const useAuth = () => React.useContext(AuthContext)

// Protected Route
const ProtectedRoute = ({ children, requiredRole }) => {
  const { authenticated, user } = useAuth()

  if (!authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h2 className="text-2xl font-bold mb-4">Please log in to continue</h2>
          <button
            onClick={login}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <LogIn className="w-5 h-5 inline mr-2" />
            Log In with Keycloak
          </button>
        </div>
      </div>
    )
  }

  if (requiredRole && !hasRole(requiredRole)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <Shield className="w-16 h-16 text-red-500 mx-auto mb-4" />
          <h2 className="text-2xl font-bold mb-2">Access Denied</h2>
          <p className="text-gray-600">You need the "{requiredRole}" role to access this page.</p>
        </div>
      </div>
    )
  }

  return children
}

// Redirect /debug/:sessionId → /chat?session=:sessionId&mode=inspect
const DebugRedirect = () => {
  const { sessionId } = useParams()
  return <Navigate to={`/chat?session=${sessionId}&mode=inspect`} replace />
}

// Main App
function App() {
  const [keycloakReady, setKeycloakReady] = useState(false)
  const [authenticated, setAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const init = async () => {
      try {
        const kc = await initKeycloak()
        setAuthenticated(kc.authenticated)
        if (kc.authenticated) {
          setUser(getUserInfo())
        }
        setKeycloakReady(true)
      } catch (err) {
        console.error('Failed to initialize Keycloak:', err)
        setError('Failed to connect to authentication server')
        setKeycloakReady(true) // Still show app, just not authenticated
      }
    }

    init()
  }, [])

  if (!keycloakReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Connecting to authentication server...</p>
          <p className="text-gray-400 text-sm mt-2">This may take a moment on first load</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="text-yellow-500 mb-4">
            <Shield className="w-16 h-16 mx-auto" />
          </div>
          <h2 className="text-xl font-bold mb-2">Authentication Server Unavailable</h2>
          <p className="text-gray-600 mb-4">{error}</p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
            >
              Retry Connection
            </button>
            <button
              onClick={login}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <LogIn className="w-4 h-4 inline mr-1" />
              Try Login Anyway
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <AuthContext.Provider value={{ authenticated, user }}>
        <ToastProvider>
          <BrowserRouter>
            <div className="flex h-screen bg-gray-50 overflow-hidden">
              <NavRail />
              <Routes>
                {/* Full-bleed routes: Chat manages its own sidebar */}
                <Route
                  path="/chat"
                  element={
                    <ProtectedRoute>
                      <ErrorBoundary>
                        <Chat />
                      </ErrorBoundary>
                    </ProtectedRoute>
                  }
                />
                {/* Redirect old debug-chat to chat */}
                <Route path="/debug-chat" element={<Navigate to="/chat" replace />} />
                {/* Padded routes: standard content pages */}
                <Route
                  path="*"
                  element={
                    <main className="flex-1 overflow-y-auto">
                      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
                        <ErrorBoundary>
                        <Routes>
                          <Route
                            path="/"
                            element={
                              <ProtectedRoute>
                                <Dashboard />
                              </ProtectedRoute>
                            }
                          />
                          {/* Redirect old debug routes */}
                          <Route path="/debug-approvals" element={<Navigate to="/tasks" replace />} />
                          <Route path="/debug-mcp" element={<Navigate to="/tools/mcp" replace />} />
                          <Route path="/debug-projects" element={<Navigate to="/tools/infrastructure" replace />} />
                          <Route
                            path="/tools/mcp"
                            element={
                              <ProtectedRoute>
                                <DebugMCP />
                              </ProtectedRoute>
                            }
                          />
                          <Route
                            path="/tools/infrastructure"
                            element={
                              <ProtectedRoute>
                                <DebugProjects />
                              </ProtectedRoute>
                            }
                          />
                          <Route
                            path="/tasks"
                            element={
                              <ProtectedRoute>
                                <Tasks />
                              </ProtectedRoute>
                            }
                          />
                          <Route
                            path="/projects"
                            element={
                              <ProtectedRoute>
                                <Projects />
                              </ProtectedRoute>
                            }
                          />
                          <Route
                            path="/projects/:projectId"
                            element={
                              <ProtectedRoute>
                                <ProjectDetail />
                              </ProtectedRoute>
                            }
                          />
                          {/* Redirect old debug trace to chat with inspect mode */}
                          <Route
                            path="/debug/:sessionId"
                            element={<DebugRedirect />}
                          />
                          <Route
                            path="/settings"
                            element={
                              <ProtectedRoute>
                                <Settings />
                              </ProtectedRoute>
                            }
                          />
                          <Route
                            path="/admin/database"
                            element={
                              <ProtectedRoute requiredRole="admin">
                                <AdminDatabase />
                              </ProtectedRoute>
                            }
                          />
                          <Route path="*" element={<Navigate to="/" replace />} />
                        </Routes>
                        </ErrorBoundary>
                      </div>
                    </main>
                  }
                />
              </Routes>
            </div>
          </BrowserRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </ErrorBoundary>
  )
}

export default App
