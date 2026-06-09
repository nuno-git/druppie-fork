# Druppie Design System

This document describes the visual and interaction design system for the Druppie governance platform frontend. It is the single source of truth for component patterns, styling conventions, and usage rules.

## Overview

The Druppie frontend is a single-page application built with React 18, styled exclusively with Tailwind CSS utility classes. There are no separate CSS component libraries — every visual element is composed from Tailwind primitives guided by a shared color system defined in `frontend/src/index.css`.

This design system covers:
- **Tech stack** and version constraints
- **Design principles** that guide all UI decisions
- **Component catalog** mapping every shared component to its source file
- **Visual rules** for color, typography, spacing, and iconography
- **Usage rules** and constraints for consistent implementation
- **Process** for adding new components

## Tech Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| React | 18.2 | UI framework |
| Vite | 5.0 | Build tool and dev server |
| Tailwind CSS | 3.4 | Utility-first styling (no custom theme extensions) |
| Zustand | 4.4 | Client-side state management |
| TanStack React Query | 5.17 | Server state, caching, background refetch |
| React Router DOM | 6.21 | Client-side routing |
| Lucide React | 0.303 | Icon library |
| Prism.js | 1.30 | Syntax highlighting in code blocks |
| Recharts | 2.15 | Chart rendering (bar, line, area, pie, scatter, treemap, funnel) |
| Mermaid | 11.13 | Diagram rendering (lazy-loaded) |
| Keycloak JS | 23.0 | Authentication (OIDC) |
| DOMPurify | 3.4 | HTML sanitization |
| react-markdown + remark-gfm | 10.1 / 4.0 | Markdown rendering |

### Dev & Test

| Technology | Version | Purpose |
|-----------|---------|---------|
| Vitest | 1.1 | Unit testing |
| Testing Library | 16.3 | React component testing |
| Playwright | 1.40 | End-to-end testing |
| ESLint | 8.55 | Linting |

## Design Principles

1. **Consistency over creativity** — Every page uses the same layout patterns (48px NavRail sidebar, PageHeader, card grids). Deviate only when the UX clearly demands it.

2. **Accessible by default** — Interactive elements have visible focus rings (`focus:ring-2 focus:ring-blue-500`), buttons use `aria-label` attributes, error states use `role="alert"`, and modals trap focus and close on Escape.

3. **Simplicity through utility classes** — No custom CSS classes except for Markdown rendering (`.markdown-content`) and animation keyframes (`.animate-slide-in`). All styling is Tailwind utilities applied directly in JSX.

4. **Progressive disclosure** — Show essential information first, reveal details on interaction. Examples: file previews open in modals, raw/diagram toggle on MermaidBlock, reject reason input expands on demand.

5. **Skeleton loading states** — Never show empty space during data fetches. Every data-driven component has a corresponding Skeleton variant (see `components/shared/Skeleton.jsx`).

## Component Catalog

### Layout Components

| Component | Category | File | Status |
|-----------|----------|------|--------|
| NavRail | Navigation | `src/components/NavRail.jsx` | Stable |
| NavRailItem | Navigation | `src/components/NavRail.jsx` (internal) | Stable |
| UserMenu | Navigation | `src/components/NavRail.jsx` (internal) | Stable |
| PageHeader | Layout | `src/components/shared/PageHeader.jsx` | Stable |

### Data Display Components

| Component | Category | File | Status |
|-----------|----------|------|--------|
| CodeBlock | Content | `src/components/CodeBlock.jsx` | Stable |
| ChartBlock | Content | `src/components/ChartBlock.jsx` | Stable |
| MermaidBlock | Content | `src/components/MermaidBlock.jsx` | Stable |
| EmptyState | Feedback | `src/components/shared/EmptyState.jsx` | Stable |
| CopyButton | Action | `src/components/shared/CopyButton.jsx` | Stable |

### Feedback Components

| Component | Category | File | Status |
|-----------|----------|------|--------|
| Toast / ToastProvider | Notification | `src/components/Toast.jsx` | Stable |
| ErrorBoundary | Error Handling | `src/components/ErrorBoundary.jsx` | Stable |
| ErrorMessage | Error Handling | `src/components/ErrorBoundary.jsx` | Stable |

### Loading Components

| Component | Category | File | Status |
|-----------|----------|------|--------|
| SkeletonLine | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonCard | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonStatCard | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonProjectCard | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonListItem | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonTaskCard | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonSidebarItem | Loading | `src/components/shared/Skeleton.jsx` | Stable |
| SkeletonSettingsSection | Loading | `src/components/shared/Skeleton.jsx` | Stable |

### Chat Components

| Component | Category | File | Status |
|-----------|----------|------|--------|
| ApprovalCard | Approval | `src/components/chat/ApprovalCard.jsx` | Stable |
| SessionDetail | Session | `src/components/chat/SessionDetail.jsx` | Stable |
| SessionSidebar | Navigation | `src/components/chat/SessionSidebar.jsx` | Stable |
| NewSessionPanel | Session | `src/components/chat/NewSessionPanel.jsx` | Stable |
| WorkflowPipeline | Visualization | `src/components/chat/WorkflowPipeline.jsx` | Stable |
| ToolDecisionCard | Tool Output | `src/components/chat/ToolDecisionCard.jsx` | Stable |
| HITLQuestionMessage | HITL | `src/components/chat/HITLQuestionMessage.jsx` | Stable |
| FileReviewCard | Review | `src/components/chat/FileReviewCard.jsx` | Stable |
| TestResultCard | Testing | `src/components/chat/TestResultCard.jsx` | Stable |
| AnnotationBar | Annotation | `src/components/chat/AnnotationBar.jsx` | Stable |
| AnnotationDetail | Annotation | `src/components/chat/AnnotationDetail.jsx` | Stable |
| SurfacedFileCard | File Display | `src/components/chat/SurfacedFileCard.jsx` | Stable |
| DownloadMenu | Download | `src/components/chat/DownloadMenu.jsx` | Stable |
| DependencyInstallCard | Dependency | `src/components/chat/DependencyInstallCard.jsx` | Stable |
| DebugEventLog | Debug | `src/components/chat/DebugEventLog.jsx` | Stable |
| SandboxEventCard | Sandbox | `src/components/chat/SandboxEventCard.jsx` | Stable |
| ContainerLogsModal | Debug | `src/components/shared/ContainerLogsModal.jsx` | Stable |

### Pages

| Page | Route | File |
|------|-------|------|
| Dashboard | `/` | `src/pages/Dashboard.jsx` |
| Chat | `/chat` | `src/pages/Chat.jsx` |
| Approvals (Tasks) | `/tasks` | `src/pages/Tasks.jsx` |
| Projects | `/projects` | `src/pages/Projects.jsx` |
| Project Detail | `/projects/:id` | `src/pages/ProjectDetail.jsx` |
| Batch Detail | `/batches/:id` | `src/pages/BatchDetail.jsx` |
| Plans | `/plans` | `src/pages/Plans.jsx` |
| Analytics | `/analytics` | `src/pages/Analytics.jsx` |
| Settings | `/settings` | `src/pages/Settings.jsx` |
| Documentation Portal | `/documentation` | `src/pages/Documentation.jsx` |
| MCP Tools | `/tools/mcp` | `src/pages/DebugMCP.jsx` |
| Infrastructure | `/tools/infrastructure` | `src/pages/DebugProjects.jsx` |
| Dependency Cache | `/tools/cache` | `src/pages/CachedDependencies.jsx` |
| Platform Admin | `/admin/platform` | `src/pages/Platform.jsx` |
| Evaluations Admin | `/admin/evaluations` | `src/pages/Evaluations.jsx` |
| Test Runner | `/admin/evaluations/:id` | `src/pages/evaluations/TestRunner.jsx` |
| Test Run Detail | `/admin/evaluations/run/:id` | `src/pages/evaluations/TestRunDetail.jsx` |
| Test Results | `/admin/evaluations/results` | `src/pages/evaluations/TestResults.jsx` |

## Visual Rules

### Color System

Colors are defined as CSS custom properties in `frontend/src/index.css` and used via Tailwind utilities:

| Token | Value | Tailwind Usage | Purpose |
|-------|-------|----------------|---------|
| `--primary` | `#2563eb` | `text-blue-600`, `bg-blue-600` | Primary actions, links, active states |
| `--primary-dark` | `#1d4ed8` | `bg-blue-700` | Primary hover states |
| `--secondary` | `#64748b` | `text-gray-500` | Secondary text, muted elements |
| `--success` | `#22c55e` | `text-green-500`, `bg-green-600` | Success states, approve actions |
| `--warning` | `#f59e0b` | `text-amber-500`, `bg-amber-50` | Warnings, pending states |
| `--danger` | `#ef4444` | `text-red-500`, `bg-red-600` | Error states, reject actions |

**Background layers:**
- Page background: `bg-gray-50`
- Card surface: `bg-white` with `border border-gray-100` or `border-gray-200`
- Dark surfaces (modals, nav): `bg-gray-900` with `bg-gray-800` for nested elements
- Hover elevation: `hover:bg-gray-50` or `hover:bg-gray-100`

**NavRail accent colors:**
- Default (blue): `text-blue-400` / `bg-blue-600`
- Tools (orange): `text-orange-400` / `hover:text-orange-400`
- Admin (purple): `text-purple-400` / `bg-purple-500/30`

### Typography

- **Font stack:** `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` (system font, no web fonts)
- **Monospace:** `'Fira Code', Consolas, Monaco, Andale Mono, Ubuntu Mono, monospace` (code blocks)
- **Headings:** `text-2xl font-bold` (h1), `text-xl font-bold` (h2), `text-base font-semibold` (h3)
- **Body text:** `text-sm` is the default. `text-xs` for metadata. `text-base` only for long-form content.
- **Markdown content:** Styled via `.markdown-content` CSS class in `index.css`.

### Spacing

- **NavRail width:** `w-12` (48px)
- **Card padding:** `p-4` to `p-6`
- **Section gaps:** `gap-1` to `gap-3` depending on density
- **Page margins:** Handled by individual page layouts, typically `p-6`
- **Border radius:** `rounded-lg` for cards and buttons, `rounded-xl` for stat cards, `rounded-full` for avatars and badges

### Iconography

- **Library:** Lucide React (all icons)
- **Default size:** `w-5 h-5` for interactive icons, `w-4 h-4` for inline/metadata icons
- **Muted icons:** `text-gray-400` default, `text-gray-500` on slightly more prominent contexts
- **No custom SVG icons** — if Lucide doesn't have it, use a text label instead

## Usage Rules

1. **No inline styles** — Exception: dynamic values that cannot be expressed with Tailwind (e.g. `width: min(1100px, 95vw)` in modals, `transform` calculations). All other styling must use Tailwind utilities.

2. **No custom Tailwind theme extensions** — The `tailwind.config.js` has an empty `theme.extend`. Use Tailwind's built-in color and spacing scales.

3. **Only one primary action per context** — Each page or card should have at most one visually prominent action (blue-600 / green-600). Secondary actions use `text-gray-500` or outlined styles.

4. **Always use `PageHeader` for page titles** — Do not create custom heading layouts. Use `PageHeader` with optional `subtitle` and `children` (action buttons).

5. **Always use `EmptyState` for empty data** — Pass an icon, title, description, and optional action. Do not create ad-hoc empty states.

6. **Always use Skeleton components during loading** — Never show blank areas. Map each data component to its corresponding Skeleton variant.

7. **Modal close on Escape** — All modals must register an Escape key listener. See `ContainerLogsModal` or `FilePreviewModal` for the pattern.

8. **Toast for transient feedback** — Use `useToast()` hook for success/error notifications. Never use `window.alert()`.

9. **Error states via `ErrorMessage`** — Use the `ErrorMessage` component from `ErrorBoundary.jsx` for inline fetch errors. Wrap page-level boundaries with `ErrorBoundary`.

10. **Icons from Lucide only** — Import only what you need. Never add another icon library.

## Adding New Components

1. **Choose the right location:**
   - `src/components/shared/` — Reusable across pages (buttons, inputs, cards, modals)
   - `src/components/chat/` — Specific to the Chat/Session workflow
   - `src/components/` (root) — Top-level components (NavRail, ErrorBoundary, Toast)

2. **Create the file** following existing patterns:
   ```jsx
   /**
    * ComponentName - One-line description of what it does
    *
    * Optional: longer description of behavior, edge cases, or usage notes.
    */

   import React from 'react'
   // ...imports

   const ComponentName = ({ prop1, prop2 }) => (
     // JSX with Tailwind classes
   )

   export default ComponentName
   ```

3. **Use Tailwind utilities exclusively** — Apply spacing, colors, and typography via classes. Reference the color system above.

4. **Add accessibility attributes** — `aria-label` on interactive elements, `role="alert"` on errors, `role="group"` on button groups.

5. **Add a corresponding Skeleton** — If the component renders fetched data, add a Skeleton variant to `src/components/shared/Skeleton.jsx`.

6. **Update this catalog** — Add the new component to the table above with its category, file path, and status (`Stable` or `Draft`).

7. **Write tests** — At minimum, a render test in `tests/` verifying the component mounts without errors.

## Enforcement

| Mechanism | What it checks | When |
|-----------|---------------|------|
| ESLint (`eslint-plugin-react`) | Missing keys, unused vars, hook rules | `npm run lint` and pre-push |
| ESLint (`eslint-plugin-react-hooks`) | Hook dependency arrays | `npm run lint` |
| Tailwind Purge (Vite) | Removes unused CSS classes in production builds | `npm run build` |
| Playwright E2E | Critical user flows (login, chat, approvals) | `npm run test:e2e` |
| Vitest unit tests | Component rendering and utility logic | `npm test` |
| PR review | Design system adherence, accessibility, new component placement | Every PR |
