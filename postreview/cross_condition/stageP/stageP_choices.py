#!/usr/bin/env python3
"""Stage P (desk, before any Stage B run): (1) health check of Stage A runs (F2 rules); (2) per condition, mode and
selected position, the context from the Stage A pre-arrival utilisation, with that condition's geometry; (3) the
choice of every policy, frozen: RSSI, LoadAware (true client counts), Airtime, AirtimeThr (delta 0.2), and the three
learners trained on the stored T0 grid (all 20 positions, 4000 rounds, 5 replicates, constrained, seed 1000*rep + 7).
Input variants: SEEDMEAN (utilisation averaged over the 5 seeds; the manuscript protocol) and OWNSEED (each seed's
own pre-arrival utilisation). Output: stageP_choices.json. No simulation."""
import json, os, re, sys
import numpy as np
REV = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2"
CC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REV); os.chdir(REV)
import policies as P, analyze as A  # noqa: E402
from simlib import parse  # noqa: E402
screen = json.load(open(os.path.join(CC, "stage0/stage0_screen.json")))
NCL = {"T1": (2, 3), "T2": (2, 2), "T3": (2, 4)}
SP = {"T1": 150.0, "T2": 100.0, "T3": 150.0}
RUNS = os.path.join(CC, "stageA_runs")
log = json.load(open(os.path.join(RUNS, "stageA_log.json")))
# (1) health (same rules as f2_masking/check_f2_validation.py)
health = {}
for e in log["runs"]:
    t = e["tag"]; f = []
    if e.get("skipped"): f.append("not run")
    elif e["exit"] != 0: f.append(f"exit {e['exit']}")
    if not e.get("My_absent", True): f.append("My created")
    if t.startswith("C_"):
        if e.get("mismatches"): f.append("control mismatch")
    elif e.get("exit") == 0:
        out = parse(open(os.path.join(RUNS, t, "stdout.txt")).read())
        f += [f"zero delivery {k[5:]} ({v} Mbit/s)" for k, v in out.items() if k.startswith("tput_") and v < 0.01]  # A2: < 0.01 Mbit/s
        last = {}; de = set()
        for line in open(os.path.join(RUNS, t, "diag.txt")):
            p = line.split()
            if len(p) > 2 and p[1] in ("ASSOC", "DEASSOC"):
                n = re.search(r"/NodeList/(\d+)/", p[2]).group(1); last[n] = (int(p[0]), p[1])
                if p[1] == "DEASSOC": de.add(n)
        nsta = sum(k.startswith("tput_") for k in out)
        if sum(1 for t_, ev in last.values() if ev == "ASSOC" and t_ <= 3e9) < nsta: f.append("association by 3 s incomplete")
        f += [f"DEASSOC node {n}" for n in sorted(de)]
    health[t] = f
# (2)-(3) contexts and choices
def util_of(cid, mode, s):
    o = parse(open(os.path.join(RUNS, f"A_{cid}_{mode}_pre_s{s}", "stdout.txt")).read())
    return [o.get("util_MAP1_L0", 0.0), o.get("util_MAP1_L1", 0.0), o.get("util_MAP4_L0", 0.0), o.get("util_MAP4_L1", 0.0)]
# learners trained once per mode on the stored T0 grid (geometry S = 150)
P.MAP_POS = {0: (0.0, 300.0), 1: (0.0, 150.0)}
idx = A.index(A.load_runs(None))
learned = {}
for mode in ("slo", "mlo"):
    data = A.build_dataset(idx, mode)
    train = [(c, rew) for k, (c, rew, _) in data.items()]
    learned[mode] = {k: [P.train_learner(k, train, 4000, seed=1000 * r + 7, constrained=True) for r in range(5)] for k in A.LEARNERS}
res = {"health": health, "choices": {}}
for cid in ("T1", "T2", "T3"):
    S = SP[cid]; P.MAP_POS = {0: (0.0, 2 * S), 1: (0.0, S)}
    for mode in ("slo", "mlo"):
        us = {s: util_of(cid, mode, s) for s in range(1, 6)}
        mean_u = list(np.mean(list(us.values()), axis=0))
        for r in screen[cid]["selected"]:
            x, y = r["pos"]
            for variant, uv in [("SEEDMEAN", {s: mean_u for s in us}), ("OWNSEED", us)]:
                for s in range(1, 6):
                    c = {"rssi": (P.rssi_dbm(x, y, 0), P.rssi_dbm(x, y, 1)), "util": list(uv[s]), "nlinks": 1 if mode == "slo" else 2,
                         "nclients": NCL[cid], "pos": (x, y)}
                    ch = {n: int(p(c)) for n, p in A.HEURISTICS.items()}
                    for k in A.LEARNERS:
                        ch[k] = [int(pol(c)) for pol in learned[mode][k]]
                    ch["J"] = P.feasible_actions(c)
                    res["choices"][f"{cid}|{mode}|{x}|{y}|{variant}|s{s}"] = ch
P.MAP_POS = {0: (0.0, 300.0), 1: (0.0, 150.0)}
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stageP_choices.json"), "w"), indent=1)
print("health flags:", {t: f for t, f in health.items() if f} or "none", "| runs checked:", len(health))
