#!/usr/bin/env python3
"""Pause-rule watcher for Stage B (amendment A3): every 120 s, apply the amended health checker to completed Stage B
runs; if MORE THAN 5% OF THE COMPLETED Stage B runs are flagged (A4), stop run_stageB.py and the simulations, and
write PAUSED.txt. Processes are stopped by PID from an exact process listing."""
import json, os, re, subprocess, sys, time
REV = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2"; sys.path.insert(0, REV)
from simlib import parse  # noqa: E402
CC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); RUNS = os.path.join(CC, "stageB_runs")
def flags(tag, e):
    f = []
    if e.get("skipped"): return f
    if e["exit"] != 0: f.append(f"exit {e['exit']}")
    if not e.get("My_absent", True): f.append("My created")
    if e["exit"] == 0:
        out = parse(open(os.path.join(RUNS, tag, "stdout.txt")).read())
        f += [f"zero delivery {k[5:]}" for k, v in out.items() if k.startswith("tput_") and v < 0.01]
        last = {}; de = set(); nsta = sum(k.startswith("tput_") for k in out)
        for line in open(os.path.join(RUNS, tag, "diag.txt")):
            p = line.split()
            if len(p) > 2 and p[1] in ("ASSOC", "DEASSOC"):
                n = re.search(r"/NodeList/(\d+)/", p[2]).group(1); last[n] = (int(p[0]), p[1])
                if p[1] == "DEASSOC": de.add(n)
        if sum(1 for t, ev in last.values() if ev == "ASSOC" and t <= 3e9) < nsta: f.append("association by 3 s incomplete")
        f += [f"DEASSOC node {n}" for n in sorted(de)]
    return f
while True:
    time.sleep(120)
    lp = os.path.join(RUNS, "stageB_log.json")
    if not os.path.exists(lp): continue
    log = json.load(open(lp)); fl = {e["tag"]: flags(e["tag"], e) for e in log["runs"]}
    nflag = sum(1 for v in fl.values() if v)
    json.dump({"checked": len(fl), "flagged": nflag, "flags": {k: v for k, v in fl.items() if v}}, open(os.path.join(RUNS, "health_live.json"), "w"), indent=1)
    if len(fl) > 0 and nflag / len(fl) > 0.05:   # A4: denominator = completed runs (spec Sec. 8 wording)
        ps = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout.splitlines()[1:]
        for ln in ps:
            pid, _, args = ln.strip().partition(" ")
            if args.startswith("python3 stageP/run_stageB.py") or "build/scratch/ns3.48-dama-mlo-v22-diag-optimized" in args.split(" ")[-0 if False else 0] or args.split(" ")[:3][-1:] == ["/home/vijay/ns-allinone-3.48/ns-3.48/build/scratch/ns3.48-dama-mlo-v22-diag-optimized"]:
                subprocess.run(["kill", pid])
        open(os.path.join(RUNS, "PAUSED.txt"), "w").write(f"paused: {nflag} flagged of {len(fl)} completed\n"); print("PAUSED", nflag); break
    alive = any(ln.split(None, 1)[1].startswith("python3 stageP/run_stageB.py")
                for ln in subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout.splitlines()[1:] if len(ln.split(None, 1)) > 1)
    if not alive and len(log["runs"]) >= 480:
        print("watcher done", nflag, "flagged of", len(fl)); break
    if not alive:
        print("runner not running; watcher exits", nflag, "flagged of", len(fl)); break
