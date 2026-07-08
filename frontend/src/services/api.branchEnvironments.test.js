import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Test the REAL api client (no module mock) — a page-level test with a mocked
// api module cannot catch the client dropping fields from the request body.
vi.mock('./keycloak', () => ({ getToken: () => null }))

import { branchEnvironmentsApi } from './api'

const okResponse = { ok: true, json: async () => ({}) }

describe('branchEnvironmentsApi.deploy request body', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue(okResponse)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const sentBody = () => JSON.parse(global.fetch.mock.calls[0][1].body)

  it('passes secrets_source through to the backend', async () => {
    await branchEnvironmentsApi.deploy({
      branch: 'feature/foo',
      secrets_source: 'developer',
    })
    expect(sentBody()).toEqual({ branch: 'feature/foo', secrets_source: 'developer' })
  })

  it('falls back to colab-dev with a console warning when secrets_source is missing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await branchEnvironmentsApi.deploy({ branch: 'feature/foo' })
    expect(sentBody().secrets_source).toBe('colab-dev')
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('falling back to "colab-dev"'))
  })

  it('includes image_tag only when set', async () => {
    await branchEnvironmentsApi.deploy({
      branch: 'feature/foo',
      image_tag: 'tag-1',
      secrets_source: 'colab-dev',
    })
    expect(sentBody().image_tag).toBe('tag-1')
  })
})

describe('branchEnvironmentsApi.pipeline', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue(okResponse)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('GETs the env pipeline with an encoded id', async () => {
    await branchEnvironmentsApi.pipeline('feature-foo')
    const [url, options] = global.fetch.mock.calls[0]
    expect(url).toContain('/api/branch-environments/feature-foo/pipeline')
    expect(options?.method).toBeUndefined()
  })
})
