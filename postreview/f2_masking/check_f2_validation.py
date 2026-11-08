#!/usr/bin/env python3
"""Applies the frozen pass/fail rules of F2_VALIDATION_SPEC.md to runs/ (no simulation). -> F2_VALIDATION_CHECK.json"""
import json, os, re, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); RUNS = os.path.join(HERE, "runs")
sys.path.insert(0, "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2")
from simlib import parse  # noqa: E402
import policies as P  # noqa: E402
import analyze as A  # noqa: E402
POS = (40.0, 195.0)
log = json.load(open(os.path.join(RUNS, "validation_log.json")))
res = {"runs": {}, "masking": {}}
for e in log["runs"]:
    tag = e["tag"]; r = {"exit": e.get("exit"), "fail": [], "warn": [], "diagnosis": "not needed"}
    if e.get("skipped"):
        r["fail"].append("not run: " + e["skipped"]); res["runs"][tag] = r; continue
    if e["exit"] != 0:
        r["fail"].append(f"exit {e['exit']}")
    if not e["My_absent"]:
        r["fail"].append("ns-3.48/My created")
    rd = os.path.join(RUNS, tag); out = parse(open(os.path.join(rd, "stdout.txt")).read()) if e["exit"] == 0 else {}
    if tag.startswith("C_"):
        if e.get("mismatches"):
            r["fail"].append(f"control mismatch in {len(e['mismatches'])} fields")
    else:
        tput = {k[5:]: v for k, v in out.items() if k.startswith("tput_")}
        r["tput"] = tput
        r["fail"] += [f"zero delivery {n}" for n, v in tput.items() if v <= 0]
        last = {}; first_tput = {}; deassoc = set()
        dpath = os.path.join(rd, "diag.txt")
        for line in open(dpath) if os.path.exists(dpath) else []:
            p = line.split()
            if len(p) > 2 and p[1] in ("ASSOC", "DEASSOC"):
                node = re.search(r"/NodeList/(\d+)/", p[2]).group(1); last[node] = (int(p[0]), p[1])
                if p[1] == "DEASSOC":
                    deassoc.add(node)
            elif len(p) > 4 and p[1] == "TPUT" and float(p[4]) > 0:
                first_tput.setdefault(p[2], int(p[3]))
        n_sta = len(tput)
        assoc_ok = [n for n, (t, ev) in last.items() if ev == "ASSOC" and t <= 3e9]
        if len(assoc_ok) < n_sta:
            r["fail"].append(f"associated by 3 s and not deassociated: {len(assoc_ok)}/{n_sta} stations")
        r["fail"] += [f"deassociation of node {n} (matches the case-A watchdog pattern; cause NOT established without trace)" for n in sorted(deassoc)]
        # late start = first non-zero 1 s delivery bin after bin 1 (indicator of STATE1_STARTUP_CHECK.md); warning only
        r["warn"] += [f"late first delivery {n} at {s} s" for n, s in first_tput.items() if s > 1]
        if tag.startswith("A_"):
            r["util"] = {k[5:]: v for k, v in out.items() if k.startswith("util_")}
    r["pass"] = not r["fail"]
    if r["fail"]:
        r["diagnosis"] = "PENDING: health flag, not a simulator defect until diagnosed (contention / implementation / undiagnosed)"
    res["runs"][tag] = r
# masking precondition M (V-A only): M1 similar utilisation AND M2 the actual AirtimeThr decision at delta = 0.2
thr = A.HEURISTICS["AirtimeThr"]; rssi = A.HEURISTICS["RSSI"]
for k in (1, 2, 4):
    for mode in ("slo", "mlo"):
        nl = 1 if mode == "slo" else 2; rows = []
        for s_ in (101, 102):
            u = res["runs"].get(f"A_k{k}_{mode}_pre_s{s_}", {}).get("util")
            if not u:
                continue
            uv = [u["MAP1_L0"], u.get("MAP1_L1", 0.0), u["MAP4_L0"], u.get("MAP4_L1", 0.0)]
            u1 = sum(uv[0:nl]) / nl; u4 = sum(uv[2:2 + nl]) / nl
            ctx = {"rssi": (P.rssi_dbm(*POS, 0), P.rssi_dbm(*POS, 1)), "util": uv, "nlinks": nl,
                   "nclients": (2 + k, 2), "pos": POS}
            rows.append({"seed": s_, "u1": round(u1, 4), "u4": round(u4, 4), "abs_diff": round(abs(u4 - u1), 4),
                         "J": P.feasible_actions(ctx), "rssi_choice": rssi(ctx), "thr_choice": thr(ctx)})
        m1 = len(rows) == 2 and all(r_["abs_diff"] <= 0.15 for r_ in rows)
        m2 = len(rows) == 2 and all(r_["J"] == [0, 1] and r_["rssi_choice"] == 1 and r_["thr_choice"] == 1 for r_ in rows)
        res["masking"][f"k{k}|{mode}"] = {"rows": rows, "M1_similar": m1, "M2_thr_keeps_MAP4": m2,
                                         "masking_candidate": m1 and m2}
res["health_pass"] = all(r["pass"] for t, r in res["runs"].items())
res["n_runs"] = len(res["runs"])
json.dump(res, open(os.path.join(HERE, "F2_VALIDATION_CHECK.json"), "w"), indent=1)
print(json.dumps({"health_pass": res["health_pass"], "n_runs": res["n_runs"], "masking": res["masking"],
                  "fails": {t: r["fail"] for t, r in res["runs"].items() if r["fail"]}}, indent=1))
