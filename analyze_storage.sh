#!/bin/bash
# Storage analysis script for VM

echo "========================================="
echo "  VM Storage Analysis - $(date)"
echo "========================================="

echo ""
echo "--- Filesystem Usage ---"
df -h --output=source,fstype,size,used,avail,pcent,target | grep -v tmpfs | grep -v udev

echo ""
echo "--- Top 20 largest directories under / ---"
du -h --max-depth=2 / 2>/dev/null | sort -rh | head -20

echo ""
echo "=== PER-USER STORAGE USAGE ==="
echo ""
echo "--- /home directories ---"
if [ -d /home ]; then
    for dir in /home/*/; do
        user=$(basename "$dir")
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        echo "  $user: $size"
    done | sort -t: -k2 -rh
fi

echo ""
echo "--- Per-user breakdown (all users with files) ---"
printf "%-20s %10s %10s\n" "USER" "FILES" "SIZE"
printf "%-20s %10s %10s\n" "----" "-----" "----"
# Find all users who own files on the system, sorted by total size
find / -xdev -not -path '/proc/*' -not -path '/sys/*' 2>/dev/null | \
    xargs -d '\n' stat --format='%U' 2>/dev/null | \
    sort | uniq -c | sort -rn | head -20 | \
    while read count user; do
        size=$(find / -xdev -not -path '/proc/*' -not -path '/sys/*' -user "$user" -type f -exec du -cb {} + 2>/dev/null | tail -1 | cut -f1)
        if [ -n "$size" ]; then
            human_size=$(numfmt --to=iec "$size" 2>/dev/null || echo "${size}B")
            printf "%-20s %10s %10s\n" "$user" "$count" "$human_size"
        fi
    done

echo ""
echo "--- Per-user /home breakdown (top subdirs) ---"
if [ -d /home ]; then
    for dir in /home/*/; do
        user=$(basename "$dir")
        echo ""
        echo "  [$user] - top 10 subdirs:"
        du -h --max-depth=1 "$dir" 2>/dev/null | sort -rh | head -10 | sed 's/^/    /'
    done
fi

echo ""
echo "--- Docker disk usage ---"
if command -v docker &>/dev/null; then
    docker system df -v 2>/dev/null || echo "Docker not accessible"
else
    echo "Docker not installed"
fi

echo ""
echo "--- Docker volumes ---"
if command -v docker &>/dev/null; then
    docker volume ls -q 2>/dev/null | while read vol; do
        size=$(docker run --rm -v "$vol":/data alpine du -sh /data 2>/dev/null | cut -f1)
        echo "  $vol: $size"
    done
fi

echo ""
echo "--- Large files (>100MB) with owner ---"
find / -xdev -type f -size +100M -printf '%s %u %p\n' 2>/dev/null | sort -rn | head -20 | \
    while read size user path; do
        human_size=$(numfmt --to=iec "$size" 2>/dev/null || echo "${size}B")
        printf "  %-8s %-15s %s\n" "$human_size" "$user" "$path"
    done

echo ""
echo "--- Journal logs size ---"
journalctl --disk-usage 2>/dev/null || echo "journalctl not available"

echo ""
echo "--- /tmp usage ---"
du -sh /tmp 2>/dev/null

echo ""
echo "--- Inode usage ---"
df -ih | grep -v tmpfs | grep -v udev

echo ""
echo "========================================="
echo "  Done"
echo "========================================="
