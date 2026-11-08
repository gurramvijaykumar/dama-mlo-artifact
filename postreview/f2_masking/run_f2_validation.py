#!/usr/bin/env python3
"""F2 validation batch (F2_VALIDATION_SPEC.md). 26 runs of the Stage 1 diag build; NOT the F2 campaign.
Usage: python3 run_f2_validation.py   (resumable; writes runs/<tag>/ and runs/validation_log.json)"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
NS3 = "/home/vijay/ns-allinone-3.48/ns-3.48"
REV = os.path.join(NS3, "My Research Papers/revision_v2"); HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "runs"); BIN = os.path.join(NS3, "build/scratch/ns3.48-dama-mlo-v20-diag-optimized")
sys.path.insert(0, REV); sys.path.insert(0, os.path.join(REV, "desk_checks_2026-11-03/stage1"))
from simlib import BASE, parse  # noqa: E402
import analyze as A  # noqa: E402


def grid_pre_record(mode, seed):
    """The unique stored v2.0 grid pre-arrival record (scenario 0, EhtMcs0, no newSta). run_stage1.stored() also
    matched the four C6 arrival runs (mlo, scenario 0, seed 1, with newSta); they are excluded here, and the result
    must equal the record analyze.py (and F1) uses."""
    hits = []
    for l in open(os.path.join(REV, "results/runs.jsonl")):
        r = json.loads(l); a = r["args"]
        if ("codeVersion" not in r and "newSta" not in a and a.get("linkMode") == mode and a.get("n4Rate") == "EhtMcs0"
                and int(a.get("scenario", -1)) == 0 and int(a["rngRun"]) == seed
                and all(str(a.get(k)) == str(v) for k, v in BASE.items() if k not in ("linkMode", "n4Rate"))):
            hits.append(r)
    assert len(hits) == 1, (mode, seed, len(hits))
    ref = A.index(A.load_runs(None))[(mode, "EhtMcs0", 0, None, None, seed)]
    assert hits[0]["out"] == ref
    return hits[0]


sha = lambda p: subprocess.run(["sha256sum", p], capture_output=True, text=True).stdout.split()[0]
assert sha(BIN) == "746687e279fa6de6164f2acbd3a4f0f796ea4bf56c1026152d4849b93e5c9267"
PER_RUN_TIMEOUT_S, BATCH_CAP_S, WORKERS = 300, 1800, 3
EXTRA = [(-20.0, 300.0), (0.0, 280.0), (-14.1, 314.1), (-14.1, 285.9)]  # fast stations on MAP 1, in this order
POS = (40.0, 195.0)


def new_sta(k):
    return ",".join(f"{x:.1f}:{y:.1f}:1" for x, y in EXTRA[:k])


def args(mode, sc, k, seed):
    a = {kk: v for kk, v in BASE.items()}
    a.update({"linkMode": mode, "n4Rate": "EhtMcs0", "scenario": sc, "rngRun": seed, "newSta": new_sta(k)})
    if sc:
        a.update({"n5X": POS[0], "n5Y": POS[1]})
    return a


plan = []
for k in (1, 2, 4):
    for mode in ("slo", "mlo"):
        for seed in (101, 102):
            plan.append((f"A_k{k}_{mode}_pre_s{seed}", args(mode, 0, k, seed), None))       # V-A
        for sc in (1, 2):
            plan.append((f"B_k{k}_{mode}_MAP{1 if sc == 1 else 4}_s101", args(mode, sc, k, 101), None))  # V-B
for mode, seed in (("slo", 1), ("mlo", 1)):  # V-C (references fixed before execution; see spec Sec. 3)
    rec = grid_pre_record(mode, seed)
    plan.append((f"C_{mode}_pre_s{seed}_stored", dict(rec["args"]), rec["out"]))
assert len(plan) == 26
if "--dry" in sys.argv:
    for tag, a, _ in plan:
        print(tag, " ".join(f"--{k}={v}" for k, v in sorted(a.items()) if k in ("linkMode", "scenario", "rngRun", "n5X", "n5Y", "newSta")))
    sys.exit(0)
os.makedirs(OUT, exist_ok=True)
logp = os.path.join(OUT, "validation_log.json")
log = json.load(open(logp)) if os.path.exists(logp) else {"binary_sha256": sha(BIN), "runs": []}
done = {r["tag"] for r in log["runs"]}
t_start = time.time()


def one(item):
    tag, a, ref = item
    if time.time() - t_start > BATCH_CAP_S:
        return {"tag": tag, "skipped": "batch cap reached"}
    argv = [f"--{k}={v}" for k, v in sorted(a.items()) if v != ""] + ["--diagFile=diag.txt"]
    assert not any(re.search(r"\s", x) for x in argv)
    rd = os.path.join(OUT, tag); os.makedirs(rd, exist_ok=True); t0 = time.time()
    with open(os.path.join(rd, "stdout.txt"), "w") as so, open(os.path.join(rd, "stderr.txt"), "w") as se:
        try:
            rc = subprocess.run(["nice", "-n", "15", BIN] + argv, cwd=rd, stdout=so, stderr=se,
                                timeout=PER_RUN_TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    out = parse(open(os.path.join(rd, "stdout.txt")).read()) if rc == 0 else {}
    e = {"tag": tag, "argv": argv, "exit": rc, "wall_s": round(time.time() - t0, 1), "n_fields": len(out),
         "My_absent": not os.path.exists(os.path.join(NS3, "My"))}
    if ref is not None:
        e["mismatches"] = [(k, ref.get(k), out.get(k)) for k in sorted(set(ref) | set(out)) if ref.get(k) != out.get(k)]
    return e


todo = [p for p in plan if p[0] not in done]
with ThreadPoolExecutor(WORKERS) as ex:
    for e in ex.map(one, todo):
        log["runs"].append(e); json.dump(log, open(logp, "w"), indent=1)
        print(e["tag"], e.get("exit", e.get("skipped")), e.get("wall_s"), flush=True)
print("DONE", len(log["runs"]), "records")
