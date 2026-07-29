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
    getPullRequest: vi.fn(),
    createPullRequest: vi.fn(),
    listBranches: vi.fn(),
  },
}))

// Mock useAuth so we can control the current user (owner / admin gating).
vi.mock('../App', () => ({
  useAuth: vi.fn(() => ({ user: null })),
}))

import BranchEnvironments, {
  slugifyBranch,
  mergeabilityRefetchInterval,
} from './BranchEnvironments'
import { branchEnvironmentsApi } from '../services/api'
import { useAuth } from '../App'
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

describe('mergeabilityRefetchInterval', () => {
  const openUnknown = { exists: true, state: 'open', mergeable: null }

  it('polls while Gitea is still computing mergeability of an open PR', () => {
    expect(mergeabilityRefetchInterval(openUnknown, 0)).toBe(5000)
    expect(mergeabilityRefetchInterval(openUnknown, 5)).toBe(5000)
  })

  it('caps polling once the poll limit is reached (no infinite 5s loop)', () => {
    // The cap is 12 — at/over it we must stop polling even if mergeable stays null.
    expect(mergeabilityRefetchInterval(openUnknown, 12)).toBe(false)
    expect(mergeabilityRefetchInterval(openUnknown, 50)).toBe(false)
  })

  it('does not poll once mergeability is resolved', () => {
    expect(mergeabilityRefetchInterval({ exists: true, state: 'open', mergeable: true }, 0)).toBe(false)
    expect(mergeabilityRefetchInterval({ exists: true, state: 'open', mergeable: false }, 0)).toBe(false)
  })

  it('does not poll for a non-open or non-existent PR', () => {
    expect(mergeabilityRefetchInterval({ exists: false }, 0)).toBe(false)
    expect(mergeabilityRefetchInterval({ exists: true, state: 'merged', mergeable: null }, 0)).toBe(false)
    expect(mergeabilityRefetchInterval(undefined, 0)).toBe(false)
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
    // Sensible defaults: no current user (non-owner) and a "no PR yet" status so
    // rendering a card never leaves the PR query unmocked.
    useAuth.mockReturnValue({ user: null })
    branchEnvironmentsApi.getPullRequest.mockResolvedValue({
      exists: false,
      base_branch: 'colab-dev',
    })
    branchEnvironmentsApi.listBranches.mockResolvedValue([])
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
    fireEvent.change(await screen.findByPlaceholderText(/type or select a branch name/i), {
      target: { value: 'feature/foo' },
    })
    fireEvent.submit(screen.getByRole('button', { name: /^deploy$/i }).closest('form'))

    await waitFor(() =>
      expect(branchEnvironmentsApi.deploy).toHaveBeenCalledWith({
        branch: 'feature/foo',
        image_tag: undefined,
        secrets_source: 'colab-dev',
        recovery_mode: false,
      })
    )
  })

  it('deploys with a developer secrets source when selected', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({ items: [], total: 0 })
    branchEnvironmentsApi.deploy.mockResolvedValue({})

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /deploy branch/i }))
    fireEvent.change(await screen.findByPlaceholderText(/type or select a branch name/i), {
      target: { value: 'feature/foo' },
    })
    fireEvent.click(screen.getByRole('radio', { name: /robbe/i }))
    fireEvent.submit(screen.getByRole('button', { name: /^deploy$/i }).closest('form'))

    await waitFor(() =>
      expect(branchEnvironmentsApi.deploy).toHaveBeenCalledWith(
        expect.objectContaining({ secrets_source: 'robbe' })
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

  it('cancels an in-flight deployment via the cancel button (teardown)', async () => {
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
      env_id: 'feature-busy',
      status: 'deploying',
      stages: [{ id: 'commit', name: 'Commit (aigit)', status: 'done', message: null, detail: null }],
    })
    branchEnvironmentsApi.teardown.mockResolvedValue({})
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderPage()

    fireEvent.click(
      await screen.findByRole('button', { name: /cancel deployment of feature\/busy/i })
    )
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('Cancel the deployment'))
    await waitFor(() => expect(branchEnvironmentsApi.teardown).toHaveBeenCalledWith('feature-busy'))
    // A deploying env has no delete (trash) button — cancel replaces it.
    expect(screen.queryByRole('button', { name: /^delete feature\/busy$/i })).toBeNull()
  })

  it('cancels an in-flight workspace deployment (disable workspace)', async () => {
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [
        {
          id: 'feature-ws',
          branch: 'feature/ws',
          slug: 'feature-ws',
          namespace: 'druppie-feature-ws',
          url: 'https://druppie-feature-ws.rijnland.dev',
          image_tag: 'abc123',
          status: 'running',
          status_message: null,
          created_at: '2026-07-07T10:00:00Z',
          workspace_enabled: true,
          workspace_url: 'https://druppie-feature-ws-dev.rijnland.dev',
          workspace_status: 'deploying',
        },
      ],
      total: 1,
    })
    branchEnvironmentsApi.disableWorkspace.mockResolvedValue({})
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderPage()

    fireEvent.click(
      await screen.findByRole('button', { name: /cancel workspace deployment for feature\/ws/i })
    )
    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('Cancel the workspace deployment')
    )
    await waitFor(() =>
      expect(branchEnvironmentsApi.disableWorkspace).toHaveBeenCalledWith('feature-ws')
    )
  })

  const runningEnv = (overrides = {}) => ({
    id: 'feature-pr',
    branch: 'feature/pr',
    slug: 'feature-pr',
    namespace: 'druppie-feature-pr',
    url: 'https://druppie-feature-pr.rijnland.dev',
    image_tag: 'abc123',
    status: 'running',
    status_message: null,
    created_at: '2026-07-07T10:00:00Z',
    workspace_enabled: false,
    workspace_url: null,
    workspace_status: null,
    owner_id: 'owner-123',
    ...overrides,
  })

  it('hides the "Pull request openen" button for a non-owner', async () => {
    useAuth.mockReturnValue({ user: { id: 'someone-else', roles: [] } })
    branchEnvironmentsApi.list.mockResolvedValue({ items: [runningEnv()], total: 1 })

    renderPage()

    await screen.findByText('feature/pr')
    expect(screen.queryByRole('button', { name: /pull request openen/i })).toBeNull()
    expect(await screen.findByText(/alleen de eigenaar/i)).toBeTruthy()
  })

  it('opens a pull request when the owner clicks the button', async () => {
    useAuth.mockReturnValue({ user: { id: 'owner-123', roles: [] } })
    branchEnvironmentsApi.list.mockResolvedValue({ items: [runningEnv()], total: 1 })
    branchEnvironmentsApi.createPullRequest.mockResolvedValue({
      exists: true,
      number: 42,
      url: 'https://gitea/pr/42',
    })

    renderPage()

    const btn = await screen.findByRole('button', { name: /pull request openen/i })
    // Wait until the PR-status query settles so the button is no longer disabled.
    await waitFor(() => expect(btn.disabled).toBe(false))
    fireEvent.click(btn)

    await waitFor(() =>
      expect(branchEnvironmentsApi.createPullRequest).toHaveBeenCalledWith('feature-pr')
    )
  })

  it('shows a branch-not-pushed message and disables the button on a 404 status', async () => {
    useAuth.mockReturnValue({ user: { id: 'owner-123', roles: [] } })
    branchEnvironmentsApi.list.mockResolvedValue({ items: [runningEnv()], total: 1 })
    branchEnvironmentsApi.getPullRequest.mockRejectedValue(
      Object.assign(new Error('not found'), { status: 404 })
    )

    renderPage()

    expect(await screen.findByText(/branch nog niet gepusht/i)).toBeTruthy()
    const btn = screen.getByRole('button', { name: /pull request openen/i })
    expect(btn.disabled).toBe(true)
  })

  it('does not retry the PR-status query on a 404 (no per-card retry storm)', async () => {
    useAuth.mockReturnValue({ user: { id: 'owner-123', roles: [] } })
    branchEnvironmentsApi.list.mockResolvedValue({ items: [runningEnv()], total: 1 })
    branchEnvironmentsApi.getPullRequest.mockRejectedValue(
      Object.assign(new Error('not found'), { status: 404 })
    )

    // Use a client whose defaults WOULD retry (3x, immediately) — the query's own
    // retry opt-out must win so an expected 404 settles after a single call.
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: 3, retryDelay: 0 } },
    })
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter>
            <BranchEnvironments />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    )

    expect(await screen.findByText(/branch nog niet gepusht/i)).toBeTruthy()
    // A single call — no 3× exponential-backoff retry storm on the expected 404.
    expect(branchEnvironmentsApi.getPullRequest).toHaveBeenCalledTimes(1)
  })

  it('disables the "Pull request openen" button for a deleting environment', async () => {
    useAuth.mockReturnValue({ user: { id: 'owner-123', roles: [] } })
    branchEnvironmentsApi.list.mockResolvedValue({
      items: [runningEnv({ status: 'deleting' })],
      total: 1,
    })

    renderPage()

    await screen.findByText('feature/pr')
    const btn = screen.getByRole('button', { name: /pull request openen/i })
    expect(btn.disabled).toBe(true)
    // The PR endpoint 404s for a terminating env, so we never even query it.
    expect(branchEnvironmentsApi.getPullRequest).not.toHaveBeenCalled()
  })
})
