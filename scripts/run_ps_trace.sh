#!/bin/bash
# Power-save trace of the downlink sensitivity runs (failed-run follow-up, 2026-10-01).
# Runs scratch/dama-mlo-trace.cc with --psTrace=true on exactly the argument sets of
# experiments.py "sens downlink" (code 2.1), one output file per run in $OUT.
# Skips runs already done. SEEDS selects replications (default: 1), e.g. SEEDS="1 2 3".
# P="parallel jobs" (default 2). Summary: python3 summarize_ps_trace.py [dir]
cd "$(dirname "$0")"
BIN=${BIN:-${NS3_DIR:-/home/vijay/ns-allinone-3.48/ns-3.48}/build/scratch/ns3.48-dama-mlo-trace-optimized}
OUT=${OUT:-results/ps_trace}
SEEDS=${SEEDS:-1}
P=${P:-2}
mkdir -p "$OUT"
python3 - "$SEEDS" > "$OUT/jobs.txt" <<'PY'
import sys, experiments as E, simlib as S
seeds = {int(s) for s in sys.argv[1].split()}
seen = set()
for a in E.state_args({"downlink": "true"}, modes=E.SENS_MODES):
    if a["rngRun"] not in seeds:
        continue
    full = {**S.BASE, **a}
    key = S._key(full, S.CODE_VERSION)
    if key in seen:
        continue
    seen.add(key)
    name = (f"sc{a['scenario']}_{a['linkMode']}_{a['n4Rate']}_{a.get('n5X', 'na')}_{a.get('n5Y', 'na')}"
            f"_s{a['rngRun']}")
    print(name, " ".join(f"--{k}={v}" for k, v in sorted(full.items())))
PY
run_one() {
    name=$1; shift
    [ -e "$OUT/$name.txt" ] && exit 0
    nice -n 15 "$BIN" "$@" --psTrace=true > "$OUT/$name.tmp" 2> "$OUT/$name.err"
    rc=$?
    # stopped by a pause (SIGINT/SIGKILL/SIGTERM): not a result, redo on the next start
    case $rc in 130|137|143) rm -f "$OUT/$name.tmp" "$OUT/$name.err"; exit 0 ;; esac
    echo "rc $rc" >> "$OUT/$name.tmp"
    mv "$OUT/$name.tmp" "$OUT/$name.txt"
}
export -f run_one; export BIN OUT
echo "$(wc -l < "$OUT/jobs.txt") jobs, $P parallel, output $OUT"
xargs -P "$P" -L 1 bash -c 'run_one "$@"' _ < "$OUT/jobs.txt"
echo "done $(date '+%F %T')"
