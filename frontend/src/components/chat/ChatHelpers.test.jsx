import { describe, it, expect } from 'vitest'
import { resolveRelativePath, rewriteRelativeLink } from './ChatHelpers'

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
