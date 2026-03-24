#!/bin/bash
set -e

echo "=== Dependency Cache Vulnerability Scan ==="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

SCAN_DIR=$(mktemp -d)
RESULTS_DIR="/scan-results"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
RESULT_FILE="$RESULTS_DIR/scan-${TIMESTAMP}.json"
MAX_ENTRIES=500

# --- npm: extract packages from cacache index ---
# npm stores packages in a content-addressable cache (_cacache). The index
# files contain JSON with tgz URLs like:
#   https://registry.npmjs.org/{name}/-/{name}-{version}.tgz
# We parse these to build a synthetic package.json for osv-scanner.
echo "Scanning npm cache..."
if [ -d /cache/npm/_cacache/index-v5 ]; then
    npm_dir="$SCAN_DIR/npm"
    mkdir -p "$npm_dir"
    # Extract package name+version from tgz URLs in the cacache index
    grep -rh '"key"' /cache/npm/_cacache/index-v5/ 2>/dev/null \
        | grep -oP 'registry\.npmjs\.org/[^"]+\.tgz' \
        | sed -n 's|.*/-/\(.*\)\.tgz|\1|p' \
        | sort -u \
        | head -"$MAX_ENTRIES" \
        | awk -F'-' '{
            # Split "name-version" — version starts at the last segment matching [0-9]
            # Handle scoped packages and multi-hyphen names
            for (i=NF; i>=2; i--) {
                if ($i ~ /^[0-9]/) {
                    name=""; for(j=1;j<i;j++) name = name (j>1?"-":"") $j
                    ver=""; for(j=i;j<=NF;j++) ver = ver (j>i?"-":"") $j
                    printf "    \"%s\": \"%s\"", name, ver
                    if (NR > 1) printf ","
                    printf "\n"
                    break
                }
            }
        }' > "$npm_dir/deps.tmp" 2>/dev/null || true

    if [ -s "$npm_dir/deps.tmp" ]; then
        # Remove trailing comma from last line and wrap in package.json
        sed -i '1s/^/{\n  "name": "npm-cache-scan",\n  "version": "0.0.0",\n  "dependencies": {\n/' "$npm_dir/deps.tmp"
        echo -e "  }\n}" >> "$npm_dir/deps.tmp"
        mv "$npm_dir/deps.tmp" "$npm_dir/package.json"
        count=$(grep -c '": "' "$npm_dir/package.json" 2>/dev/null || echo 0)
        # Subtract 2 for name and version fields
        count=$((count - 2))
        echo "  Found $count npm packages (from cacache index)"
    else
        rm -f "$npm_dir/deps.tmp"
        echo "  No npm packages found in cacache index"
    fi
else
    echo "  /cache/npm/_cacache not found, skipping"
fi

# --- pnpm: find package.json files in the pnpm content-addressable store ---
echo "Scanning pnpm cache..."
if [ -d /cache/pnpm ]; then
    pnpm_dir="$SCAN_DIR/pnpm"
    mkdir -p "$pnpm_dir"
    find /cache/pnpm -name "package.json" -size +10c 2>/dev/null | head -"$MAX_ENTRIES" | while read -r pj; do
        if grep -q '"name"' "$pj" 2>/dev/null; then
            hash=$(echo "$pj" | sha256sum | cut -d' ' -f1 | head -c 16)
            target_dir="$pnpm_dir/pkg-${hash}"
            mkdir -p "$target_dir"
            cp "$pj" "$target_dir/package.json" 2>/dev/null || true
        fi
    done
    count=$(find "$pnpm_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count pnpm package manifests"
else
    echo "  /cache/pnpm not found, skipping"
fi

# --- bun: find package.json in versioned package dirs ({name}@{version}@@@1/) ---
echo "Scanning bun cache..."
if [ -d /cache/bun ]; then
    bun_dir="$SCAN_DIR/bun"
    mkdir -p "$bun_dir"
    find /cache/bun -maxdepth 2 -name "package.json" -size +10c 2>/dev/null | head -"$MAX_ENTRIES" | while read -r pj; do
        if grep -q '"name"' "$pj" 2>/dev/null; then
            hash=$(echo "$pj" | sha256sum | cut -d' ' -f1 | head -c 16)
            target_dir="$bun_dir/pkg-${hash}"
            mkdir -p "$target_dir"
            cp "$pj" "$target_dir/package.json" 2>/dev/null || true
        fi
    done
    count=$(find "$bun_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count bun package manifests"
else
    echo "  /cache/bun not found, skipping"
fi

# --- uv: find METADATA in archive-v0/*/dist-info/ directories ---
echo "Scanning uv cache..."
if [ -d /cache/uv ]; then
    uv_dir="$SCAN_DIR/uv"
    mkdir -p "$uv_dir"
    find /cache/uv -name "METADATA" 2>/dev/null | head -"$MAX_ENTRIES" | while read -r meta; do
        hash=$(echo "$meta" | sha256sum | cut -d' ' -f1 | head -c 16)
        target_dir="$uv_dir/pkg-${hash}"
        mkdir -p "$target_dir"
        cp "$meta" "$target_dir/METADATA" 2>/dev/null || true
    done
    count=$(find "$uv_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count uv package metadata files"
else
    echo "  /cache/uv not found, skipping"
fi

# --- pip: HTTP response cache (http-v2/) has no parsable metadata ---
# pip's cache stores raw HTTP responses, not package manifests. Unlike uv
# which keeps extracted archives with METADATA files, pip's cache format
# cannot be scanned by osv-scanner. Pip packages are best scanned via
# project-level requirements.txt or Pipfile.lock files.
echo "Scanning pip cache... (skipped — pip uses HTTP response cache without parsable metadata)"

echo ""
echo "Running osv-scanner..."
echo ""

# Run osv-scanner on discovered manifests
total_files=$(find "$SCAN_DIR" -type f 2>/dev/null | wc -l)
if [ "$total_files" -eq 0 ]; then
    echo "No package manifests found in cache. Cache may be empty."
    echo '{"vulnerabilities": [], "status": "empty_cache"}' > "$RESULT_FILE"
    echo ""
    echo "Results written to: $RESULT_FILE"
    rm -rf "$SCAN_DIR"
    exit 0
fi

echo "  Total files to scan: $total_files"

# osv-scanner returns 1 if vulnerabilities are found, 0 if clean
set +e
osv-scanner --recursive --format json "$SCAN_DIR" > "$RESULT_FILE" 2>&1
scan_exit=$?
set -e

if [ $scan_exit -eq 0 ]; then
    echo "No vulnerabilities found."
elif [ $scan_exit -eq 1 ]; then
    echo "VULNERABILITIES FOUND — see $RESULT_FILE for details"
    # Print summary to stdout
    if command -v jq >/dev/null 2>&1 && [ -s "$RESULT_FILE" ]; then
        vuln_count=$(jq '[.results[]?.packages[]?.vulnerabilities // [] | length] | add // 0' "$RESULT_FILE" 2>/dev/null || echo "?")
        echo "  Total vulnerabilities: $vuln_count"
    fi
else
    echo "Scanner exited with code $scan_exit (possible error)"
fi

echo ""
echo "Results written to: $RESULT_FILE"

# Clean up temp directory
rm -rf "$SCAN_DIR"

exit $scan_exit
