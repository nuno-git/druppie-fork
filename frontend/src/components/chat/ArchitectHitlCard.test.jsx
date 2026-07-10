import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ArchitectHitlCard from './ArchitectHitlCard'

vi.mock('../../services/api', () => ({
  submitArchitectHitl: vi.fn(),
  ARCHITECT_REJECT_NEXT: Object.freeze(['ba_hitl', 'terminate']),
}))

vi.mock('../../App', () => ({
  useAuth: () => ({ user: { id: 'user-arch', roles: ['architect'] } }),
}))

import { submitArchitectHitl } from '../../services/api'

const SESSION_ID = 'ses-456'

function renderWithClient(ui) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const baseSession = { user_id: 'user-owner' }

describe('ArchitectHitlCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    submitArchitectHitl.mockResolvedValue({ event: { id: 'e1' }, message: 'ok' })
  })

  it('does not expose next-on-reject choices until Reject is clicked', () => {
    renderWithClient(<ArchitectHitlCard sessionId={SESSION_ID} session={baseSession} />)
    expect(screen.queryByRole('button', { name: /back to ba review/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /terminate session/i })).toBeNull()
    expect(screen.getByRole('button', { name: /reject/i })).toBeDefined()
  })

  it('reveals the next-on-reject chooser after Reject is clicked and does not call the API yet', async () => {
    const user = userEvent.setup()
    renderWithClient(<ArchitectHitlCard sessionId={SESSION_ID} session={baseSession} />)

    await user.click(screen.getByRole('button', { name: /reject/i }))

    expect(screen.getByRole('button', { name: /back to ba review/i })).toBeDefined()
    expect(screen.getByRole('button', { name: /terminate session/i })).toBeDefined()
    expect(submitArchitectHitl).not.toHaveBeenCalled()
  })

  it('submits reject with next_on_reject=ba_hitl when Back to BA is chosen', async () => {
    const user = userEvent.setup()
    renderWithClient(<ArchitectHitlCard sessionId={SESSION_ID} session={baseSession} />)
    await user.click(screen.getByRole('button', { name: /reject/i }))
    await user.click(screen.getByRole('button', { name: /back to ba review/i }))

    await waitFor(() => {
      expect(submitArchitectHitl).toHaveBeenCalledWith(SESSION_ID, {
        decision: 'reject',
        next_on_reject: 'ba_hitl',
      })
    })
  })

  it('submits reject with next_on_reject=terminate when Terminate is chosen', async () => {
    const user = userEvent.setup()
    renderWithClient(<ArchitectHitlCard sessionId={SESSION_ID} session={baseSession} />)
    await user.click(screen.getByRole('button', { name: /reject/i }))
    await user.click(screen.getByRole('button', { name: /terminate session/i }))

    await waitFor(() => {
      expect(submitArchitectHitl).toHaveBeenCalledWith(SESSION_ID, {
        decision: 'reject',
        next_on_reject: 'terminate',
      })
    })
  })

  it('submits approve immediately', async () => {
    const user = userEvent.setup()
    renderWithClient(<ArchitectHitlCard sessionId={SESSION_ID} session={baseSession} />)
    await user.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() => {
      expect(submitArchitectHitl).toHaveBeenCalledWith(SESSION_ID, { decision: 'approve' })
    })
  })
})
