/**
 * NavRail - 48px icon sidebar for app-wide navigation
 *
 * Replaces the top navbar. Shows logo, nav items with tooltips,
 * debug flyout, admin link, and user menu at the bottom.
 */

import React, { useState, useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Home,
  MessageSquare,
  CheckSquare,
  FolderOpen,
  Settings,
  Database,
  Shield,
  LogIn,
  LogOut,
  Wrench,
  Server,
  FlaskConical,
  Package,
  Boxes,
} from 'lucide-react'

import { useAuth } from '../App'
import { login, logout } from '../services/keycloak'
import { getTasks } from '../services/api'

// --- NavRail Item with tooltip ---

const NavRailItem = ({ to, icon: Icon, label, badge, active, accent }) => {
  const [showTooltip, setShowTooltip] = useState(false)

  const baseColor = accent || 'blue'
  const activeClasses = {
    blue: 'bg-gray-700 text-white before:bg-blue-400',
    orange: 'bg-gray-700 text-orange-400 before:bg-orange-400',
    purple: 'bg-gray-700 text-purple-400 before:bg-purple-400',
  }
  const hoverClasses = {
    blue: 'text-gray-400 hover:text-white hover:bg-gray-800',
    orange: 'text-orange-400/70 hover:text-orange-400 hover:bg-gray-800',
    purple: 'text-purple-400/70 hover:text-purple-400 hover:bg-gray-800',
  }

  return (
    <div className="relative flex justify-center">
      <Link
        to={to}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className={`relative w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
          active
            ? `${activeClasses[baseColor]} before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-5 before:rounded-r`
            : hoverClasses[baseColor]
        }`}
      >
        <Icon className="w-5 h-5" />
        {badge > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
            {badge > 9 ? '9+' : badge}
          </span>
        )}
      </Link>
      {showTooltip && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-50 pointer-events-none shadow-lg">
          {label}
        </div>
      )}
    </div>
  )
}

// --- User Menu ---

const UserMenu = ({ user, authenticated }) => {
  const [open, setOpen] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  if (!authenticated) {
    return (
      <div className="relative flex justify-center">
        <button
          onClick={login}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
          className="w-10 h-10 flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
        >
          <LogIn className="w-5 h-5" />
        </button>
        {showTooltip && (
          <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-50 pointer-events-none shadow-lg">
            Log in
          </div>
        )}
      </div>
    )
  }

  const initial = (user?.username || '?')[0].toUpperCase()

  return (
    <div className="relative flex justify-center" ref={ref}>
      <button
        onClick={() => { setOpen(!open); setShowTooltip(false) }}
        onMouseEnter={() => !open && setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
          open
            ? 'bg-blue-500 text-white ring-2 ring-blue-400'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
        }`}
      >
        {initial}
      </button>
      {showTooltip && !open && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-50 pointer-events-none shadow-lg">
          {user?.username}
        </div>
      )}
      {open && (
        <div className="absolute left-full ml-2 bottom-0 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-2 min-w-[180px] z-50">
          <div className="px-3 py-1.5 border-b border-gray-700">
            <div className="text-sm font-medium text-white">{user?.username}</div>
            {user?.roles?.includes('admin') && (
              <span className="inline-block mt-0.5 px-1.5 py-0.5 text-[10px] font-semibold bg-purple-500/30 text-purple-300 rounded">
                Admin
              </span>
            )}
          </div>
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
          >
            <Settings className="w-4 h-4" />
            Settings
          </Link>
          <button
            onClick={() => { setOpen(false); logout() }}
            className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}

// --- Main NavRail ---

const NavRail = () => {
  const { authenticated, user } = useAuth()
  const location = useLocation()

  const { data: tasksData } = useQuery({
    queryKey: ['pending-approvals-count'],
    queryFn: getTasks,
    enabled: authenticated,
    refetchInterval: 30000,
  })

  const pendingApprovalsCount = tasksData?.items?.length || 0

  const isActive = (path) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  return (
    <nav className="w-12 flex-shrink-0 bg-gray-900 flex flex-col items-center py-3 gap-1">
      {/* Logo (decorative — Dashboard icon below handles navigation) */}
      <div className="w-9 h-9 bg-blue-600 rounded-lg flex items-center justify-center mb-3">
        <Shield className="w-5 h-5 text-white" />
      </div>

      {/* Main nav */}
      <NavRailItem to="/" icon={Home} label="Dashboard" active={isActive('/')} />
      <NavRailItem to="/chat" icon={MessageSquare} label="Chat" active={isActive('/chat')} />
      <NavRailItem
        to="/tasks"
        icon={CheckSquare}
        label="Approvals"
        badge={pendingApprovalsCount}
        active={isActive('/tasks')}
      />
      <NavRailItem to="/projects" icon={FolderOpen} label="Projects" active={isActive('/projects')} />

      {/* Tools */}
      <div className="mt-1 pt-1 border-t border-gray-800 w-8" />
      <NavRailItem to="/tools/mcp" icon={Wrench} label="MCP Tools" active={isActive('/tools/mcp')} />
      <NavRailItem to="/tools/infrastructure" icon={Server} label="Infrastructure" active={isActive('/tools/infrastructure')} />
      <NavRailItem to="/tools/cache" icon={Package} label="Dep Cache" active={isActive('/tools/cache')} />

      {/* Admin */}
      {user?.roles?.includes('admin') && (
        <>
          <div className="mt-1 pt-1 border-t border-gray-800 w-8" />
          <NavRailItem
            to="/admin/platform"
            icon={Boxes}
            label="Platform"
            active={isActive('/admin/platform')}
            accent="purple"
          />
          <NavRailItem
            to="/admin/database"
            icon={Database}
            label="Database"
            active={isActive('/admin/database')}
            accent="purple"
          />
          <NavRailItem
            to="/admin/evaluations"
            icon={FlaskConical}
            label="Tests"
            active={isActive('/admin/evaluations')}
            accent="purple"
          />
        </>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* User */}
      <UserMenu user={user} authenticated={authenticated} />
    </nav>
  )
}

export default NavRail
