# Platform Functional Standards

**Revision:** 2026-04-20

Every Druppie-created application inherits these functional defaults. The
Business Analyst treats them as givens during elicitation and only writes
specific requirements into the FD when the user needs something different.

The user sees this file linked from every `functional-design.md`. If anything
here doesn't fit a project, the BA documents the deviation in the FD.

## 1. Language

- User-facing text, HITL questions, and the functional design document
  are written in the user's language by default. For Dutch public-sector
  work that means Dutch.
- Error messages, empty states, and confirmation dialogs follow the same
  language as the rest of the app.

## 2. Performance (user-visible)

- Pages load within **2 seconds** under normal conditions (home network,
  reasonable payload).
- Search / filter results appear within **2 seconds** for typical datasets.
- The app works acceptably for at least **25 concurrent users** without
  visible slowdown.

Projects only write NFRs for performance when they need stricter numbers
than these (e.g. realtime, sub-100ms) or when a specific operation has an
unusual cost profile.

## 3. Responsiveness & device support

- Works on desktop (≥1280px), tablet, and mobile (down to 320px wide).
- Touch-friendly tap targets on mobile.
- No horizontal scrolling on any supported width.

## 4. Accessibility

- Keyboard navigation works for every interactive element.
- Color contrast meets WCAG 2.1 AA for text.
- Every form field has an associated label.
- Focus states are visible.

The BA does not elicit accessibility requirements for every project — they
are a given. The BA only asks if the user has explicit extra needs (e.g.
screen-reader-only users, high-contrast mode).

## 5. Error behaviour (user-visible)

- When something fails, the app shows a clear, human-readable message in
  the user's language — never a stack trace, never an error code without
  explanation.
- On partial failure, the rest of the app stays usable.
- Destructive actions ask for confirmation.

## 6. Authentication (user experience)

- Users log in via the Druppie platform (Keycloak). The project itself
  does not show a login page, registration form, password-reset flow, or
  role-management UI.
- The BA does NOT elicit login/password/role-management requirements.
  If a user asks for project-specific identity features, the BA flags
  that as a platform-standard deviation for the Architect to evaluate.

## 7. Cost and usage (user experience)

- Apps do not show LLM/model cost, token usage, or spend information to
  users. Cost tracking is a platform concern.

## 8. Explicitly out of scope (functional)

These topics are platform-level and should NOT become FD requirements
unless the user explicitly wants a deviation:

- Login / signup / password reset screens
- User/role administration UI
- In-app billing or pricing pages
- Cost / token usage displays
- Notification preferences (platform handles notifications)
- GDPR data-export / right-to-be-forgotten flows (platform feature)

If the user wants one of these, document it in the FD under
*"Platform standard deviations"* with a short rationale — the Architect
will then build it explicitly.

## 9. Referencing this file in the FD

Every `functional-design.md` ends with a **Platform standards applied**
section linking back here with the revision the FD was written against:

> Platform standards applied: [docs/platform-functional-standards.md](./platform-functional-standards.md) rev 2026-04-20.
> Only deviations are listed below.

This keeps the user in the loop about what they're getting for free.
