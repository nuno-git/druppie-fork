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

# --- npm: find package.json / package-lock.json preserving original names ---
echo "Scanning npm cache..."
if [ -d /cache/npm ]; then
    npm_dir="$SCAN_DIR/npm"
    mkdir -p "$npm_dir"
    # Search for package.json and package-lock.json in the cache tree
    find /cache/npm \( -name "package.json" -o -name "package-lock.json" \) -size +10c 2>/dev/null | head -200 | while read -r pj; do
        # Only copy if it has a "name" field (actual package manifest)
        if grep -q '"name"' "$pj" 2>/dev/null; then
            hash=$(echo "$pj" | md5sum | cut -d' ' -f1)
            target_dir="$npm_dir/pkg-${hash}"
            mkdir -p "$target_dir"
            # Preserve the original filename so osv-scanner recognizes it
            cp "$pj" "$target_dir/$(basename "$pj")" 2>/dev/null || true
        fi
    done
    count=$(find "$npm_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count npm package manifests"
else
    echo "  /cache/npm not found, skipping"
fi

# --- pnpm: find package.json files in the pnpm store metadata ---
echo "Scanning pnpm cache..."
if [ -d /cache/pnpm ]; then
    pnpm_dir="$SCAN_DIR/pnpm"
    mkdir -p "$pnpm_dir"
    find /cache/pnpm -name "package.json" -size +10c 2>/dev/null | head -200 | while read -r pj; do
        if grep -q '"name"' "$pj" 2>/dev/null; then
            hash=$(echo "$pj" | md5sum | cut -d' ' -f1)
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

# --- pip: copy METADATA / PKG-INFO preserving original names ---
echo "Scanning pip cache..."
if [ -d /cache/pip ]; then
    pip_dir="$SCAN_DIR/pip"
    mkdir -p "$pip_dir"
    find /cache/pip -name "METADATA" -o -name "PKG-INFO" 2>/dev/null | head -200 | while read -r meta; do
        hash=$(echo "$meta" | md5sum | cut -d' ' -f1)
        target_dir="$pip_dir/pkg-${hash}"
        mkdir -p "$target_dir"
        # Preserve original filename (METADATA or PKG-INFO)
        cp "$meta" "$target_dir/$(basename "$meta")" 2>/dev/null || true
    done
    count=$(find "$pip_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count pip package metadata files"
else
    echo "  /cache/pip not found, skipping"
fi

# --- uv: same PyPI ecosystem as pip, uses METADATA files ---
echo "Scanning uv cache..."
if [ -d /cache/uv ]; then
    uv_dir="$SCAN_DIR/uv"
    mkdir -p "$uv_dir"
    find /cache/uv -name "METADATA" -o -name "PKG-INFO" 2>/dev/null | head -200 | while read -r meta; do
        hash=$(echo "$meta" | md5sum | cut -d' ' -f1)
        target_dir="$uv_dir/pkg-${hash}"
        mkdir -p "$target_dir"
        cp "$meta" "$target_dir/$(basename "$meta")" 2>/dev/null || true
    done
    count=$(find "$uv_dir" -type f 2>/dev/null | wc -l)
    echo "  Found $count uv package metadata files"
else
    echo "  /cache/uv not found, skipping"
fi

# Note: bun is not scanned because its cache stores compiled/binary artifacts
# without standard package manifests (no package.json or METADATA files).
# osv-scanner cannot identify packages from bun's cache format.

echo ""
echo "Running osv-scanner..."
echo ""

# Run osv-scanner on discovered manifests
if [ "$(find "$SCAN_DIR" -type f 2>/dev/null | wc -l)" -eq 0 ]; then
    echo "No package manifests found in cache. Cache may be empty."
    echo '{"vulnerabilities": [], "status": "empty_cache"}' > "$RESULT_FILE"
    echo ""
    echo "Results written to: $RESULT_FILE"
    rm -rf "$SCAN_DIR"
    exit 0
fi

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
