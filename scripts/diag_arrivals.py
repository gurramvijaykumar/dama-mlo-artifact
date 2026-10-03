"""Per-trial view of the final network in the sequential-arrival experiment (pass 20 text).
Read-only; matches each trial's final placement to its run in runs.jsonl by --newSta."""
import json
from collections import defaultdict

from arrivals import sta_arg

byarg = defaultdict(list)
for line in open("results/runs.jsonl"):
    r = json.loads(line)
    a = r["args"]
    if "newSta" in a:
        byarg[(a["linkMode"], a["newSta"])].append(r["out"])
out = {}
for mode in ("mlo", "mloConfined"):
    d = json.load(open(f"results/arrivals_{mode}_EhtMcs0.json"))
    res = defaultdict(list)
    for key, placed in d["decisions"].items():
        t, n = key.split("|")
        cands = byarg[(mode, sta_arg([tuple(p) for p in placed]))]
        assert len(cands) >= 1, (mode, key)
        o = cands[0]
        tp = [v for k, v in o.items() if k.startswith("tput_")]
        res[n].append((int(t), o["sumLog"], min(tp)))
    rssi = {t: s for t, s, _ in res["RSSI"]}
    print(mode)
    out[mode] = {}
    for n, rows in res.items():
        g = sorted((t, s - rssi[t], m) for t, s, m in rows)
        starved = [t for t, _, m in g if m < 0.01]
        worst = min(g, key=lambda x: x[1])
        out[mode][n] = {"gain_by_trial": [x[1] for x in g], "starved_trials": starved}
        print(f"  {n:13s} starved trials {starved}  worst trial {worst[0]} gain {worst[1]:+.2f}  "
              f"gains>0 {sum(x[1] > 0 for x in g)}/{len(g)}")
json.dump(out, open("results/diag_arrivals.json", "w"), indent=1)
