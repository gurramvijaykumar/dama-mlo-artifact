#!/usr/bin/env python3
"""Stage B analysis (CROSS_CONDITION_SPEC.md Sec. 5-6 + SPEC_ERRATA_AND_AMENDMENTS.md). Frozen before any Stage B run.
  --check-wrapper  geometry wrapper at S = 150 reproduces stored T0 policy results (policies.json) exactly
  --selftest       runs the whole pipeline on T0 descriptive cells (stored grid, N4 EhtMcs0, rule positions)
  (default)        analyses stageB_runs with the frozen choices (variant SEEDMEAN primary, OWNSEED sensitivity)
Estimands per context and seed: G = oracle - RSSI, D = Thr - RSSI, S = oracle - Thr, L_l = learner - Thr.
Fixed rules: two-stage bootstrap (positions, then seeds), B = 10000, seed 20261108. Learners: three-stage (positions,
training replicates, seeds). One-sided p = (1 + #{theta* on the null side of c}) / (B + 1). Holm within each family at
0.025. A run with no output removes that seed from both arms of its context (manuscript rule)."""
import json, math, os, sys
import numpy as np
REV = "/home/vijay/ns-allinone-3.48/ns-3.48/My Research Papers/revision_v2"
HERE = os.path.dirname(os.path.abspath(__file__)); CC = os.path.dirname(HERE)
sys.path.insert(0, REV); os.chdir(REV)
import policies as P, analyze as A  # noqa: E402
from simlib import parse  # noqa: E402
B, SEED, ALPHA = 10000, 20261108, 0.025
LRN = {"neural": "DAMA-MLO", "ucb1": "UCB1", "linucb": "LinUCB"}
DN = {"T0": 0.05, "T1": 0.06, "T2": 0.05, "T3": 0.07}


def boot2(groups):
    """groups: list (positions) of 1-D arrays (per-seed values of one context). Returns (point, samples)."""
    rng = np.random.default_rng(SEED); n = len(groups)
    point = float(np.mean([g.mean() for g in groups]))
    out = np.empty(B)
    for b in range(B):
        pos = rng.integers(n, size=n)
        out[b] = np.mean([groups[i][rng.integers(len(groups[i]), size=len(groups[i]))].mean() for i in pos])
    return point, out


def boot3(groups):
    """groups: list of 2-D arrays [replicate, seed]. Positions, then replicates, then seeds are resampled."""
    rng = np.random.default_rng(SEED); n = len(groups)
    point = float(np.mean([g.mean() for g in groups]))
    out = np.empty(B)
    for b in range(B):
        vals = []
        for i in rng.integers(n, size=n):
            g = groups[i]; R, S_ = g.shape
            reps = g[rng.integers(R, size=R)]
            vals.append(reps[:, rng.integers(S_, size=S_)].mean())
        out[b] = np.mean(vals)
    return point, out


def summ(point, s):
    return {"est": point, "lo": float(np.percentile(s, 2.5)), "hi": float(np.percentile(s, 97.5)),
            "p_gt": None, "p_lt": None}


def p_gt(s, c): return (1 + np.sum(s <= c)) / (B + 1)   # H1: theta > c
def p_lt(s, c): return (1 + np.sum(s >= c)) / (B + 1)   # H1: theta < c


def holm(pvals):
    """pvals: {key: p}. Returns {key: rejected} at ALPHA, Holm step-down."""
    order = sorted(pvals, key=pvals.get); rej = {k: False for k in pvals}; m = len(order)
    for i, k in enumerate(order):
        if pvals[k] <= ALPHA / (m - i):
            rej[k] = True
        else:
            break
    return rej


def cell_stats(ctxs, dN):
    """ctxs: list of dicts with rew[a] (per-seed arrays), choices (thr, rssi, learners as [rep] lists), J."""
    G, D, S_, Lg = [], [], [], {l: [] for l in LRN}
    dep = []
    for c in ctxs:
        rew = c["rew"]; o = max(c["J"], key=lambda a: rew[a].mean())
        thr, rs = c["thr"], c["rssi"]
        G.append(rew[o] - rew[rs]); D.append(rew[thr] - rew[rs]); S_.append(rew[o] - rew[thr]); dep.append(thr != rs)
        for l in LRN:
            Lg[l].append(np.array([rew[a] - rew[thr] for a in c["lrn"][l]]))
    res = {"n_pos": len(ctxs), "departure_rate": float(np.mean(dep)), "dN": dN}
    for name, grp in (("G", G), ("D", D), ("S", S_)):
        pt, s = boot2(grp); r = summ(pt, s)
        r["p_gt_dN"] = p_gt(s, dN); r["p_lt_dN"] = p_lt(s, dN); r["p_gt_0"] = p_gt(s, 0.0); r["p_lt_0"] = p_lt(s, 0.0)
        res[name] = r
    for l in LRN:
        pt, s = boot3(Lg[l]); r = summ(pt, s); r["p_gt_dN"] = p_gt(s, dN); r["p_lt_dN"] = p_lt(s, dN)
        r["train_sd"] = float(np.std([g.mean(axis=1) for g in Lg[l]], axis=1).mean()) if len(Lg[l][0]) > 1 else None
        res["L_" + l] = r
    return res


def families(cells):
    """cells: {cellkey: cell_stats}. Holm families of the spec (T0 excluded)."""
    ks = [k for k in cells if not k.startswith("T0")]
    fam = {
        "F-G": holm({k: cells[k]["G"]["p_gt_dN"] for k in ks}),
        "F-D+": holm({k: cells[k]["D"]["p_gt_0"] for k in ks}),
        "F-D-": holm({k: cells[k]["D"]["p_lt_0"] for k in ks}),
        "F-S": holm({k: cells[k]["S"]["p_lt_dN"] for k in ks}),
        "F-B": holm({k: cells[k]["S"]["p_gt_dN"] for k in ks}),
        "F-L+": holm({f"{k}|{l}": cells[k]["L_" + l]["p_gt_dN"] for k in ks for l in LRN}),
        "F-L0": holm({f"{k}|{l}": cells[k]["L_" + l]["p_lt_dN"] for k in ks for l in LRN}),
    }
    verdict = {}
    for k in ks:
        if fam["F-B"][k]:
            v = "FAILS"
        elif fam["F-S"][k]:
            v = "SUFFICIENT" if fam["F-G"][k] else "SUFFICIENT BUT UNINFORMATIVE (no demonstrated available gain)"
        else:
            v = "INCONCLUSIVE"
        verdict[k] = {"AirtimeThr": v, "intervention": "helps" if fam["F-D+"][k] else "harms" if fam["F-D-"][k] else "not shown"}
    return fam, verdict


def check_wrapper():
    P.MAP_POS = {0: (0.0, 300.0), 1: (0.0, 150.0)}
    st = json.load(open(os.path.join(REV, "results/policies.json"))); idx = A.index(A.load_runs(None)); bad = []
    for mode in ("slo", "mlo", "mloConfined"):
        data = A.build_dataset(idx, mode)
        for n, pol in A.HEURISTICS.items():
            s = A.summarize(A.evaluate_policy_choices(data, lambda k, c, p=pol: p(c)))
            if abs(s["mean_sumLog_gain_vs_rssi"][0] - st[mode][n]["mean_sumLog_gain_vs_rssi"][0]) > 0:
                bad.append((mode, n))
    print("wrapper at S=150 reproduces stored fixed-rule gains exactly:", not bad, bad)
    return not bad


def t0_cells():
    """T0 descriptive cells: stored grid, N4 EhtMcs0, positions satisfying the Sec. 3 J/RSSI rule; learners trained on
    the whole T0 grid (in-sample, so descriptive only)."""
    P.MAP_POS = {0: (0.0, 300.0), 1: (0.0, 150.0)}
    idx = A.index(A.load_runs(None)); cells = {}
    from experiments import GRID_X, GRID_Y
    for mode in ("slo", "mlo"):
        data = A.build_dataset(idx, mode); train = [(c, rew) for k, (c, rew, _) in data.items()]
        L = {k: [P.train_learner(k, train, 4000, seed=1000 * r + 7, constrained=True) for r in range(5)] for k in LRN}
        ctxs = []
        for x in GRID_X:
            for y in GRID_Y:
                c, rew, _ = data[("EhtMcs0", x, y)]
                ok = all(P.weakest_link_rssi(dict(c), ap) >= -81.0 for ap in (0, 1)) and P.rssi_dbm(x, y, 1) > P.rssi_dbm(x, y, 0)
                if not ok:
                    continue
                ctxs.append({"rew": {0: np.array(rew[0]), 1: np.array(rew[1])}, "J": P.feasible_actions(c),
                             "thr": A.HEURISTICS["AirtimeThr"](c), "rssi": A.HEURISTICS["RSSI"](c),
                             "lrn": {k: [int(p(c)) for p in L[k]] for k in LRN}})
        cells[f"T0|{mode}"] = cell_stats(ctxs, DN["T0"])
    return cells


def stageB_cells(variant="SEEDMEAN"):
    ch = json.load(open(os.path.join(HERE, "stageP_choices.json")))["choices"]
    screen = json.load(open(os.path.join(CC, "stage0/stage0_screen.json")))
    runs = os.environ.get("STAGEB_RUNS_DIR", os.path.join(CC, "stageB_runs")); cells = {}  # env override: tests only
    for cid in ("T1", "T2", "T3"):
        for mode in ("slo", "mlo"):
            ctxs = []
            for r in screen[cid]["selected"]:
                x, y = r["pos"]; rew = {0: [], 1: []}; keep = []
                for s in range(1, 6):
                    vals = []
                    for a, m in ((0, 1), (1, 4)):
                        f = os.path.join(runs, f"B_{cid}_{mode}_x{x:g}_y{y:g}_MAP{m}_s{s}", "stdout.txt")
                        o = parse(open(f).read()) if os.path.exists(f) else {}
                        vals.append(o.get("sumLog"))
                    if None not in vals:
                        rew[0].append(vals[0]); rew[1].append(vals[1]); keep.append(s)
                if not keep:
                    continue
                kk = [f"{cid}|{mode}|{x}|{y}|{variant}|s{s}" for s in keep]
                # per-seed choices (OWNSEED may differ by seed): reward of seed s uses the choice for seed s
                thr = [ch[k]["AirtimeThr"] for k in kk]; rs = [ch[k]["RSSI"] for k in kk]
                R = {a: np.array(rew[a]) for a in (0, 1)}
                pick = lambda acts: np.array([R[a][i] for i, a in enumerate(acts)])
                ctx = {"J": ch[kk[0]]["J"], "R": R, "thr_v": pick(thr), "rssi_v": pick(rs),
                       "dep": float(np.mean([t != r_ for t, r_ in zip(thr, rs)])),
                       "lrn_v": {l: np.array([pick([ch[k][l][rep] for k in kk]) for rep in range(5)]) for l in LRN}}
                ctxs.append(ctx)
            cells[f"{cid}|{mode}"] = cell_stats_v(ctxs, DN[cid])
    return cells


def cell_stats_v(ctxs, dN):
    """As cell_stats, with per-seed chosen-reward vectors already resolved (allows per-seed choices)."""
    conv = []
    for c in ctxs:
        o = max(c["J"], key=lambda a: c["R"][a].mean())
        conv.append({"rew": {"o": c["R"][o], "t": c["thr_v"], "r": c["rssi_v"], **{f"l{l}{i}": c["lrn_v"][l][i] for l in LRN for i in range(5)}},
                     "J": ["o"], "thr": "t", "rssi": "r", "lrn": {l: [f"l{l}{i}" for i in range(5)] for l in LRN}})
    res = cell_stats(conv, dN)
    res["departure_rate"] = float(np.mean([c["dep"] for c in ctxs]))   # share of (context, seed) choices with Thr != RSSI
    return res


if __name__ == "__main__":
    if "--check-wrapper" in sys.argv:
        sys.exit(0 if check_wrapper() else 1)
    if "--selftest" in sys.argv:
        cells = t0_cells()
        for k, v in cells.items():
            print(k, "n_pos", v["n_pos"], "dep %.2f" % v["departure_rate"],
                  {n: "%.3f [%.3f, %.3f]" % (v[n]["est"], v[n]["lo"], v[n]["hi"]) for n in ("G", "D", "S", "L_neural", "L_ucb1", "L_linucb")})
        print("holm self-test:", holm({"a": 0.001, "b": 0.02, "c": 0.013}))
        sys.exit(0)
    out = {}
    for variant in ("SEEDMEAN", "OWNSEED"):
        cells = stageB_cells(variant); fam, ver = families(cells)
        out[variant] = {"cells": cells, "families": fam, "verdicts": ver}
    out["T0_descriptive"] = t0_cells()
    json.dump(out, open(os.path.join(CC, "STAGEB_RESULTS.json"), "w"), indent=1, default=float)
    print(json.dumps(out["SEEDMEAN"]["verdicts"], indent=1))
