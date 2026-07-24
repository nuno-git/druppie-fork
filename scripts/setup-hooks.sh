#!/usr/bin/env bash
#
# setup-hooks.sh — OPTIONAL, opt-in installer for the local lefthook pre-commit hook.
#
# The lefthook hook only gives fast LOCAL feedback (it runs the docs-validator
# before a commit that touches docs). It is NOT the binding gate: CI
# (.github/workflows/docs.yml) is what actually enforces the documentation
# standard on every PR. Installing this is entirely optional.
#
# This script is idempotent — running it again is safe.

set -euo pipefail

if ! command -v lefthook >/dev/null 2>&1; then
  echo "lefthook binary not found."
  echo
  echo "Install it (one-time), then re-run this script:"
  echo "  Linux : go install github.com/evilmartians/lefthook@latest"
  echo "          (or download a release binary from"
  echo "           https://github.com/evilmartians/lefthook/releases)"
  echo "  macOS : brew install lefthook"
  echo
  echo "This is optional — CI (.github/workflows/docs.yml) remains the binding gate."
  exit 0
fi

# Install (or re-install) the git hooks. Safe to run repeatedly.
lefthook install

echo
echo "Local lefthook hooks installed. This is optional convenience only;"
echo "CI (.github/workflows/docs.yml) remains the binding gate."
