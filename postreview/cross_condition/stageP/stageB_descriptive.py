"""Descriptive per-context report for Stage B (post-analysis; NOT part of the frozen tests).
Reports per (cell, position): mean sum-log on MAP 1 and MAP 4, empirical oracle choice, AirtimeThr/RSSI choices per seed
(OWNSEED and SEEDMEAN), learner MAP-1 share, the airtime-model check (spec Sec. 4), and per-run N5/total throughput."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); CC = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(CC, "..", "..", "analysis")) if False else None
from stageB_analysis import parse  # reuses frozen import path
ch = json.load(open(os.path.join(HERE, "stageP_choices.json")))["choices"]
scr = json.load(open(os.path.join(CC, "stage0/stage0_screen.json")))
runs = os.path.join(CC, "stageB_runs"); out = {}; agree = {}
for cid in ("T1", "T2", "T3"):
    for mode in ("slo", "mlo"):
        rows = []; ag = 0
        for r in scr[cid]["selected"]:
            x, y = r["pos"]; R = {1: [], 4: []}
            for s in range(1, 6):
                for m in (1, 4):
                    o = parse(open(os.path.join(runs, f"B_{cid}_{mode}_x{x:g}_y{y:g}_MAP{m}_s{s}", "stdout.txt")).read())
                    R[m].append(o["sumLog"])
            m1, m4 = np.mean(R[1]), np.mean(R[4]); orc = 1 if m1 >= m4 else 4
            seedwin = sum(a > b for a, b in zip(R[1], R[4]))
            mb = r["model"][mode]["better"]; ag += (mb == orc)
            k = lambda v, s: f"{cid}|{mode}|{x}|{y}|{v}|s{s}"
            act = lambda a: 1 if a == 0 else 4
            rows.append({"pos": [x, y], "hidden": r["hidden"], "sumlog_MAP1": round(m1, 3), "sumlog_MAP4": round(m4, 3),
                         "oracle": orc, "seeds_MAP1_better": seedwin, "model_better": mb,
                         "model_robust": r["model"][mode]["robust_over_L_Toh"],
                         "thr_OWNSEED": [act(ch[k("OWNSEED", s)]["AirtimeThr"]) for s in range(1, 6)],
                         "thr_SEEDMEAN": act(ch[k("SEEDMEAN", 1)]["AirtimeThr"]),
                         "rssi": act(ch[k("SEEDMEAN", 1)]["RSSI"]),
                         "learner_MAP1_share_OWNSEED": {l: float(np.mean([a == 0 for s in range(1, 6) for a in ch[k("OWNSEED", s)][l]]))
                                                        for l in ("neural", "ucb1", "linucb")}})
        out[f"{cid}|{mode}"] = rows; agree[f"{cid}|{mode}"] = f"{ag}/{len(rows)}"
json.dump({"contexts": out, "model_oracle_agreement": agree}, open(os.path.join(CC, "STAGEB_DESCRIPTIVE.json"), "w"), indent=1)
for c, rows in out.items():
    print("==", c, "model-oracle agreement", agree[c])
    for r in rows:
        print(r["pos"], "M1 %.3f M4 %.3f" % (r["sumlog_MAP1"], r["sumlog_MAP4"]), "orc", r["oracle"], "seedsM1>", r["seeds_MAP1_better"],
              "model", r["model_better"], "rssi", r["rssi"], "thrSM", r["thr_SEEDMEAN"], "thrOS", r["thr_OWNSEED"],
              "lrnM1", {k: round(v, 2) for k, v in r["learner_MAP1_share_OWNSEED"].items()})
