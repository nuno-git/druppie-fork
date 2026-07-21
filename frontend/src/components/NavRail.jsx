/**
 * NavRail - 48px icon sidebar for app-wide navigation
 *
 * Replaces the top navbar. Shows logo, direct nav items, collapsible group
 * flyouts (Review / Tools / Deploy / Admin), and the user menu at the bottom.
 * Each group carries a logical accent color.
 */

import React, { useState, useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Home,
  MessageSquare,
  CheckSquare,
  CalendarClock,
  ClipboardCheck,
  FolderOpen,
  Settings,
  Shield,
  LogIn,
  LogOut,
  Wrench,
  Hammer,
  Server,
  FlaskConical,
  Package,
  BookOpen,
  Boxes,
  Rocket,
  Cpu,
  Terminal,
  HelpCircle,
  GitPullRequestArrow,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react'

import { useAuth } from '../App'
import { login, logout } from '../services/keycloak'
import { getTasks, getAvatarUrl, getPendingQuestions } from '../services/api'

// --- Accent color palette (logical per section) ---
// Full class strings so Tailwind keeps them at build time.
const ACCENTS = {
  blue: {
    active: 'bg-gray-700 text-white before:bg-blue-400',
    hover: 'text-gray-400 hover:text-white hover:bg-gray-800',
    text: 'text-blue-400',
    itemActive: 'bg-blue-500/10 text-blue-300',
    itemHover: 'text-gray-300 hover:bg-gray-700 hover:text-white',
  },
  amber: {
    active: 'bg-gray-700 text-amber-400 before:bg-amber-400',
    hover: 'text-amber-400/70 hover:text-amber-300 hover:bg-gray-800',
    text: 'text-amber-400',
    itemActive: 'bg-amber-500/10 text-amber-300',
    itemHover: 'text-gray-300 hover:bg-gray-700 hover:text-amber-200',
  },
  cyan: {
    active: 'bg-gray-700 text-cyan-400 before:bg-cyan-400',
    hover: 'text-cyan-400/70 hover:text-cyan-300 hover:bg-gray-800',
    text: 'text-cyan-400',
    itemActive: 'bg-cyan-500/10 text-cyan-300',
    itemHover: 'text-gray-300 hover:bg-gray-700 hover:text-cyan-200',
  },
  green: {
    active: 'bg-gray-700 text-green-400 before:bg-green-400',
    hover: 'text-green-400/70 hover:text-green-300 hover:bg-gray-800',
    text: 'text-green-400',
    itemActive: 'bg-green-500/10 text-green-300',
    itemHover: 'text-gray-300 hover:bg-gray-700 hover:text-green-200',
  },
  purple: {
    active: 'bg-gray-700 text-purple-400 before:bg-purple-400',
    hover: 'text-purple-400/70 hover:text-purple-400 hover:bg-gray-800',
    text: 'text-purple-400',
    itemActive: 'bg-purple-500/10 text-purple-300',
    itemHover: 'text-gray-300 hover:bg-gray-700 hover:text-purple-200',
  },
}

const Badge = ({ count }) =>
  count > 0 ? (
    <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
      {count > 9 ? '9+' : count}
    </span>
  ) : null

// --- NavRail Item with tooltip ---

const NavRailItem = ({ to, icon: Icon, label, badge, active, accent }) => {
  const [showTooltip, setShowTooltip] = useState(false)
  const A = ACCENTS[accent] || ACCENTS.blue

  return (
    <div className="relative flex justify-center">
      <Link
        to={to}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className={`relative w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
          active
            ? `${A.active} before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-5 before:rounded-r`
            : A.hover
        }`}
      >
        <Icon className="w-5 h-5" />
        <Badge count={badge} />
      </Link>
      {showTooltip && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-50 pointer-events-none shadow-lg">
          {label}
        </div>
      )}
    </div>
  )
}

// --- NavRail Group (click-to-toggle flyout) ---

const NavRailGroup = ({ icon: Icon, label, accent, items, open, onToggle, onClose, isActive }) => {
  const [showTooltip, setShowTooltip] = useState(false)
  const ref = useRef(null)
  const A = ACCENTS[accent] || ACCENTS.blue

  const groupActive = items.some((it) => isActive(it.to))
  const groupBadge = items.reduce((sum, it) => sum + (it.badge || 0), 0)

  // Close on outside click / Escape while open
  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open, onClose])

  return (
    <div className="relative flex justify-center" ref={ref}>
      <button
        onClick={() => { onToggle(); setShowTooltip(false) }}
        onMouseEnter={() => !open && setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={label}
        className={`relative w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
          open || groupActive
            ? `${A.active} before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-5 before:rounded-r`
            : A.hover
        }`}
      >
        <Icon className="w-5 h-5" />
        {!open && <Badge count={groupBadge} />}
        {/* small chevron affordance */}
        <ChevronRight className="absolute bottom-0 right-0 w-2.5 h-2.5 opacity-60" />
      </button>

      {showTooltip && !open && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-gray-800 text-white text-xs rounded whitespace-nowrap z-50 pointer-events-none shadow-lg">
          {label}
        </div>
      )}

      {open && (
        <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1.5 min-w-[190px] z-50">
          <div className={`px-3 pb-1.5 mb-1 border-b border-gray-700 text-[11px] font-semibold uppercase tracking-wide ${A.text}`}>
            {label}
          </div>
          {items.map((it) => {
            const ItemIcon = it.icon
            const active = isActive(it.to)
            return (
              <Link
                key={it.to}
                to={it.to}
                onClick={onClose}
                className={`relative flex items-center gap-2.5 mx-1 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                  active ? A.itemActive : A.itemHover
                }`}
              >
                <ItemIcon className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1 whitespace-nowrap">{it.label}</span>
                {it.badge > 0 && (
                  <span className="bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
                    {it.badge > 9 ? '9+' : it.badge}
                  </span>
                )}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

// --- User Menu ---

const UserMenu = ({ user, authenticated }) => {
  const [open, setOpen] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)
  const [avatarUrl, setAvatarUrl] = useState(null)
  const ref = useRef(null)

  useEffect(() => {
    if (!authenticated) { setAvatarUrl(null); return }
    let revoke = null
    let cancelled = false
    getAvatarUrl().then(url => {
      if (cancelled) return
      if (url) {
        setAvatarUrl(url)
        revoke = url
      } else {
        setAvatarUrl(null)
      }
    })
    return () => { cancelled = true; setAvatarUrl(null); if (revoke) URL.revokeObjectURL(revoke) }
  }, [authenticated, user?.id])

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
        className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold transition-colors overflow-hidden ${
          open
            ? 'ring-2 ring-blue-400'
            : 'hover:ring-2 hover:ring-gray-500'
        } ${avatarUrl ? '' : open ? 'bg-blue-500 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
      >
        {avatarUrl
          ? <img src={avatarUrl} alt="" className="w-full h-full object-cover" />
          : initial
        }
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
  const [openGroup, setOpenGroup] = useState(null)

  const { data: tasksData } = useQuery({
    queryKey: ['pending-approvals-count'],
    queryFn: getTasks,
    enabled: authenticated,
    refetchInterval: 30000,
  })

  const { data: questionsData } = useQuery({
    queryKey: ['pending-questions-count'],
    queryFn: getPendingQuestions,
    enabled: authenticated,
    refetchInterval: 30000,
  })

  const pendingApprovalsCount = tasksData?.items?.length || 0
  const pendingQuestionsCount = questionsData?.items?.length || 0

  const isActive = (path) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  const isAdmin = user?.roles?.includes('admin')
  const isDeveloper = user?.roles?.includes('developer') || isAdmin

  const toggleGroup = (key) => setOpenGroup((cur) => (cur === key ? null : key))
  const closeGroup = () => setOpenGroup(null)

  // --- Group definitions ---
  const reviewItems = [
    { to: '/tasks', icon: CheckSquare, label: 'Approvals', badge: pendingApprovalsCount },
    { to: '/questions', icon: HelpCircle, label: 'Questions', badge: pendingQuestionsCount },
  ]

  const toolsItems = [
    { to: '/tools/developer', icon: Terminal, label: 'Agent Test' },
    { to: '/tools/mcp', icon: Wrench, label: 'MCP Tools' },
    { to: '/tools/infrastructure', icon: Server, label: 'Infrastructure' },
    { to: '/tools/cache', icon: Package, label: 'Dep Cache' },
  ]

  const deployItems = [
    { to: '/deployments', icon: Rocket, label: 'Deployments' },
    ...(isDeveloper ? [{ to: '/branch-environments', icon: GitPullRequestArrow, label: 'Branch Environments' }] : []),
  ]

  const adminItems = [
    { to: '/jobs', icon: CalendarClock, label: 'Scheduled Jobs' },
    { to: '/admin/models', icon: Cpu, label: 'Models' },
    { to: '/admin/platform', icon: Boxes, label: 'Platform' },
    { to: '/admin/evaluations', icon: FlaskConical, label: 'Tests' },
  ]

  return (
    <nav className="w-12 flex-shrink-0 bg-gray-900 flex flex-col items-center py-3 gap-1">
      {/* Logo (decorative — Dashboard icon below handles navigation) */}
      <div className="w-9 h-9 bg-blue-600 rounded-lg flex items-center justify-center mb-3">
        <Shield className="w-5 h-5 text-white" />
      </div>

      {/* Direct, high-traffic destinations */}
      <NavRailItem to="/" icon={Home} label="Dashboard" active={isActive('/')} />
      <NavRailItem to="/chat" icon={MessageSquare} label="Chat" active={isActive('/chat')} />
      <NavRailItem to="/projects" icon={FolderOpen} label="Projects" active={isActive('/projects')} />

      {/* Grouped sections */}
      <div className="mt-1 pt-1 border-t border-gray-800 w-8" />
      <NavRailGroup
        icon={ClipboardCheck}
        label="Review"
        accent="amber"
        items={reviewItems}
        open={openGroup === 'review'}
        onToggle={() => toggleGroup('review')}
        onClose={closeGroup}
        isActive={isActive}
      />
      <NavRailGroup
        icon={Hammer}
        label="Tools"
        accent="cyan"
        items={toolsItems}
        open={openGroup === 'tools'}
        onToggle={() => toggleGroup('tools')}
        onClose={closeGroup}
        isActive={isActive}
      />
      <NavRailGroup
        icon={Rocket}
        label="Deploy"
        accent="green"
        items={deployItems}
        open={openGroup === 'deploy'}
        onToggle={() => toggleGroup('deploy')}
        onClose={closeGroup}
        isActive={isActive}
      />

      {/* Doc Portal */}
      <div className="mt-1 pt-1 border-t border-gray-800 w-8" />
      <NavRailItem to="/documentation" icon={BookOpen} label="Documentation Portal" active={isActive('/documentation')} />

      {/* Admin */}
      {isAdmin && (
        <>
          <div className="mt-1 pt-1 border-t border-gray-800 w-8" />
          <NavRailGroup
            icon={ShieldCheck}
            label="Admin"
            accent="purple"
            items={adminItems}
            open={openGroup === 'admin'}
            onToggle={() => toggleGroup('admin')}
            onClose={closeGroup}
            isActive={isActive}
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
