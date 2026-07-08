import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

// Mock the api module before importing the page so the query uses our stub.
vi.mock('../services/api', () => ({
  branchEnvironmentsApi: {
    list: vi.fn(),
    deploy: vi.fn(),
    pipeline: vi.fn(),
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

  it('deploys with the colab-dev secrets source by default', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({ items: [], total: 0 })
    branchEnvironmentsApi.deploy.mockResolvedValue({})

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /deploy branch/i }))
    fireEvent.change(screen.getByPlaceholderText('feature/my-branch'), {
      target: { value: 'feature/foo' },
    })
    fireEvent.submit(screen.getByRole('button', { name: /^deploy$/i }).closest('form'))

    await waitFor(() =>
      expect(branchEnvironmentsApi.deploy).toHaveBeenCalledWith({
        branch: 'feature/foo',
        image_tag: undefined,
        secrets_source: 'colab-dev',
      })
    )
  })

  it('deploys with the developer secrets source when selected', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({ items: [], total: 0 })
    branchEnvironmentsApi.deploy.mockResolvedValue({})

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /deploy branch/i }))
    fireEvent.change(screen.getByPlaceholderText('feature/my-branch'), {
      target: { value: 'feature/foo' },
    })
    fireEvent.click(screen.getByRole('radio', { name: /my developer vault map/i }))
    fireEvent.submit(screen.getByRole('button', { name: /^deploy$/i }).closest('form'))

    await waitFor(() =>
      expect(branchEnvironmentsApi.deploy).toHaveBeenCalledWith(
        expect.objectContaining({ secrets_source: 'developer' })
      )
    )
  })

  it('auto-opens the deploy pipeline for a deploying environment', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'feature-busy',
          branch: 'feature/busy',
          slug: 'feature-busy',
          namespace: 'druppie-feature-busy',
          url: 'https://druppie-feature-busy.rijnland.dev',
          image_tag: null,
          status: 'deploying',
          status_message: 'helm release reconciling',
          created_at: '2026-07-07T10:00:00Z',
          workspace_enabled: false,
          workspace_url: null,
          workspace_status: null,
        },
      ],
      total: 1,
    })
    branchEnvironmentsApi.pipeline.mockResolvedValue({
      env_id: 'feature-busy',
      status: 'deploying',
      stages: [
        { id: 'commit', name: 'Commit (aigit)', status: 'done', message: null, detail: null },
        { id: 'flux', name: 'Flux sync', status: 'done', message: null, detail: null },
        { id: 'source', name: 'Chart source', status: 'done', message: null, detail: null },
        { id: 'secrets', name: 'Secrets (Vault)', status: 'done', message: null, detail: null },
        {
          id: 'helm',
          name: 'Helm install',
          status: 'busy',
          message: 'helm release reconciling',
          detail: null,
        },
        { id: 'workloads', name: 'Pods & images', status: 'pending', message: null, detail: null },
        { id: 'live', name: 'Live', status: 'pending', message: null, detail: null },
      ],
    })

    renderPage()

    expect(await screen.findByTestId('branch-env-pipeline')).toBeTruthy()
    expect(branchEnvironmentsApi.pipeline).toHaveBeenCalledWith('feature-busy')
    expect(screen.getByTestId('pipeline-stage-helm').getAttribute('data-status')).toBe('busy')
  })

  it('does not fetch the pipeline for a running environment until expanded', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'feature-ok',
          branch: 'feature/ok',
          slug: 'feature-ok',
          namespace: 'druppie-feature-ok',
          url: 'https://druppie-feature-ok.rijnland.dev',
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
    branchEnvironmentsApi.pipeline.mockResolvedValue({
      env_id: 'feature-ok',
      status: 'running',
      stages: [{ id: 'commit', name: 'Commit (aigit)', status: 'done', message: null, detail: null }],
    })

    renderPage()

    await screen.findByText('feature/ok')
    expect(branchEnvironmentsApi.pipeline).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /pipeline/i }))
    expect(await screen.findByTestId('branch-env-pipeline')).toBeTruthy()
    expect(branchEnvironmentsApi.pipeline).toHaveBeenCalledWith('feature-ok')
  })
})
