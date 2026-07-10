import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BAHitlCard from './BAHitlCard'

vi.mock('../../services/api', () => ({
  submitBaHitl: vi.fn(),
}))

vi.mock('../../App', () => ({
  useAuth: () => ({ user: { id: 'user-admin', roles: ['admin'] } }),
}))

import { submitBaHitl } from '../../services/api'

const SESSION_ID = 'ses-123'

function renderWithClient(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const baseSession = {
  user_id: 'user-admin',
  fd_post_hitl_rejection_count: 0,
  fd_escalation_mode: false,
}

describe('BAHitlCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    submitBaHitl.mockResolvedValue({ event: { id: 'e1' }, message: 'ok' })
  })

  it('disables the Escalate button when there have been zero post-HITL rejections', () => {
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={{ ...baseSession, fd_post_hitl_rejection_count: 0 }} />)
    const escalate = screen.getByRole('button', { name: /escalate/i })
    expect(escalate.disabled).toBe(true)
  })

  it('enables the Escalate button once fd_post_hitl_rejection_count >= 1', () => {
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={{ ...baseSession, fd_post_hitl_rejection_count: 1 }} />)
    const escalate = screen.getByRole('button', { name: /escalate/i })
    expect(escalate.disabled).toBe(false)
  })

  it('shows the feedback textarea when Iterate is clicked and submits the feedback', async () => {
    const user = userEvent.setup()
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={baseSession} />)

    // Feedback textarea is absent until Iterate is clicked
    expect(screen.queryByLabelText(/ba iteration feedback/i)).toBeNull()

    await user.click(screen.getByRole('button', { name: /iterate/i }))

    const textarea = await screen.findByLabelText(/ba iteration feedback/i)
    await user.type(textarea, 'Please clarify the data model')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(submitBaHitl).toHaveBeenCalledWith(SESSION_ID, {
        decision: 'iterate',
        feedback: 'Please clarify the data model',
      })
    })
  })

  it('does not submit Iterate when the feedback is empty', async () => {
    const user = userEvent.setup()
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={baseSession} />)
    await user.click(screen.getByRole('button', { name: /iterate/i }))
    expect(screen.getByRole('button', { name: /^send$/i }).disabled).toBe(true)
  })

  it('requires a confirm step before submitting Terminate', async () => {
    const user = userEvent.setup()
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={baseSession} />)

    // No confirm button initially
    expect(screen.queryByRole('button', { name: /confirm terminate/i })).toBeNull()

    await user.click(screen.getByRole('button', { name: /terminate/i }))
    expect(screen.getByRole('button', { name: /confirm terminate/i })).toBeDefined()

    await user.click(screen.getByRole('button', { name: /confirm terminate/i }))
    await waitFor(() => {
      expect(submitBaHitl).toHaveBeenCalledWith(SESSION_ID, { decision: 'terminate' })
    })
  })

  it('submits Ready with no feedback', async () => {
    const user = userEvent.setup()
    renderWithClient(<BAHitlCard sessionId={SESSION_ID} session={baseSession} />)
    await user.click(screen.getByRole('button', { name: /ready/i }))
    await waitFor(() => {
      expect(submitBaHitl).toHaveBeenCalledWith(SESSION_ID, { decision: 'ready' })
    })
  })
})
