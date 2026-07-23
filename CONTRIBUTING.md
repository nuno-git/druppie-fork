# Contributing

Thanks for contributing to Druppie. For setup, development commands, and how to run tests and
services, see the [README](README.md).

## Documentation

This repo has a documentation standard. The tool-agnostic entry point is
[`AGENTS.md`](AGENTS.md); the full details and templates live in
[`docs/guides/documentation-framework.md`](docs/guides/documentation-framework.md).

The core rule: **if your PR changes feature code, include documentation** (PRD / Research / ADR /
Spec, following the flow `PRD → Research? → ADR? → Spec → build`), **or mark the PR
`docs-exempt`** — via the `docs-exempt` label, a checked `- [x] docs-exempt` checkbox, or a
`docs-exempt: <reason>` line in the PR body.

Validate your docs locally before pushing:

```bash
docker compose --profile docs-validator run --rm docs-validator
```
