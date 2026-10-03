#!/bin/bash
# Diagnostic traces of the 2.1 zero-throughput anomalies (2026-10-02). Existing trace binary, no rebuild.
cd "$(dirname "$0")"
BIN=/home/vijay/ns-allinone-3.48/ns-3.48/build/scratch/ns3.48-dama-mlo-trace-optimized
run_one() { name=$1; shift; [ -e "$name.txt" ] && exit 0
  nice -n 15 "$BIN" "$@" --psTrace=true > "$name.tmp" 2> "$name.err"; rc=$?
  case $rc in 130|137|143) rm -f "$name.tmp" "$name.err"; exit 0;; esac
  echo "rc $rc" >> "$name.tmp"; mv "$name.tmp" "$name.txt"; }
export -f run_one; export BIN
xargs -P 2 -L 1 bash -c 'run_one "$@"' _ < jobs.txt
echo "done $(date '+%F %T')"
