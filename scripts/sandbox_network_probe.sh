#!/usr/bin/env bash
# sandbox_network_probe.sh — determine what a gVisor coding sandbox can reach.
#
# Answers AC2 of the coding-sandbox story: "is there network access from the
# sandbox to other modules/services in the cluster (Gitea, LLM, modules), and
# does it work?" Run this FROM INSIDE a sandbox pod and record the output in
# docs/sandbox-network-findings.md.
#
# How to run:
#   # Option 1 — via kubectl exec into a live sandbox pod:
#   kubectl -n <instance>-sandbox exec -it <sandbox-pod> -- bash -c \
#     "$(cat scripts/sandbox_network_probe.sh)"
#
#   # Option 2 — via the coding:bash MCP tool (paste the script as the command).
#
# Override the endpoints for your instance via env vars (defaults below match
# the Helm ConfigMap naming; from inside the sandbox cluster DNS usually will
# NOT resolve these — that is itself a finding):
#   LLM_PROBE_URL       default: http://druppie-backend:8000/health
#   FILESEARCH_URL      default: http://druppie-module-filesearch:9004/health
#   REGISTRY_URL        default: http://druppie-module-registry:9007/health
#   GITEA_URL           default: http://druppie-gitea:3000/api/healthz
#
# Exit code is always 0 — this is a diagnostic, not a gate. Read the table.

set -u

TIMEOUT="${PROBE_TIMEOUT:-6}"
LLM_PROBE_URL="${LLM_PROBE_URL:-http://druppie-backend:8000/health}"
FILESEARCH_URL="${FILESEARCH_URL:-http://druppie-module-filesearch:9004/health}"
REGISTRY_URL="${REGISTRY_URL:-http://druppie-module-registry:9007/health}"
GITEA_URL="${GITEA_URL:-http://druppie-gitea:3000/api/healthz}"

pass=0; fail=0
printf '%-42s | %-9s | %s\n' "PROBE" "OUTCOME" "DETAIL"
printf -- '-------------------------------------------+-----------+---------------------------\n'

row() { # name  outcome  detail
  printf '%-42s | %-9s | %s\n' "$1" "$2" "$3"
  case "$2" in PASS) pass=$((pass+1));; FAIL) fail=$((fail+1));; esac
}

# --- DNS resolution --------------------------------------------------------
dns() { # host
  if getent hosts "$1" >/dev/null 2>&1 || nslookup "$1" >/dev/null 2>&1; then
    echo "resolves"
  else
    echo "NO-RESOLVE"
  fi
}

# --- HTTP(S) reachability --------------------------------------------------
# A failed connection makes curl BOTH print "000" (via -w) AND exit non-zero,
# so a trailing `|| echo 000` would append a second 000 and corrupt every
# comparison below. Capture curl's own output and only substitute 000 when it
# printed nothing at all (e.g. curl binary missing). Result is always a single
# clean value.
http() { # url
  local out
  out=$(curl -sS -k -o /dev/null -m "$TIMEOUT" -w '%{http_code}' "$1" 2>/dev/null)
  printf '%s' "${out:-000}"
}

echo "# Sandbox network probe  (timeout=${TIMEOUT}s)"
echo

# 1) Internet over HTTPS — EXPECTED to work (egress 0.0.0.0/0:443 is allowed).
code=$(http "https://pypi.org/simple/")
[ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ] \
  && row "internet https (pypi.org:443)" "PASS" "HTTP $code — as designed" \
  || row "internet https (pypi.org:443)" "FAIL" "HTTP $code — expected reachable"

code=$(http "https://github.com/")
[ "$code" != "000" ] \
  && row "internet https (github.com:443)" "PASS" "HTTP $code" \
  || row "internet https (github.com:443)" "FAIL" "no response"

# 2) Internet over plain HTTP:80 — EXPECTED to FAIL (only :443 is allowed out).
code=$(http "http://example.com/")
[ "$code" = "000" ] \
  && row "internet http (example.com:80)" "EXP-FAIL" "blocked as designed (:80 not allowed)" \
  || row "internet http (example.com:80)" "PASS?" "HTTP $code — unexpectedly reachable"

# 3) Cluster DNS — EXPECTED NO-RESOLVE (pod uses node resolver, not CoreDNS).
r=$(dns "druppie-backend")
row "cluster DNS (short svc name)" "$([ "$r" = resolves ] && echo INFO || echo EXP-FAIL)" \
    "$r — gVisor pod uses dnsPolicy: Default (node resolver)"

# 4) Gitea — EXPECTED unreachable (ClusterIP; handled host-side via bundles).
code=$(http "$GITEA_URL")
[ "$code" = "000" ] \
  && row "gitea ($GITEA_URL)" "EXP-FAIL" "unreachable as designed (host-side clone/push)" \
  || row "gitea ($GITEA_URL)" "INFO" "HTTP $code — reachable (unexpected for gVisor)"

# 5) LLM backend — policy ALLOWS backend:8000, but ClusterIP+DNS likely block it.
code=$(http "$LLM_PROBE_URL")
[ "$code" != "000" ] \
  && row "llm backend ($LLM_PROBE_URL)" "PASS" "HTTP $code — reachable" \
  || row "llm backend ($LLM_PROBE_URL)" "FAIL" "unreachable (ClusterIP/DNS?) — confirm"

# 6) Module MCP servers — EXPECTED unreachable (no egress rule + ClusterIP).
for u in "$FILESEARCH_URL" "$REGISTRY_URL"; do
  code=$(http "$u")
  [ "$code" = "000" ] \
    && row "module ($u)" "EXP-FAIL" "unreachable — no module egress + ClusterIP" \
    || row "module ($u)" "INFO" "HTTP $code — reachable (unexpected)"
done

echo
echo "Legend: PASS=works as needed · FAIL=needs works but broken ·"
echo "        EXP-FAIL=blocked on purpose (correct) · INFO=note the value"
echo "Summary: ${pass} pass / ${fail} fail (EXP-FAIL and INFO are not failures)."
echo
echo "Record this output in docs/sandbox-network-findings.md."
exit 0
