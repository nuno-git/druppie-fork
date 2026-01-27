/**
 * Druppie Governance Platform - Main Application
 */

import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Home,
  CheckSquare,
  LogOut,
  LogIn,
  User,
  Shield,
  MessageSquare,
  FolderOpen,
  Bug,
  Settings as SettingsIcon,
  Database,
} from 'lucide-react'

import { initKeycloak, login, logout, isAuthenticated, getUserInfo, hasRole, isKeycloakAvailable } from './services/keycloak'
import { getTasks } from './services/api'
import { ToastProvider } from './components/Toast'
import ErrorBoundary from './components/ErrorBoundary'
import ConnectionStatus from './components/ConnectionStatus'

// Pages
import Dashboard from './pages/Dashboard'
import Tasks from './pages/Tasks'
import Chat from './pages/Chat'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Debug from './pages/Debug'
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

// Navigation
const Navigation = () => {
  const { authenticated, user } = useAuth()
  const location = useLocation()

  // Fetch pending approvals count for badge
  const { data: tasksData } = useQuery({
    queryKey: ['pending-approvals-count'],
    queryFn: getTasks,
    enabled: authenticated,
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  const pendingApprovalsCount = tasksData?.approvals?.length || 0

  const navItems = [
    { path: '/', icon: Home, label: 'Dashboard' },
    { path: '/chat', icon: MessageSquare, label: 'Chat' },
    { path: '/tasks', icon: CheckSquare, label: 'Approvals', badge: pendingApprovalsCount },
    { path: '/projects', icon: FolderOpen, label: 'Projects' },
    { path: '/settings', icon: SettingsIcon, label: 'Settings' },
  ]

  // Add admin-only nav items
  const adminNavItems = [
    { path: '/admin/database', icon: Database, label: 'Database' },
  ]

  const isActive = (path) => location.pathname === path || location.pathname.startsWith(path + '/')

  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          {/* Logo */}
          <div className="flex items-center">
            <Link to="/" className="flex items-center space-x-2">
              <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
                <Shield className="w-5 h-5 text-white" />
              </div>
              <span className="text-xl font-bold text-gray-900">Druppie</span>
            </Link>
          </div>

          {/* Navigation */}
          <nav className="hidden md:flex items-center space-x-1">
            {navItems.map(({ path, icon: Icon, label, badge }) => (
              <Link
                key={path}
                to={path}
                className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors relative ${
                  isActive(path)
                    ? 'bg-blue-100 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                <Icon className="w-4 h-4 inline mr-1" />
                {label}
                {badge > 0 && (
                  <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
                    {badge > 9 ? '9+' : badge}
                  </span>
                )}
              </Link>
            ))}
            {/* Admin-only navigation items */}
            {user?.roles?.includes('admin') && adminNavItems.map(({ path, icon: Icon, label }) => (
              <Link
                key={path}
                to={path}
                className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive(path)
                    ? 'bg-purple-100 text-purple-700'
                    : 'text-purple-600 hover:bg-purple-50'
                }`}
              >
                <Icon className="w-4 h-4 inline mr-1" />
                {label}
              </Link>
            ))}
          </nav>

          {/* User Menu */}
          <div className="flex items-center space-x-4">
            {authenticated ? (
              <>
                <div className="hidden sm:flex items-center space-x-2">
                  <User className="w-4 h-4 text-gray-500" />
                  <span className="text-sm text-gray-700">{user?.username}</span>
                  {user?.roles?.includes('admin') && (
                    <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded">
                      Admin
                    </span>
                  )}
                </div>
                <button
                  onClick={logout}
                  className="px-3 py-2 text-sm text-gray-600 hover:text-gray-900"
                >
                  <LogOut className="w-4 h-4 inline mr-1" />
                  Logout
                </button>
              </>
            ) : (
              <button
                onClick={login}
                className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
              >
                <LogIn className="w-4 h-4 inline mr-1" />
                Login
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  )
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
            <div className="min-h-screen bg-gray-50">
              <Navigation />
              <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <Routes>
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <Dashboard />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/chat"
                  element={
                    <ProtectedRoute>
                      <Chat />
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
                <Route
                  path="/debug/:sessionId"
                  element={
                    <ProtectedRoute>
                      <Debug />
                    </ProtectedRoute>
                  }
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
              </main>
            </div>
            <ConnectionStatus />
          </BrowserRouter>
        </ToastProvider>
      </AuthContext.Provider>
    </ErrorBoundary>
  )
}

export default App
