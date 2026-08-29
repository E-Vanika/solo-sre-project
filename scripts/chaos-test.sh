#!/usr/bin/env bash
# Simple chaos scenarios for the demo. Run each one, observe recovery,
# then fill in docs/runbook.md / a postmortem from what you saw.
set -euo pipefail

scenario="${1:-}"

case "$scenario" in
  kill-app)
    echo "Killing app container to test restart policy..."
    docker kill app
    sleep 3
    docker ps --filter name=app
    ;;
  cpu-spike)
    echo "Spiking CPU for 30s with stress-ng (install: apt install stress-ng)..."
    stress-ng --cpu 1 --timeout 30s
    ;;
  fill-disk)
    echo "Filling disk with a 500MB junk file for 20s, then cleaning up..."
    fallocate -l 500M /tmp/chaos-fill
    sleep 20
    rm -f /tmp/chaos-fill
    ;;
  oom)
    echo "Forcing app container to exceed its 150m mem_limit..."
    docker exec app python -c "x = bytearray(300*1024*1024)" || echo "Container OOM-killed as expected, check: docker ps -a"
    ;;
  *)
    echo "Usage: $0 {kill-app|cpu-spike|fill-disk|oom}"
    exit 1
    ;;
esac
