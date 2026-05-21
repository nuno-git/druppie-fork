#!/bin/sh
# Fetch bundle into a fresh bare clone, then push to the remote.
# The bundle's contents only ever exist as packfile blobs — nothing
# is checked out, no hooks run, no submodules are initialised.
set -eu

: "${REMOTE_URL:?REMOTE_URL is required}"
: "${BRANCH:?BRANCH is required}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"

BUNDLE="${BUNDLE_PATH:-/in/run.bundle}"
if [ ! -f "$BUNDLE" ]; then
  echo "bundle not found at $BUNDLE" >&2
  exit 1
fi

cd /tmp
# Fresh bare clone of the remote. No working tree, no hooks.
# Use --filter=blob:none for speed — we only need refs and trees for push.
git -c core.hooksPath=/dev/null \
    clone --bare --filter=blob:none "$REMOTE_URL" /tmp/remote.git 2>/tmp/clone.log \
  || (echo "clone failed:" >&2; cat /tmp/clone.log >&2; exit 1)

cd /tmp/remote.git

# Verify the bundle is well-formed against this repository's object graph.
# `git bundle verify` checks that prerequisite commits (if any) exist.
# It is pure data validation — never executes bundle contents.
git bundle verify "$BUNDLE" 2>/tmp/verify.log \
  || (echo "bundle verify failed:" >&2; cat /tmp/verify.log >&2; exit 1)

# Fetch objects and branch refs from the bundle into this bare repo.
# Fetch never runs hooks and never populates a working tree.
git -c core.hooksPath=/dev/null \
    fetch "$BUNDLE" "refs/heads/${BRANCH}:refs/heads/${BRANCH}"

# Push that single branch to the remote.
git -c core.hooksPath=/dev/null \
    push --no-verify origin "refs/heads/${BRANCH}:refs/heads/${BRANCH}"

echo "push: success branch=${BRANCH}"
