"""Screen every stored run for zero-delivery / zero-transmission stations (ADDBA-expiry follow-up, 2026-10-02).

A run is a CANDIDATE if any station has throughput < 0.05 Mbit/s or transmitted no data frame on any link.
Runs with N4 at EhtMcs7 are listed separately: that rate is never decoded and those runs are not used in
any table (replaced by EhtMcs4). Candidates are traced with the isolated diagnostic build; the screen itself
classifies nothing.

Usage: python3 screen_zero_delivery.py [outdir]   (default results/addba_screen)
Writes <outdir>/jobs.txt (name + full arguments) and <outdir>/candidates.json (name, version, args, hits, stored out).
"""

import json
import os
import sys

import simlib as S

TPUT_ZERO = 0.05  # Mbit/s

out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(S.HERE, "results", "addba_screen")
os.makedirs(out_dir, exist_ok=True)

cands, unused, seen = [], 0, set()
for line in open(os.path.join(S.HERE, "results", "runs.jsonl")):
    r = json.loads(line)
    o, a = r["out"], r["args"]
    hits = []
    for st in sorted({k[5:] for k in o if k.startswith("tput_")}):
        frames = [v for k, v in o.items() if k.startswith("frames_" + st + "_")]
        zero_tx = bool(frames) and sum(frames) == 0
        if o["tput_" + st] < TPUT_ZERO or zero_tx:
            hits.append(st + ("(0tx)" if zero_tx else ""))
    if not hits:
        continue
    if a.get("n4Rate") == "EhtMcs7":
        unused += 1
        continue
    full = {**S.BASE, **a}
    argstr = " ".join(f"--{k}={v}" for k, v in sorted(full.items()))
    if argstr in seen:
        continue
    seen.add(argstr)
    name = f"c{len(cands):04d}"
    cands.append({"name": name, "version": str(r.get("codeVersion")), "args": full, "hits": hits, "out": o})

with open(os.path.join(out_dir, "jobs.txt"), "w") as f:
    for c in cands:
        f.write(c["name"] + " " + " ".join(f"--{k}={v}" for k, v in sorted(c["args"].items())) + "\n")
with open(os.path.join(out_dir, "candidates.json"), "w") as f:
    json.dump(cands, f)
by_ver = {}
for c in cands:
    by_ver[c["version"]] = by_ver.get(c["version"], 0) + 1
print(f"candidates (unique runs): {len(cands)}  by version: {by_ver}  "
      f"(not used, N4 EhtMcs7: {unused})  -> {out_dir}")
