# AGENTS.md

Whatever you build with — Claude Code, opencode, GLM, or your own hands — this repo has a
documentation standard. Read this before you write feature code, then follow the flow below.
The full details and templates live in
[`docs/guides/documentation-framework.md`](docs/guides/documentation-framework.md); this file
is just the entry point.

## The flow

```
PRD  →  Research?  →  ADR?  →  Spec  →  build
```

PRD first (what and why), Research only when the choice isn't obvious, ADR only for a new
decision worth remembering, Spec to pin the acceptance criteria — then build. A bugfix or
chore usually needs no docs.

## The four templated types

| Type | Captures | Where | Template |
|------|----------|-------|----------|
| **PRD** | The feature: problem + goal | `docs/prds/` | `docs/prds/TEMPLATE.md` |
| **Research** | Options considered + trade-offs (optional) | `docs/research/` | `docs/research/TEMPLATE.md` |
| **ADR** | The decision taken + its consequences | `docs/adrs/` | `docs/adrs/TEMPLATE.md` |
| **Spec** | Executable acceptance criteria (Gherkin) | `testing/specs/features/` | `testing/specs/features/TEMPLATE.feature` |

## The two orientation types (optional, no template)

- **Guide** — how-to / conventions / runbooks → `docs/guides/`
- **Reference** — subsystem & architecture naslag → `docs/reference/`

They carry no mandatory frontmatter and aren't schema-validated, but they should link back to
the ADR/PRD/Spec that owns the underlying decision or behaviour.

## The rule

If you change feature code, ship documentation with it — **unless** the PR is `docs-exempt`.
A PR is exempt via any of these three:

- the `docs-exempt` **label**,
- a checked `- [x] docs-exempt` checkbox in the PR body, or
- a `docs-exempt: <reason>` line in the PR body.

## Validate locally

```bash
docker compose --profile docs-validator run --rm docs-validator
```

Full details & templates: [`docs/guides/documentation-framework.md`](docs/guides/documentation-framework.md).
