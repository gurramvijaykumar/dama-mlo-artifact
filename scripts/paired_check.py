"""Paired-test and multiplicity check of the named-state comparisons (no new simulations).

The tables compare MAP 1 and MAP 4 with Welch's t-test, although both options of a
state share the seed index. This script repeats every comparison with a paired t-test
on the shared seeds and applies a Holm correction within each table, and reports how
many detected/not-detected decisions change.

  python3 paired_check.py   -> results/paired_check.json
"""

import json
import os

import numpy as np
from scipy import stats

import analyze as A
import make_tables_figs as T
from experiments import LINK_MODES, STATE_SEEDS, STATES


def holm(ps):
    order = np.argsort(ps)
    m = len(ps)
    adj = np.empty(m)
    run = 0.0
    for i, j in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[j]))
        adj[j] = run
    return adj


def compare(filters, version, modes):
    idx = A.index(A.load_runs(filters, version))
    out = []
    for mode in modes:
        for st in STATES:
            x, y, rate = st["n5X"], st["n5Y"], st["n4Rate"]
            common = [s for s in STATE_SEEDS
                      if (mode, rate, 1, x, y, s) in idx and (mode, rate, 2, x, y, s) in idx]
            if len(common) < 2:
                continue
            for metric in ("sumLog", "sumTput"):
                a = np.array([idx[(mode, rate, 1, x, y, s)][metric] for s in common])
                b = np.array([idx[(mode, rate, 2, x, y, s)][metric] for s in common])
                pw = float(stats.ttest_ind(a, b, equal_var=False).pvalue)
                d = a - b
                pp = 1.0 if np.allclose(d, d[0]) and d[0] == 0 else float(stats.ttest_rel(a, b).pvalue)
                out.append({"mode": mode, "state": st["id"], "metric": metric, "n": len(common),
                            "delta": float(d.mean()), "p_welch": pw, "p_paired": pp})
    return out


def main():
    sets = {"states_v20": ({}, A.LEGACY_VERSION, LINK_MODES),
            "base_v21_80MHz": ({}, T.CODE_VERSION, T.SENS_MODES)}
    for w in (20, 160):
        sets[f"backhaul_{w}MHz"] = ({"backhaulWidth": w}, T.CODE_VERSION, T.SENS_MODES)
    for label, f in T.SENS[1:]:
        sets["sens_" + label.split()[0]] = (f, T.CODE_VERSION, T.SENS_MODES)
    res, summ = {}, {}
    for name, (f, ver, modes) in sets.items():
        rows = compare(f, ver, modes)
        for metric in ("sumLog", "sumTput"):
            sub = [r for r in rows if r["metric"] == metric]
            for r, ph in zip(sub, holm([r["p_welch"] for r in sub])):
                r["p_welch_holm"] = float(ph)
            for r, ph in zip(sub, holm([r["p_paired"] for r in sub])):
                r["p_paired_holm"] = float(ph)
        res[name] = rows
        s = {}
        for metric in ("sumLog", "sumTput"):
            sub = [r for r in rows if r["metric"] == metric]
            det = lambda k: [r[k] < 0.05 for r in sub]
            s[metric] = {
                "n": len(sub),
                "welch_detected": sum(det("p_welch")),
                "paired_detected": sum(det("p_paired")),
                "paired_vs_welch_changed": [(r["mode"], r["state"]) for r in sub
                                            if (r["p_welch"] < 0.05) != (r["p_paired"] < 0.05)],
                "welch_holm_detected": sum(det("p_welch_holm")),
                "welch_lost_under_holm": [(r["mode"], r["state"]) for r in sub
                                          if r["p_welch"] < 0.05 <= r["p_welch_holm"]],
            }
        summ[name] = s
    with open(os.path.join(A.OUT, "paired_check.json"), "w") as fh:
        json.dump({"summary": summ, "rows": res}, fh, indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
