#!/bin/bash
# Fix Claude Code for pieter

set -e

echo "=== Switching to pieter and diagnosing Claude Code ==="

sudo -i -u pieter bash << 'PIETER_EOF'
echo "--- Running as: $(whoami) ---"
echo "--- Home: $HOME ---"

# 1. Check if claude is already somewhere
echo ""
echo "=== Step 1: Looking for existing claude installation ==="
which claude 2>/dev/null && echo "Found in PATH!" || echo "Not in PATH"
find /usr/local /home/pieter -name "claude" -type f 2>/dev/null || true
ls -la ~/.claude/bin/ 2>/dev/null || echo "No ~/.claude/bin/ directory"

# 2. Check Node.js
echo ""
echo "=== Step 2: Checking Node.js ==="
if command -v node &>/dev/null; then
    echo "Node: $(node --version)"
    echo "npm:  $(npm --version)"
else
    echo "Node.js NOT found - installing..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
    echo "Node: $(node --version)"
    echo "npm:  $(npm --version)"
fi

# 3. Install Claude Code
echo ""
echo "=== Step 3: Installing Claude Code ==="
npm install -g @anthropic-ai/claude-code

# 4. Ensure PATH includes npm global bin
echo ""
echo "=== Step 4: Fixing PATH ==="
NPM_BIN="$(npm config get prefix)/bin"
if [[ ":$PATH:" != *":$NPM_BIN:"* ]]; then
    echo "Adding $NPM_BIN to PATH in ~/.bashrc"
    echo "export PATH=\"$NPM_BIN:\$PATH\"" >> ~/.bashrc
fi

# 5. Verify
echo ""
echo "=== Step 5: Verification ==="
export PATH="$NPM_BIN:$PATH"
which claude && claude --version && echo "SUCCESS: Claude Code is ready!" || echo "FAILED: Something went wrong"

PIETER_EOF
