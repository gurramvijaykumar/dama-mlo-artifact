#!/usr/bin/env python3
"""Stage A of CROSS_CONDITION_SPEC.md: 4 v2.2 controls (defaults, must equal stored v2.0 records field for field) and
30 pre-arrival runs (T1-T3 x slo/mlo x seeds 1-5). v2.2 diag build. Resumable. --dry prints the plan.
Usage: python3 run_stageA.py [--dry]"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
NS3 = "/home/vijay/ns-allinone-3.48/ns-3.48"
REV = os.path.join(NS3, "My Research Papers/revision_v2"); HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "stageA_runs"); BIN = os.path.join(NS3, "build/scratch/ns3.48-dama-mlo-v22-diag-optimized")
sys.path.insert(0, REV)
from simlib import BASE, parse  # noqa: E402
import analyze as A  # noqa: E402
sha = lambda p: subprocess.run(["sha256sum", p], capture_output=True, text=True).stdout.split()[0]
assert sha(BIN) == "f1cc4e02013d0742edbd642bfc7f66f16af363af5500c5bb6675f081343e2f56"
PER_RUN_TIMEOUT_S, BATCH_CAP_S, WORKERS = 300, 1800, 3
COND = {"T1": {"extraMap4Slow": 1}, "T2": {"mapSpacing": 100.0}, "T3": {"n4Rate": "EhtMcs4", "extraMap4": 2}}


def stored_record(mode, sc, x, y, seed):
    """Unique stored v2.0 grid record (no newSta, no extra args), equal to the one analyze.py uses."""
    hits = []
    for l in open(os.path.join(REV, "results/runs.jsonl")):
        r = json.loads(l); a = r["args"]
        if ("codeVersion" not in r and set(a) <= set(BASE) | {"scenario", "rngRun", "n5X", "n5Y"}
                and a.get("linkMode") == mode and a.get("n4Rate") == "EhtMcs0" and int(a.get("scenario", -1)) == sc
                and int(a["rngRun"]) == seed and (sc == 0 or (float(a["n5X"]), float(a["n5Y"])) == (x, y))
                and all(str(a.get(k)) == str(v) for k, v in BASE.items() if k not in ("linkMode", "n4Rate"))):
            hits.append(r)
    assert len(hits) == 1, (mode, sc, x, y, seed, len(hits))
    ref = A.index(A.load_runs(None))[(mode, "EhtMcs0", sc, x if sc else None, y if sc else None, seed)]
    assert hits[0]["out"] == ref
    return hits[0]


plan = []
for mode in ("slo", "mlo"):
    for sc, x, y in ((0, None, None), (2, 40.0, 195.0)):
        rec = stored_record(mode, sc, x, y, 1)
        plan.append((f"C_{mode}_sc{sc}_s1", dict(rec["args"]), rec["out"]))
for cid, extra in COND.items():
    for mode in ("slo", "mlo"):
        for s in range(1, 6):
            a = dict(BASE); a.update({"linkMode": mode, "n4Rate": "EhtMcs0", "scenario": 0, "rngRun": s}); a.update(extra)
            plan.append((f"A_{cid}_{mode}_pre_s{s}", a, None))
assert len(plan) == 34
if "--dry" in sys.argv:
    for tag, a, _ in plan:
        print(tag, " ".join(f"--{k}={v}" for k, v in sorted(a.items()) if k in ("linkMode", "scenario", "rngRun", "n5X", "n5Y", "n4Rate", "extraMap4", "extraMap4Slow", "mapSpacing")))
    sys.exit(0)
os.makedirs(OUT, exist_ok=True)
logp = os.path.join(OUT, "stageA_log.json")
log = json.load(open(logp)) if os.path.exists(logp) else {"binary_sha256": sha(BIN), "runs": []}
done = {r["tag"] for r in log["runs"]}; t_start = time.time()


def one(item):
    tag, a, ref = item
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
    out = parse(open(os.path.join(rd, "stdout.txt")).read()) if rc == 0 else {}
    e = {"tag": tag, "argv": argv, "exit": rc, "wall_s": round(time.time() - t0, 1), "n_fields": len(out),
         "My_absent": not os.path.exists(os.path.join(NS3, "My"))}
    if ref is not None:
        e["mismatches"] = [(k, ref.get(k), out.get(k)) for k in sorted(set(ref) | set(out)) if ref.get(k) != out.get(k)]
    return e


todo = [p for p in plan if p[0] not in done]
if "--controls-only" in sys.argv:          # amendment A1: controls are run and verified before the pre-arrival runs
    todo = [p for p in todo if p[0].startswith("C_")]
else:
    ctl = [r for r in log["runs"] if r["tag"].startswith("C_")]
    assert len(ctl) == 4 and all(r["exit"] == 0 and not r.get("mismatches") and r["My_absent"] for r in ctl), \
        "controls missing or not identical: STOP (spec Sec. 8)"
with ThreadPoolExecutor(WORKERS) as ex:
    for e in ex.map(one, todo):
        log["runs"].append(e); json.dump(log, open(logp, "w"), indent=1)
        print(e["tag"], e.get("exit", e.get("skipped")), e.get("wall_s"), flush=True)
print("DONE", len(log["runs"]))
