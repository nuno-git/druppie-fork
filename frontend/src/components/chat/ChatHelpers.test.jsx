import { describe, it, expect } from 'vitest'
import { resolveRelativePath, rewriteRelativeLink, extractOrderedItems, buildApprovalFileList } from './ChatHelpers'

describe('resolveRelativePath', () => {
  it('resolves ./foo.md against a docs/ source', () => {
    expect(resolveRelativePath('docs/functional-design.md', './foo.md')).toBe('docs/foo.md')
  })

  it('treats bare filename as relative to the source directory', () => {
    expect(resolveRelativePath('docs/functional-design.md', 'foo.md')).toBe('docs/foo.md')
  })

  it('walks ../ up one directory', () => {
    expect(resolveRelativePath('docs/a/b.md', '../foo.md')).toBe('docs/foo.md')
  })

  it('treats a leading slash as repo-root absolute', () => {
    expect(resolveRelativePath('docs/functional-design.md', '/foo.md')).toBe('foo.md')
  })

  it('returns href-only when the source is at repo root', () => {
    expect(resolveRelativePath('readme.md', './foo.md')).toBe('foo.md')
  })

  it('handles undefined source path as repo root', () => {
    expect(resolveRelativePath(undefined, 'foo.md')).toBe('foo.md')
  })

  it('walks multiple ../ segments', () => {
    expect(resolveRelativePath('docs/a/b/c.md', '../../foo.md')).toBe('docs/foo.md')
  })
})

describe('rewriteRelativeLink', () => {
  const repo = { repo_url: 'https://gitea.example.com/acme/app', default_branch: 'main' }

  it('rewrites a relative link to a Gitea src URL', () => {
    expect(rewriteRelativeLink('./platform-functional-standards.md', repo, 'docs/functional-design.md'))
      .toBe('https://gitea.example.com/acme/app/src/branch/main/docs/platform-functional-standards.md')
  })

  it('uses the project default branch when present', () => {
    const customRepo = { ...repo, default_branch: 'colab-dev' }
    expect(rewriteRelativeLink('./foo.md', customRepo, 'docs/fd.md'))
      .toBe('https://gitea.example.com/acme/app/src/branch/colab-dev/docs/foo.md')
  })

  it('falls back to main when default_branch is missing', () => {
    const repoNoBranch = { repo_url: 'https://gitea.example.com/acme/app' }
    expect(rewriteRelativeLink('./foo.md', repoNoBranch, 'docs/fd.md'))
      .toBe('https://gitea.example.com/acme/app/src/branch/main/docs/foo.md')
  })

  it('strips a trailing slash from repo_url', () => {
    const repoWithSlash = { repo_url: 'https://gitea.example.com/acme/app/', default_branch: 'main' }
    expect(rewriteRelativeLink('./foo.md', repoWithSlash, 'docs/fd.md'))
      .toBe('https://gitea.example.com/acme/app/src/branch/main/docs/foo.md')
  })

  it('returns null for external http(s) links', () => {
    expect(rewriteRelativeLink('https://example.com/x', repo, 'docs/fd.md')).toBeNull()
    expect(rewriteRelativeLink('http://example.com/x', repo, 'docs/fd.md')).toBeNull()
  })

  it('returns null for mailto, tel and anchors', () => {
    expect(rewriteRelativeLink('mailto:foo@bar.com', repo, 'docs/fd.md')).toBeNull()
    expect(rewriteRelativeLink('tel:+31123456789', repo, 'docs/fd.md')).toBeNull()
    expect(rewriteRelativeLink('#section', repo, 'docs/fd.md')).toBeNull()
  })

  it('returns null when no repo context is available', () => {
    expect(rewriteRelativeLink('./foo.md', null, 'docs/fd.md')).toBeNull()
    expect(rewriteRelativeLink('./foo.md', { repo_url: null }, 'docs/fd.md')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// extractOrderedItems
// ---------------------------------------------------------------------------

describe('extractOrderedItems', () => {
  const makeRun = (toolCalls) => ({
    agent_id: 'business_analyst',
    llm_calls: [{ tool_calls: toolCalls }],
  })

  it('skips HITL questions with pending status (translation in progress)', () => {
    const run = makeRun([
      { tool_name: 'hitl_ask_question', status: 'pending', arguments: { question: 'English?' } },
    ])
    expect(extractOrderedItems(run, false)).toEqual([])
  })

  it('includes HITL questions with waiting_answer status', () => {
    const tc = { tool_name: 'hitl_ask_question', status: 'waiting_answer', arguments: { question: 'Dutch?' } }
    const run = makeRun([tc])
    const items = extractOrderedItems(run, false)
    expect(items).toHaveLength(1)
    expect(items[0]).toEqual({ type: 'question', tc, agentId: 'business_analyst' })
  })

  it('includes HITL questions with completed status', () => {
    const tc = { tool_name: 'hitl_ask_multiple_choice_question', status: 'completed', arguments: {} }
    const run = makeRun([tc])
    expect(extractOrderedItems(run, false)).toHaveLength(1)
  })

  it('includes approvals when no following message', () => {
    const tc = { tool_name: 'submit_design_for_review', status: 'completed', approval: { status: 'approved' } }
    const run = makeRun([tc])
    const items = extractOrderedItems(run, false)
    expect(items).toHaveLength(1)
    expect(items[0].type).toBe('approval')
  })

  it('excludes approvals when there is a following message', () => {
    const tc = { tool_name: 'submit_design_for_review', status: 'completed', approval: { status: 'approved' } }
    const run = makeRun([tc])
    expect(extractOrderedItems(run, true)).toEqual([])
  })

  it('excludes pending approvals', () => {
    const tc = { tool_name: 'submit_design_for_review', status: 'waiting_approval', approval: { status: 'pending' } }
    const run = makeRun([tc])
    expect(extractOrderedItems(run, false)).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// buildApprovalFileList
// ---------------------------------------------------------------------------

describe('buildApprovalFileList', () => {
  it('returns null when no content is present', () => {
    expect(buildApprovalFileList({ path: 'docs/fd.md' })).toBeNull()
    expect(buildApprovalFileList({})).toBeNull()
  })

  it('returns single file for English-only design', () => {
    const files = buildApprovalFileList({
      path: 'docs/functional-design.md',
      content: '# Functional Design',
    })
    expect(files).toEqual([
      { path: 'docs/functional-design.md', content: '# Functional Design' },
    ])
  })

  it('returns only translated file when translation exists', () => {
    const files = buildApprovalFileList({
      path: 'docs/functional-design.md',
      content: '# Functional Design',
      translated_path: 'docs/functioneel-ontwerp.md',
      translated_content: '# Functioneel Ontwerp',
    })
    expect(files).toHaveLength(1)
    expect(files[0]).toEqual({
      path: 'docs/functioneel-ontwerp.md',
      content: '# Functioneel Ontwerp',
    })
  })

  it('ignores partial translation (content without path)', () => {
    const files = buildApprovalFileList({
      path: 'docs/functional-design.md',
      content: '# FD',
      translated_content: '# FO',
    })
    expect(files).toEqual([
      { path: 'docs/functional-design.md', content: '# FD' },
    ])
  })

  it('ignores partial translation (path without content)', () => {
    const files = buildApprovalFileList({
      path: 'docs/functional-design.md',
      content: '# FD',
      translated_path: 'docs/functioneel-ontwerp.md',
    })
    expect(files).toEqual([
      { path: 'docs/functional-design.md', content: '# FD' },
    ])
  })

  it('handles batch file writes', () => {
    const files = buildApprovalFileList({
      files: { 'a.md': 'aaa', 'b.md': 'bbb' },
    })
    expect(files).toHaveLength(2)
    expect(files[0]).toEqual({ path: 'a.md', content: 'aaa' })
    expect(files[1]).toEqual({ path: 'b.md', content: 'bbb' })
  })

  it('uses "file" as fallback path when path is missing', () => {
    const files = buildApprovalFileList({ content: 'hello' })
    expect(files).toEqual([{ path: 'file', content: 'hello' }])
  })
})
