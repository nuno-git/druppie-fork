#!/bin/sh
# Git askpass helper — returns username or password for HTTPS auth.
# Git calls this with a prompt like "Username for 'https://github.com':".
# We always answer: username = "x-access-token", password = $GITHUB_TOKEN.
case "$1" in
  *Username*) printf '%s' "x-access-token" ;;
  *Password*) printf '%s' "${GITHUB_TOKEN}" ;;
  *)          printf '%s' "${GITHUB_TOKEN}" ;;
esac
