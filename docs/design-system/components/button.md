# Button

The Druppie frontend does not use a dedicated `<Button>` component. Instead, button styling is applied directly via Tailwind CSS utility classes on native `<button>` and `<Link>` elements. This page documents the established patterns.

> **Why no component?** The codebase has diverse button contexts (inline, card, modal, dark theme) that are better served by composable Tailwind classes than a prop-driven component. If the pattern count grows, a shared component may be extracted.

## Variants

### Primary (Green — Approval Actions)

Used for the single most important action in a context: approve, confirm, submit.

```jsx
<button className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2">
  Approve
</button>
```

**When to use:** The one approval/confirm action per card or page section.

### Primary (Blue — Navigation / Retry)

Used for primary navigation actions, retry buttons, and general confirmations.

```jsx
<button className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
  Try Again
</button>
```

**When to use:** Error retry, modal primary actions, "Create New" buttons.

### Secondary

Used for non-primary actions that still need visibility: cancel, view details, toggle.

```jsx
<button className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 rounded-lg transition-colors focus:outline-none">
  Cancel
</button>
```

**When to use:** Cancel buttons, secondary toggles, "Show more" links.

### Danger (Red — Destructive Actions)

Used for reject, delete, and other destructive operations.

```jsx
<button className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2">
  Confirm Reject
</button>
```

**When to use:** Reject, delete, remove — always paired with a confirmation step (e.g. expand to show reason input first).

### Ghost (Outlined)

Used for tertiary actions in dense UI areas.

```jsx
<button className="flex items-center gap-2 px-4 py-2 text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
  Contact Approver
</button>
```

**When to use:** Low-priority actions, "learn more" links, contact buttons.

### Dark Context (NavRail, Modals)

Buttons on dark backgrounds use inverted color logic.

```jsx
// NavRail icon button
<button className="w-10 h-10 flex items-center justify-center rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors">
  <Icon className="w-5 h-5" />
</button>

// Modal close button
<button className="p-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors">
  <X className="w-4 h-4" />
</button>
```

### Link-as-Button

For navigation actions that look like buttons:

```jsx
<Link className="inline-flex items-center px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors">
  Create Project
</Link>
```

## Sizes

| Size | Classes | When to use |
|------|---------|-------------|
| **Small** | `px-2 py-1 text-xs` | Dense lists, inline actions, metadata rows |
| **Medium (default)** | `px-3 py-1.5 text-sm` | Cards, forms, most UI contexts |
| **Large** | `px-4 py-2 text-sm` or `px-6 py-3 text-sm` | Page-level CTAs, error states, empty states |
| **Icon-only** | `w-10 h-10` (NavRail) or `p-1.5` (inline) | Toolbar actions, copy buttons, close buttons |

## States

### Default

No additional classes beyond the base variant classes.

### Hover

All buttons include `hover:` classes for background color shift:
- Filled: `hover:bg-{color}-700` (darker shade)
- Ghost/Outlined: `hover:bg-{color}-50` (light tint)
- Secondary: `hover:text-gray-700`, `hover:bg-gray-50`

### Active (Pressed)

Tailwind's `active:` is not explicitly used in the current codebase. The `transition-colors` utility provides visual feedback through the hover state change on press.

### Disabled

```jsx
disabled={isProcessing}
className="... disabled:opacity-50 disabled:cursor-not-allowed ..."
```

All interactive buttons must include `disabled:opacity-50 disabled:cursor-not-allowed` when they have a loading or processing state.

### Loading

Replace the button label with a spinner icon and disable the button:

```jsx
<button disabled={isProcessing} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg ...">
  {isProcessing ? (
    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
  ) : (
    <CheckCircle className="w-4 h-4" aria-hidden="true" />
  )}
  {isProcessing ? 'Processing...' : 'Approve'}
</button>
```

## Usage Rules

1. **Only one primary button visible per page section** — A card should have at most one green or blue filled button. All other actions are secondary (text-only) or ghost (outlined).

2. **Always include `focus:outline-none focus:ring-2 focus:ring-{color}-500 focus:ring-offset-2`** — Every interactive button must have a visible focus ring for keyboard accessibility.

3. **Always include `transition-colors`** — All buttons must animate color changes for perceived responsiveness.

4. **Destructive actions require confirmation** — Reject and delete buttons must not act on a single click. Show a confirmation step (e.g. expand reason input, or show "Are you sure?" prompt).

5. **Use `disabled` attribute, not CSS class** — Hide or disable buttons using the `disabled` HTML attribute combined with `disabled:opacity-50 disabled:cursor-not-allowed`.

6. **Icon + text buttons use `gap-1.5`** — When combining a Lucide icon with a text label, wrap in `flex items-center gap-1.5`.

7. **No `window.confirm()` or `window.alert()`** — Use the Toast system (`useToast()`) for notifications and in-UI confirmation flows.

## Code Examples

### Approval Action Pair (Approve + Reject)

```jsx
<div className="flex items-center gap-2" role="group" aria-label="Approval actions">
  <button
    onClick={() => onApprove(taskId)}
    disabled={isProcessing}
    className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
    aria-label="Approve task"
  >
    {isProcessing ? (
      <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
    ) : (
      <CheckCircle className="w-4 h-4" aria-hidden="true" />
    )}
    Approve
  </button>
  <button
    onClick={() => setShowReject(true)}
    className="px-3 py-1.5 text-sm text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors focus:outline-none"
    aria-label="Reject task"
  >
    Reject
  </button>
</div>
```

### Empty State Action

```jsx
<Link
  to="/projects/new"
  className="inline-flex items-center px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
>
  Create Project
</Link>
```

### Icon-only Copy Button

```jsx
<button
  onClick={handleCopy}
  className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
  aria-label={copied ? 'Copied' : 'Copy text'}
  title={copied ? 'Copied!' : 'Copy'}
>
  {copied ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
</button>
```

### Refresh / Secondary Action (Dark Context)

```jsx
<button
  onClick={() => refetch()}
  disabled={isFetching}
  className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-400 rounded hover:bg-gray-700 transition-colors disabled:opacity-50"
  title="Refresh logs"
>
  <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
  <span>Refresh</span>
</button>
```

## Accessibility

| Requirement | Implementation |
|------------|----------------|
| Focus indicator | `focus:outline-none focus:ring-2 focus:ring-{color}-500 focus:ring-offset-2` on every button |
| Label | `aria-label` on icon-only buttons; visible text serves as label on text buttons |
| Disabled state | HTML `disabled` attribute + `disabled:opacity-50 disabled:cursor-not-allowed` |
| Loading state | Spinner icon with `aria-hidden="true"` (decorative) + accessible label update |
| Button groups | `role="group"` with `aria-label` on the wrapper `<div>` |
| Error actions | `role="alert"` on error message containers, not on buttons themselves |
| Keyboard | All buttons are native `<button>` elements — keyboard interaction is automatic |
