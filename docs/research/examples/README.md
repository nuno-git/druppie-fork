# CI artifact samples (Part F)

These are **reference samples** for the "Continuous documentation & PR enforcement"
section (Part F) of [../documentation-standards.md](../documentation-standards.md).
They live here, under `docs/research/examples/`, deliberately **not** in `.github/`,
so that they do not silently enable a gate before the team has agreed to it.

## How to activate

1. Move `deploy-docs.yml` into `.github/workflows/`.
2. Move `docs-required.yml` into `.github/workflows/`.
3. Move `pull_request_template.md` into `.github/`.
4. Make the `docs-required` job a **required status check** via branch protection
   on `colab-dev`.

## Sample files

- `deploy-docs.yml` — auto-publishes the docs site to GitHub Pages on every push to `colab-dev`.
- `docs-required.yml` — mandatory-documentation gate that runs on every pull request.
- `pull_request_template.md` — PR template with the documentation checklist.

## Not built by this spike

`scripts/generate_index.py`, `scripts/validate_adr_status.py` and
`scripts/validate_doc_links.py` are referenced by these samples but are **not**
built by this spike. The validators exist in draft PR #277.
