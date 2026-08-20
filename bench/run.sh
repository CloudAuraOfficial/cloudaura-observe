#!/usr/bin/env bash
# E05 hourly window. Cron slot :35. ponytail: inline guards until E00's shared runner lands.
set -euo pipefail; cd "$(dirname "$0")"
exec 9>.window.lock; flock -n 9 || { echo "skip: window running"; exit 0; }
load=$(cut -d' ' -f1 /proc/loadavg); awk -v l="$load" 'BEGIN{exit !(l>3.0)}' && { echo "skip: load $load"; exit 0; }
curl -sf 127.0.0.1:8019/health >/dev/null || { echo "skip: faultsvc down"; exit 0; }
trap 'curl -s -XPOST 127.0.0.1:8019/bench/fault -d "{\"fault\":null}" >/dev/null' EXIT   # never leave a fault on
python3 window.py
