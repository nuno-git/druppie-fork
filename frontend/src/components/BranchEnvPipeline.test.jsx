import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import BranchEnvPipeline from './BranchEnvPipeline'

const stage = (id, name, status, extra = {}) => ({
  id,
  name,
  status,
  message: null,
  detail: null,
  ...extra,
})

const DEPLOY_STAGES = [
  stage('commit', 'Commit (aigit)', 'done'),
  stage('flux', 'Flux sync', 'done'),
  stage('source', 'Chart source', 'done'),
  stage('secrets', 'Secrets (Vault)', 'busy', { detail: '2/3 secrets synced' }),
  stage('helm', 'Helm install', 'pending'),
  stage('workloads', 'Pods & images', 'pending'),
  stage('live', 'Live', 'pending'),
]

describe('BranchEnvPipeline', () => {
  it('renders a node per stage with its status', () => {
    render(<BranchEnvPipeline stages={DEPLOY_STAGES} />)
    DEPLOY_STAGES.forEach((s) => {
      const node = screen.getByTestId(`pipeline-stage-${s.id}`)
      expect(node.getAttribute('data-status')).toBe(s.status)
    })
    expect(screen.getByText('2/3 secrets synced')).toBeTruthy()
  })

  it('shows the failed stage message in a callout', () => {
    const stages = DEPLOY_STAGES.map((s) =>
      s.id === 'source'
        ? { ...s, status: 'failed', message: "couldn't find remote ref refs/heads/feature/foo" }
        : s
    )
    render(<BranchEnvPipeline stages={stages} />)
    expect(screen.getByTestId('pipeline-stage-source').getAttribute('data-status')).toBe('failed')
    expect(screen.getByText(/remote ref/)).toBeTruthy()
  })

  it('shows the busy stage message when nothing failed', () => {
    const stages = DEPLOY_STAGES.map((s) =>
      s.id === 'secrets'
        ? { ...s, message: 'waiting for ExternalSecrets to appear' }
        : s
    )
    render(<BranchEnvPipeline stages={stages} />)
    expect(screen.getByText(/waiting for ExternalSecrets/)).toBeTruthy()
  })

  it('renders a teardown pipeline (unknown stage ids fall back gracefully)', () => {
    render(
      <BranchEnvPipeline
        stages={[
          stage('commit-removed', 'Removed from GitOps repo', 'done'),
          stage('pruning', 'Flux pruning namespace', 'busy', {
            message: 'namespace is terminating',
          }),
        ]}
      />
    )
    expect(screen.getByTestId('pipeline-stage-commit-removed').getAttribute('data-status')).toBe(
      'done'
    )
    expect(screen.getByText(/namespace is terminating/)).toBeTruthy()
  })

  it('renders nothing without stages', () => {
    const { container } = render(<BranchEnvPipeline stages={[]} />)
    expect(container.innerHTML).toBe('')
  })
})
