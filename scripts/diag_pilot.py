"""Steady-state check (pass 20 text): 30 s pilot runs vs the 10 s runs with the same
arguments and seed. Read-only; prints a summary and writes results/diag_pilot.json."""
import json
from collections import defaultdict

import numpy as np

from simlib import record_version

KEYS = ("linkMode", "n4Rate", "scenario", "n5X", "n5Y", "rngRun")
pilot, short = {}, defaultdict(dict)
for line in open("results/runs.jsonl"):
    r = json.loads(line)
    a, o = r["args"], r["out"]
    if "newSta" in a:
        continue
    base = (str(a.get("backhaulWidth")) == "80" and str(a.get("useTcp")) == "true"
            and str(a.get("downlink")) == "false" and float(a.get("staDist", 20)) == 20.0)
    if not base:
        continue
    k = tuple(str(a.get(x)) for x in KEYS)
    if a.get("simTime") == 33.0:
        pilot[k] = o
    elif a.get("simTime") == 13.0:
        short[k][record_version(r)] = o
rows = []
for k, o in sorted(pilot.items()):
    s = short[k].get("2.1") or short[k].get("2.0")
    ver = "2.1" if "2.1" in short[k] else ("2.0" if s else None)
    tr = np.array(o["tputTrace"])
    early = tr[(tr[:, 0] > 3) & (tr[:, 0] <= 13), 1].mean()
    late = tr[(tr[:, 0] > 13) & (tr[:, 0] <= 33), 1].mean()
    rows.append({"key": k, "short_version": ver,
                 "sumLog30": o["sumLog"], "sumLog10": s["sumLog"] if s else None,
                 "tputN5_30": o["tput_N5"], "tputN5_10": s["tput_N5"] if s else None,
                 "agg_3_13": float(early), "agg_13_33": float(late)})
json.dump(rows, open("results/diag_pilot.json", "w"), indent=1)
for r in rows:
    d = None if r["sumLog10"] is None else r["sumLog30"] - r["sumLog10"]
    print(r["key"], r["short_version"], f"30s {r['sumLog30']:.3f}",
          "10s", None if d is None else f"{r['sumLog10']:.3f} d={d:+.3f}",
          f"N5 {r['tputN5_30']:.2f}/{r['tputN5_10']}", f"agg {r['agg_3_13']:.1f}->{r['agg_13_33']:.1f}")
# ranking MAP1 vs MAP4 per (mode, position), 30 s vs 10 s, means over seeds
grp = defaultdict(lambda: defaultdict(list))
for r in rows:
    mode, _, sc, x, y, s = r["key"]
    grp[(mode, x, y)][sc].append(r)
print()
for g, v in sorted(grp.items()):
    m30 = np.mean([r["sumLog30"] for r in v["1"]]) - np.mean([r["sumLog30"] for r in v["2"]])
    m10 = np.mean([r["sumLog10"] for r in v["1"]]) - np.mean([r["sumLog10"] for r in v["2"]])
    print(g, f"MAP1-MAP4 30s {m30:+.3f}  10s {m10:+.3f}")
d = [abs(r["sumLog30"] - r["sumLog10"]) for r in rows if r["sumLog10"] is not None]
print("n", len(d), "median |d|", np.median(d), "max", max(d))
