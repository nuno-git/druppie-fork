#!/bin/bash
echo "=== Checking claude installation for all users ==="
for home in /home/*/; do
    user=$(basename "$home")
    echo ""
    echo "--- $user ---"
    ls -la "$home/.local/bin/claude" 2>/dev/null || echo "  No .local/bin/claude"
    ls -la "$home/.local/share/claude/" 2>/dev/null || echo "  No .local/share/claude/"
done
