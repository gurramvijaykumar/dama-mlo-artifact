#!/bin/bash
# Codex item 3: edge-stall trace runs (scratch/dama-mlo-trace.cc, code 2.1 + trace).
# N5 on MAP 1 (scenario 1), N4 at EhtMcs0, base configuration of simlib.BASE.
# Failing points (70,165), (100,195); nearby working points (40,165), (70,195);
# control: N5 single-link 5 GHz (--n5Links=5) at the failing points; references:
# mloConfined and SLO at (100,195). Output: results/edge_trace/<name>.txt
# (existing outputs are skipped). Runs 2 at a time next to the main sweep.
cd "$(dirname "$0")"
# BIN: the built trace scenario; OUT: output folder (both can be set in the environment)
BIN=${BIN:-${NS3_DIR:-/home/vijay/ns-allinone-3.48/ns-3.48}/build/scratch/ns3.48-dama-mlo-trace-optimized}
OUT=${OUT:-results/edge_trace}
BASE="--accessExp=2.5 --backhaulBand=5 --backhaulExp=2.0 --backhaulWidth=80 --downlink=false --fastRate=ideal --n4Rate=EhtMcs0 --n4X=120.0 --prop=logdist --simTime=13.0 --staDist=20.0 --txPower=20.0 --useTcp=true --warmup=3.0 --scenario=1"
jobs_list() {
    for s in 1 2; do
        for p in 70,165 100,195 40,165 70,195; do
            echo "mlo_${p/,/_}_s$s --linkMode=mlo --n5X=${p%,*} --n5Y=${p#*,} --rngRun=$s"
        done
        for p in 70,165 100,195; do
            echo "mlo5only_${p/,/_}_s$s --linkMode=mlo --n5Links=5 --n5X=${p%,*} --n5Y=${p#*,} --rngRun=$s"
        done
    done
    echo "mloConfined_100_195_s1 --linkMode=mloConfined --n5X=100 --n5Y=195 --rngRun=1"
    echo "slo_100_195_s1 --linkMode=slo --n5X=100 --n5Y=195 --rngRun=1"
}
run_one() {
    name=$1; shift
    [ -s "$OUT/$name.txt" ] && grep -q "^R traceVersion" "$OUT/$name.txt" && return
    nice "$BIN" $BASE "$@" > "$OUT/$name.tmp" 2>&1 && mv "$OUT/$name.tmp" "$OUT/$name.txt" \
        && echo "[trace $(date '+%T')] done $name" || echo "[trace $(date '+%T')] FAILED $name"
}
export -f run_one; export BIN BASE OUT
mkdir -p "$OUT"
jobs_list | xargs -P 2 -L 1 bash -c 'run_one "$@"' _
echo "[trace $(date '+%T')] all done"
