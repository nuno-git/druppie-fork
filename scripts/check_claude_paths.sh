#!/bin/bash
echo "=== Checking root installation ==="
ls -la /root/.local/bin/claude 2>/dev/null || echo "No root .local/bin/claude"
ls -la /usr/local/bin/claude 2>/dev/null || echo "No /usr/local/bin/claude"
ls -la /usr/bin/claude 2>/dev/null || echo "No /usr/bin/claude"

echo ""
echo "=== Checking PATH in bashrc for all users ==="
for home in /home/*/; do
    user=$(basename "$home")
    echo ""
    echo "--- $user ---"
    grep -i "claude\|\.local/bin" "$home/.bashrc" 2>/dev/null || echo "  No claude/local-bin references in .bashrc"
    grep -i "claude\|\.local/bin" "$home/.profile" 2>/dev/null || echo "  No claude/local-bin references in .profile"
done

echo ""
echo "--- root ---"
grep -i "claude\|\.local/bin" /root/.bashrc 2>/dev/null || echo "  No claude/local-bin references in root .bashrc"
grep -i "claude\|\.local/bin" /root/.profile 2>/dev/null || echo "  No claude/local-bin references in root .profile"

echo ""
echo "=== Checking /etc/profile.d/ for claude ==="
grep -rl "claude\|\.local/bin" /etc/profile.d/ 2>/dev/null || echo "Nothing in /etc/profile.d/"

echo ""
echo "=== Checking /etc/environment ==="
cat /etc/environment 2>/dev/null
