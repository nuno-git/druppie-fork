import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// Mock the api module before importing the page so the query uses our stub.
vi.mock('../services/api', () => ({
  branchEnvironmentsApi: {
    list: vi.fn(),
    deploy: vi.fn(),
    redeploy: vi.fn(),
    teardown: vi.fn(),
  },
}))

import BranchEnvironments, { slugifyBranch } from './BranchEnvironments'
import { branchEnvironmentsApi } from '../services/api'
import { ToastProvider } from '../components/Toast'

describe('slugifyBranch', () => {
  it('lowercases', () => {
    expect(slugifyBranch('MAIN')).toBe('main')
  })
  it('replaces non-alphanumeric with dashes and lowercases', () => {
    expect(slugifyBranch('feature/Foo_Bar')).toBe('feature-foo-bar')
  })
  it('collapses consecutive separators', () => {
    expect(slugifyBranch('a///b   c')).toBe('a-b-c')
  })
  it('trims leading and trailing dashes', () => {
    expect(slugifyBranch('/feature/')).toBe('feature')
  })
  it('strips weird characters', () => {
    expect(slugifyBranch('feat@#$%^&*()!')).toBe('feat')
  })
  it('returns empty string for empty input', () => {
    expect(slugifyBranch('')).toBe('')
  })
  it('returns empty string for null/undefined', () => {
    expect(slugifyBranch(null)).toBe('')
    expect(slugifyBranch(undefined)).toBe('')
  })
  it('preserves existing dashes without duplicating', () => {
    expect(slugifyBranch('feature/my-branch')).toBe('feature-my-branch')
  })
})

const renderPage = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <BranchEnvironments />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}

describe('BranchEnvironments page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders a running environment with its branch and Open link', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'env-1',
          branch: 'feature/awesome',
          slug: 'feature-awesome',
          namespace: 'druppie-feature-awesome',
          url: 'https://druppie-feature-awesome.rijnland.dev',
          image_tag: 'abc123',
          status: 'running',
          status_message: null,
          created_at: '2026-07-07T10:00:00Z',
        },
      ],
      total: 1,
    })

    renderPage()

    expect(await screen.findByText('feature/awesome')).toBeTruthy()
    const openLink = await screen.findByRole('link', { name: /open/i })
    expect(openLink.getAttribute('href')).toBe('https://druppie-feature-awesome.rijnland.dev')
  })
})
