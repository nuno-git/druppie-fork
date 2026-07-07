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
    enableWorkspace: vi.fn(),
    disableWorkspace: vi.fn(),
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
          workspace_enabled: false,
          workspace_url: null,
          workspace_status: null,
        },
      ],
      total: 1,
    })

    renderPage()

    expect(await screen.findByText('feature/awesome')).toBeTruthy()
    const openLink = await screen.findByRole('link', { name: /^open$/i })
    expect(openLink.getAttribute('href')).toBe('https://druppie-feature-awesome.rijnland.dev')
  })

  it('renders the Open workspace link when the workspace is running', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'env-2',
          branch: 'feature/with-workspace',
          slug: 'feature-with-workspace',
          namespace: 'druppie-feature-with-workspace',
          url: 'https://druppie-feature-with-workspace.rijnland.dev',
          image_tag: 'abc123',
          status: 'running',
          status_message: null,
          created_at: '2026-07-07T10:00:00Z',
          workspace_enabled: true,
          workspace_url: 'https://druppie-feature-with-workspace-dev.rijnland.dev',
          workspace_status: 'running',
        },
      ],
      total: 1,
    })

    renderPage()

    const workspaceLink = await screen.findByRole('link', { name: /open workspace/i })
    expect(workspaceLink.getAttribute('href')).toBe(
      'https://druppie-feature-with-workspace-dev.rijnland.dev'
    )
  })

  it('renders the enable workspace button when the workspace is disabled', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'env-3',
          branch: 'feature/no-workspace',
          slug: 'feature-no-workspace',
          namespace: 'druppie-feature-no-workspace',
          url: 'https://druppie-feature-no-workspace.rijnland.dev',
          image_tag: 'abc123',
          status: 'running',
          status_message: null,
          created_at: '2026-07-07T10:00:00Z',
          workspace_enabled: false,
          workspace_url: null,
          workspace_status: null,
        },
      ],
      total: 1,
    })

    renderPage()

    const enableButton = await screen.findByRole('button', { name: /workspace aanzetten/i })
    expect(enableButton).toBeTruthy()
    expect(enableButton.disabled).toBe(false)
  })
})
