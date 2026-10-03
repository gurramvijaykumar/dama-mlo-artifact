#!/bin/bash
# ADDBA-expiry candidate traces (2026-10-02): isolated diag build (ARP capture), --diagTrace. Skips finished runs.
cd "${1:?usage: run_addba_screen.sh DIR (holding jobs.txt)}"
BIN=${BIN:-${NS3_DIR:-/path/to/ns-3.48}}/build/scratch/ns3.48-dama-mlo-diag-optimized
run_one() { name=$1; shift; [ -e "$name.txt" ] && exit 0
  nice -n 15 "$BIN" "$@" --psTrace=true --diagTrace=true > "$name.tmp" 2> "$name.err"; rc=$?
  case $rc in 130|137|143) rm -f "$name.tmp" "$name.err"; exit 0;; esac
  echo "rc $rc" >> "$name.tmp"; mv "$name.tmp" "$name.txt"; }
export -f run_one; export BIN
xargs -P ${P:-3} -L 1 bash -c 'run_one "$@"' _ < jobs.txt
echo "done $(date '+%F %T')"
