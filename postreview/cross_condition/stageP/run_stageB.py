#!/usr/bin/env python3
"""Stage B of CROSS_CONDITION_SPEC.md (gate 3): 480 outcome runs = 3 conditions x 8 frozen positions x 2 arms
(scenario 1: N5 -> MAP 1, scenario 2: N5 -> MAP 4) x 2 modes x seeds 1-5, v2.2 diag build. Resumable. Caps: 300 s per
run, 6 h batch (runs not started by then are recorded "not run"). Flagged runs are data and are never re-run; a run
killed by the HOST may be re-executed once (manual, logged). --dry prints the plan.
Usage: python3 run_stageB.py [--dry]"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
NS3 = "/home/vijay/ns-allinone-3.48/ns-3.48"
REV = os.path.join(NS3, "My Research Papers/revision_v2"); CC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(CC, "stageB_runs"); BIN = os.path.join(NS3, "build/scratch/ns3.48-dama-mlo-v22-diag-optimized")
sys.path.insert(0, REV)
from simlib import BASE, parse  # noqa: E402
sha = lambda p: subprocess.run(["sha256sum", p], capture_output=True, text=True).stdout.split()[0]
assert sha(BIN) == "f1cc4e02013d0742edbd642bfc7f66f16af363af5500c5bb6675f081343e2f56"
PER_RUN_TIMEOUT_S = 300
BATCH_CAP_S = int(os.environ.get("STAGEB_CAP_S", str(6 * 3600)))  # A3: 6 h study cap minus Stage A wall time
WORKERS = int(os.environ.get("STAGEB_WORKERS", "3"))   # 3 as frozen; another value needs author approval
COND = {"T1": {"extraMap4Slow": 1}, "T2": {"mapSpacing": 100.0}, "T3": {"n4Rate": "EhtMcs4", "extraMap4": 2}}
screen = json.load(open(os.path.join(CC, "stage0/stage0_screen.json")))
plan = []
for cid, extra in COND.items():
    for r in screen[cid]["selected"]:
        x, y = r["pos"]
        for mode in ("slo", "mlo"):
            for sc in (1, 2):
                for s in range(1, 6):
                    a = dict(BASE); a.update({"linkMode": mode, "n4Rate": "EhtMcs0", "scenario": sc, "rngRun": s,
                                              "n5X": float(x), "n5Y": float(y)}); a.update(extra)
                    plan.append((f"B_{cid}_{mode}_x{x:g}_y{y:g}_MAP{1 if sc == 1 else 4}_s{s}", a))
assert len(plan) == 480 and len({t for t, _ in plan}) == 480
if "--dry" in sys.argv:
    for tag, _ in plan[:3] + plan[-2:]:
        print(tag)
    print(len(plan), "runs"); sys.exit(0)
os.makedirs(OUT, exist_ok=True)
logp = os.path.join(OUT, "stageB_log.json")
log = json.load(open(logp)) if os.path.exists(logp) else {"binary_sha256": sha(BIN), "workers": WORKERS, "runs": []}
done = {r["tag"] for r in log["runs"]}; t_start = time.time()


def one(item):
    tag, a = item
    if time.time() - t_start > BATCH_CAP_S:
        return {"tag": tag, "skipped": "batch cap reached"}
    argv = [f"--{k}={v}" for k, v in sorted(a.items())] + ["--diagFile=diag.txt"]
    assert not any(re.search(r"\s", x) for x in argv)
    rd = os.path.join(OUT, tag); os.makedirs(rd, exist_ok=True); t0 = time.time()
    with open(os.path.join(rd, "stdout.txt"), "w") as so, open(os.path.join(rd, "stderr.txt"), "w") as se:
        try:
            rc = subprocess.run(["nice", "-n", "15", BIN] + argv, cwd=rd, stdout=so, stderr=se, timeout=PER_RUN_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return {"tag": tag, "argv": argv, "exit": rc, "wall_s": round(time.time() - t0, 1),
            "My_absent": not os.path.exists(os.path.join(NS3, "My"))}


with ThreadPoolExecutor(WORKERS) as ex:
    for e in ex.map(one, [p for p in plan if p[0] not in done]):
        log["runs"].append(e); json.dump(log, open(logp, "w"), indent=1)
        print(e["tag"], e.get("exit", e.get("skipped")), e.get("wall_s"), flush=True)
print("DONE", len(log["runs"]))
