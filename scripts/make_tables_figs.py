"""Tables and figures for the revised DAMA-MLO manuscript.

Reads results/runs.jsonl (and results/arrivals_*.json) and writes
  tables/tab_*.tex    LaTeX fragments (booktabs) to \\input in the manuscript
  figures/fig_*.pdf   matplotlib figures (vector, print widths)
  tables/STATUS.txt   coverage of every sweep the tables depend on
  tables/preview.pdf  every table and figure on a few pages, for checking

Works on partial data: missing cells print "--", a table or figure whose
sweep has no runs yet is skipped (listed in STATUS.txt), and while any sweep
is incomplete every output is stamped PARTIAL and analyze.py writes its JSON
with a _partial suffix, so the final results/*.json are never overwritten
by a preview.

  python3 make_tables_figs.py              final settings (5 learner replicates)
  python3 make_tables_figs.py --reps 1     quick preview (~3 min on the full grid)
  python3 make_tables_figs.py --no-learners
"""

import argparse
import warnings
import glob
import json
import math
import os
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# ci95 of an empty cell (a sweep not yet run) is NaN by design; the tables print "--"
warnings.filterwarnings("ignore", category=RuntimeWarning)

import analyze as A
import policies as P
from experiments import GRID_SEEDS, GRID_X, GRID_Y, LINK_MODES, N4_RATES, STATE_SEEDS, STATES
from simlib import CODE_VERSION, HERE

TAB = os.path.join(HERE, "tables")
FIG = os.path.join(HERE, "figures")
N_STA = 5  # stations in the single-arrival scenario (N1-N5)

MODE_NAME = {"slo": "SLO", "mlo": "MLO", "mloConfined": "MLO-conf."}
RATE_NAME = {r: "MCS " + r.replace("EhtMcs", "") for r in N4_RATES}
POL_NAME = {"RSSI": "RSSI", "LoadAware": "Load-Aware", "Airtime": "Airtime",
            "AirtimeThr": "AirtimeThr", "ucb1": "UCB1", "linucb": "LinUCB",
            "neural": "DAMA-MLO", "Oracle": "Oracle", "GreedyOracle": "Greedy oracle"}
BACKHAUL_W = (20, 80, 160)
SENS = [("base", {}), ("UDP", {"useTcp": "false"}), ("downlink", {"downlink": "true"}),
        ("near (10 m)", {"staDist": 10.0})]
SENS_MODES = ["mlo", "mloConfined"]

# Link configuration = identity, so it keeps one color, marker and hatch in every
# figure. Colors: first three slots of the validated categorical palette (all-pairs
# CVD safe); aqua is below 3:1 contrast, hence the marker/hatch secondary encoding.
MODE_STYLE = {
    "slo": dict(color="#2a78d6", marker="o", hatch=""),
    "mlo": dict(color="#eb6834", marker="s", hatch="//"),
    "mloConfined": dict(color="#1baf7a", marker="^", hatch=".."),
}
POL_STYLE = {  # arrivals figure: learners/heuristics, oracle in black
    "RSSI": dict(color="#52514e", marker="o", ls="-"),
    "Airtime": dict(color="#eda100", marker="s", ls="-"),
    "AirtimeThr": dict(color="#e87ba4", marker="D", ls="-"),
    "linucb": dict(color="#008300", marker="^", ls="-"),
    "neural": dict(color="#4a3aa7", marker="v", ls="-"),
    "ucb1": dict(color="#e34948", marker="P", ls="-"),
    "LoadAware": dict(color="#8a8984", marker="x", ls=":"),
    "GreedyOracle": dict(color="#0b0b0b", marker="*", ls="--"),
}
# diverging: orange pole (MAP 4 better) - neutral gray - blue pole (MAP 1 better)
DIVERGING = LinearSegmentedColormap.from_list("map4_map1", ["#d95926", "#f0efec", "#2a78d6"])

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.5, "axes.axisbelow": True,
    "lines.linewidth": 1.2, "lines.markersize": 4, "hatch.linewidth": 0.5,
    "pdf.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
COL1 = 3.5   # single-column width [in] (Elsevier CAS double-column)
COL2 = 7.16  # full text width

PARTIAL = False
STATUS = []
MADE = {"tables": [], "figures": []}


# ------------------------------------------------------------------ helpers
def pm(mc, d=2):
    """mean +- CI from a (mean, ci[, n]) tuple; '--' if absent."""
    if mc is None or (isinstance(mc, (list, tuple)) and (len(mc) < 2 or mc[0] is None)):
        return "--"
    m, c = mc[0], mc[1]
    if isinstance(m, float) and math.isnan(m):
        return "--"
    return f"${m:.{d}f} \\pm {c:.{d}f}$" if c else f"${m:.{d}f}$"


def boot(v, d=3):
    """mean [lo, hi] from a cluster-bootstrap triple; '--' if absent."""
    if not v:
        return "--"
    m, lo, hi = v
    return f"${m:.{d}f}$ {{\\scriptsize [${lo:.{d}f}$, ${hi:.{d}f}$]}}"


def num(x, d=2):
    return "--" if x is None or (isinstance(x, float) and math.isnan(x)) else f"${x:.{d}f}$"


def pval(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "--"
    return "$<10^{-3}$" if p < 1e-3 else f"${p:.3f}$"


def geo_pct(dlog):
    """sumLog difference -> geometric-mean per-station throughput change [%]."""
    return 100.0 * (math.exp(dlog / N_STA) - 1.0)


def write_table(name, body, caption, label, wide=False, note="", size="small", sep=3.5):
    env = "table*" if wide else "table"
    head = f"% generated by make_tables_figs.py -- do not edit by hand\n"
    if PARTIAL:
        head += "% PARTIAL DATA: see tables/STATUS.txt\n"
    cap = caption + (" \\textcolor{red}{[PARTIAL]}" if PARTIAL else "")
    tex = (f"{head}\\begin{{{env}}}[t]\n\\caption{{{cap}}}\n\\label{{{label}}}\n\\centering\n"
           f"\\{size}\n\\setlength{{\\tabcolsep}}{{{sep}pt}}\n{body}"
           + (f"\n\\par\\smallskip\\footnotesize {note}" if note else "")
           + f"\n\\end{{{env}}}\n")
    with open(os.path.join(TAB, name + ".tex"), "w") as f:
        f.write(tex)
    MADE["tables"].append(name)


def save_fig(fig, name):
    if PARTIAL:
        fig.text(0.995, 0.005, "PARTIAL DATA", ha="right", va="bottom", fontsize=6, color="#e34948")
    fig.savefig(os.path.join(FIG, name + ".pdf"))
    fig.savefig(os.path.join(FIG, name + ".png"), dpi=200)
    plt.close(fig)
    MADE["figures"].append(name)


def skip(what, why):
    STATUS.append(f"SKIPPED {what}: {why}")


# ------------------------------------------------------------------ coverage
def coverage():
    """Count cached runs for every sweep; sets the global PARTIAL flag."""
    global PARTIAL
    idx = A.index(A.load_runs())
    lines = []
    tot_have = tot_want = tot_excl = 0

    def add(label, have, want, excluded=0):
        # excluded: runs recorded in results/failed_runs.jsonl (ns-3 exited non-zero);
        # they are reported, never imputed, and do not make the outputs PARTIAL
        nonlocal tot_have, tot_want, tot_excl
        tot_have += have
        tot_want += want
        tot_excl += excluded
        lines.append(f"{label:<34s} {have:5d} / {want:5d}"
                     + (f"  EXCLUDED {excluded} (failed_runs.jsonl)" if excluded else "")
                     + ("" if have + excluded == want else "  INCOMPLETE"))

    for mode in LINK_MODES:
        for rate in N4_RATES:
            want = [(mode, rate, 0, None, None, s) for s in GRID_SEEDS]
            want += [(mode, rate, sc, x, y, s) for x in GRID_X for y in GRID_Y
                     for sc in (1, 2) for s in GRID_SEEDS]
            add(f"grid {mode} {rate}", sum(k in idx for k in want), len(want))
    def state_keys(modes):
        # states sharing N4's rate share their pre-association runs, hence a set
        want = set()
        for mode in modes:
            for st in STATES:
                want |= {(mode, st["n4Rate"], 0, None, None, s) for s in STATE_SEEDS}
                want |= {(mode, st["n4Rate"], sc, st["n5X"], st["n5Y"], s)
                         for sc in (1, 2) for s in STATE_SEEDS}
        return want

    for mode in LINK_MODES:
        want = state_keys([mode])
        add(f"states {mode}", len(want & idx.keys()), len(want))
    # code 2.1 (matched delay, per-destination downlink rate): its own 80 MHz baseline
    want = state_keys(SENS_MODES)
    for label, filt in [("baseline 80 MHz (code 2.1)", {})] + \
            [(f"backhaul {w} MHz", {"backhaulWidth": w}) for w in (20, 160)] + SENS[1:]:
        sidx = A.index(A.load_runs(filt, version=CODE_VERSION))
        fidx = A.index(A.load_runs(filt, version=CODE_VERSION, failed=True))
        add(f"sens {label}", len(want & sidx.keys()), len(want), len((want & fidx.keys()) - sidx.keys()))
    for mode in ("mlo", "mloConfined"):
        f = os.path.join(HERE, "results", f"arrivals_{mode}_EhtMcs0.json")
        lines.append(f"arrivals {mode:<25s} {'present' if os.path.exists(f) else 'MISSING'}")
        if not os.path.exists(f):
            PARTIAL = True
    PARTIAL = PARTIAL or tot_have + tot_excl < tot_want
    lines.append(f"{'TOTAL runs':<34s} {tot_have:5d} / {tot_want:5d}"
                 + (f"  EXCLUDED {tot_excl} (failed_runs.jsonl)" if tot_excl else ""))
    return idx, lines


# ------------------------------------------------------------------ per-position data
def position_table(idx, mode, rate):
    """[(x, y, dlog MAP1-MAP4, rssi choice, n seeds)] for the grid positions with both actions."""
    rows = []
    data = A.build_dataset(idx, mode)
    for x in GRID_X:
        for y in GRID_Y:
            d = data.get((rate, x, y))
            if d is None:
                continue
            c, rew, _ = d
            n = min(len(rew[0]), len(rew[1]))
            if n == 0:
                continue
            # RSSI choice and oracle both restricted to the candidate set (Sec. 4.1)
            rows.append((x, y, float(np.mean(rew[0]) - np.mean(rew[1])), A.HEURISTICS["RSSI"](c), n,
                         float(np.mean(rew[0])), float(np.mean(rew[1])), A.oracle_action(c, rew)))
    return rows


# ------------------------------------------------------------------ Table: state utilization
def tab_states_util(st_json):
    body = ["\\begin{tabular}{ccccccc}", "\\toprule",
            "& \\multicolumn{2}{c}{MAP 1} & \\multicolumn{2}{c}{MAP 4} & \\multicolumn{2}{c}{Rule choice} \\\\",
            "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}\\cmidrule(lr){6-7}",
            "State & $u_{1,0}$ & $u_{1,1}$ & $u_{4,0}$ & $u_{4,1}$ & Airtime & AirtimeThr \\\\", "\\midrule"]
    any_ = False
    for st in STATES:
        r = st_json.get(f"mlo|state{st['id']}", {})
        ctx = r.get("context")
        if ctx is None:
            body.append(f"{st['id']} & -- & -- & -- & -- & -- & -- \\\\")
            continue
        any_ = True
        u = ctx["util"]
        ch = r.get("choice", {})
        name = lambda a: "--" if a is None else ("MAP 1" if a == 0 else "MAP 4")
        body.append(f"{st['id']} & {num(u[0])} & {num(u[1])} & {num(u[2])} & {num(u[3])} & "
                    f"{name(ch.get('Airtime'))} & {name(ch.get('AirtimeThr'))} \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    if not any_:
        return skip("tab_states_util", "no MLO state runs")
    write_table("tab_states_util", "\n".join(body),
                "Measured channel utilization before $N_5$ arrives (MLO, 10 seeds).",
                "tab:states_util", sep=2.5,
                note="$u_{j,l}$: busy fraction of MAP $j$ on Link $l$ (0: 5~GHz, 1: 6~GHz), "
                     "as advertised in the BSS Load element.")


# ------------------------------------------------------------------ Table: state results
def tab_states_results(st_json):
    body = ["\\begin{tabular}{cl ccc cc cc cc}", "\\toprule",
            " & & \\multicolumn{3}{c}{Sum-log throughput} & \\multicolumn{2}{c}{Sum throughput [Mbit/s]}"
            " & \\multicolumn{2}{c}{Jain's index} & \\multicolumn{2}{c}{$N_5$ [Mbit/s]} \\\\",
            "\\cmidrule(lr){3-5}\\cmidrule(lr){6-7}\\cmidrule(lr){8-9}\\cmidrule(lr){10-11}",
            "State & Config. & MAP 1 & MAP 4 & $p$ & MAP 1 & MAP 4 & MAP 1 & MAP 4 & MAP 1 & MAP 4 \\\\",
            "\\midrule"]
    any_ = False
    for i, st in enumerate(STATES):
        if i:
            body.append("\\addlinespace")
        for mode in LINK_MODES:
            r = st_json.get(f"{mode}|state{st['id']}", {})
            a, b = r.get("MAP1", {}), r.get("MAP4", {})
            if not a.get("n") and not b.get("n"):
                cells = ["--"] * 9
            else:
                any_ = True
                cells = [pm(a.get("sumLog")), pm(b.get("sumLog")), pval(r.get("welch_p_sumLog_MAP1_vs_MAP4")),
                         pm(a.get("sumTput"), 1), pm(b.get("sumTput"), 1),
                         pm(a.get("jain"), 3), pm(b.get("jain"), 3),
                         pm(a.get("tput_N5"), 1), pm(b.get("tput_N5"), 1)]
            body.append(f"{st['id'] if mode == LINK_MODES[0] else ''} & {MODE_NAME[mode]} & "
                        + " & ".join(cells) + " \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    if not any_:
        return skip("tab_states_results", "no state runs")
    write_table("tab_states_results", "\n".join(body),
                "Named states: $N_5$ at MAP 1 or MAP 4 (mean $\\pm$ 95\\% CI, 10 seeds).",
                "tab:states_results", wide=True, size="footnotesize", sep=2.5,
                note="$p$: Welch's $t$-test on sum-log throughput, MAP 1 vs MAP 4.")


# ------------------------------------------------------------------ Table + Fig: ablation
def ablation_rows(idx, abl, min_positions):
    rows = []
    for mode in LINK_MODES:
        for rate in N4_RATES:
            pre = abl.get(f"{mode}|{rate}|pre", {})
            pos = position_table(idx, mode, rate)
            npos = len(pos)
            if len(pos) < min_positions:
                pos = []  # too few positions for a grid mean
            if pos:
                # oracle gain over RSSI at each position: better MAP minus the RSSI choice
                g = [(m1 if a_o == 0 else m4) - (m1 if a_r == 0 else m4) for (_, _, _, a_r, _, m1, m4, a_o) in pos]
                gmc = A.ci95(g)
                frac1 = float(np.mean([d > 0 for (_, _, d, *_) in pos]))
            else:
                gmc, frac1 = None, None
            rows.append(dict(mode=mode, rate=rate, pre=pre, npos=npos, used=bool(pos), gain=gmc, frac1=frac1,
                             dlog=A.ci95([d for (_, _, d, *_) in pos]) if pos else None))
    return rows


def tab_ablation(rows):
    body = ["\\begin{tabular}{ll ccc c cc c}", "\\toprule",
            "Config. & $R_{N_4}$ & $u_{4,0}$ & $u_{4,1}$ & $N_4$ [Mbit/s] & Pos. & MAP 1 best & "
            "Oracle $-$ RSSI & Per-sta. \\\\",
            " & & & & & & [\\%] & sum-log & [\\%] \\\\", "\\midrule"]
    any_ = False
    for i, r in enumerate(rows):
        if i and r["rate"] == N4_RATES[0]:
            body.append("\\addlinespace")
        pre = r["pre"]
        has_pre = pre.get("util_MAP4_L0", (0, 0, 0))[2] > 0
        u1 = "--" if r["mode"] == "slo" else pm(pre.get("util_MAP4_L1"))
        cells = [pm(pre.get("util_MAP4_L0")) if has_pre else "--", u1 if has_pre else "--",
                 pm(pre.get("tput_N4"), 1) if has_pre else "--"]
        if r["used"]:
            any_ = True
            cells += [f"{r['npos']}", num(100 * r["frac1"], 0), pm(r["gain"], 3), num(geo_pct(r["gain"][0]), 1)]
        else:
            cells += [f"{r['npos']}", "--", "--", "--"]
        body.append(f"{MODE_NAME[r['mode']] if r['rate'] == N4_RATES[0] else ''} & {RATE_NAME[r['rate']]} & "
                    + " & ".join(cells) + " \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    if not any_:
        return skip("tab_ablation", "no grid runs")
    write_table("tab_ablation", "\n".join(body),
                "Ablation of the link configuration under fixed association (grid of $N_5$ positions).",
                "tab:ablation", wide=True,
                note="$u_{4,l}$, $N_4$: before $N_5$ arrives. Pos.: grid positions with both associations "
                     "simulated. MAP 1 best: share of positions where MAP 1 gives the higher sum-log throughput. "
                     "Oracle $-$ RSSI: mean sum-log gain of the better MAP over the RSSI choice; per-sta.: the "
                     "same as a geometric-mean per-station throughput change, $100(e^{\\Delta/5}-1)$.")


def fig_ablation(rows):
    have = [r for r in rows if r["pre"].get("util_MAP4_L0", (0, 0, 0))[2] > 0]
    if not have:
        return skip("fig_ablation", "no pre-association runs")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(COL1, 3.6), sharex=True)
    w = 0.26
    xs = np.arange(len(N4_RATES))
    for j, mode in enumerate(LINK_MODES):
        st = MODE_STYLE[mode]
        rr = {r["rate"]: r for r in rows if r["mode"] == mode}
        u = [rr[k]["pre"].get("util_MAP4_L0", (np.nan, 0))[0] if rr[k]["pre"].get("util_MAP4_L0", (0, 0, 0))[2]
             else np.nan for k in N4_RATES]
        uc = [rr[k]["pre"].get("util_MAP4_L0", (0, 0))[1] for k in N4_RATES]
        ax1.bar(xs + (j - 1) * w, u, w * 0.9, yerr=uc, color=st["color"], hatch=st["hatch"],
                edgecolor="white", linewidth=0.4, error_kw=dict(lw=0.6, capsize=1.5), label=MODE_NAME[mode])
        g = [rr[k]["gain"][0] if rr[k]["gain"] else np.nan for k in N4_RATES]
        gc = [rr[k]["gain"][1] if rr[k]["gain"] else 0 for k in N4_RATES]
        ax2.bar(xs + (j - 1) * w, g, w * 0.9, yerr=gc, color=st["color"], hatch=st["hatch"],
                edgecolor="white", linewidth=0.4, error_kw=dict(lw=0.6, capsize=1.5))
        for x0, v in zip(xs + (j - 1) * w, g):
            if np.isnan(v):
                ax2.text(x0, 0.002, "n/a", ha="center", va="bottom", fontsize=5.5, color="#8a8984", rotation=90)
    ax1.set_ylabel("MAP 4 utilization, 5 GHz")
    ax1.set_ylim(0, 1)
    ax1.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.22), frameon=False)
    ax2.set_ylabel("Oracle $-$ RSSI, sum-log")
    ax2.set_xticks(xs, [RATE_NAME[r] for r in N4_RATES])
    ax2.set_xlabel("Rate of the slow station $N_4$")
    ax2.set_ylim(bottom=0)
    for ax, t in ((ax1, "(a)"), (ax2, "(b)")):
        ax.set_title(t, loc="left", fontsize=8)
    save_fig(fig, "fig_ablation")


def fig_grid(idx, rate="EhtMcs0"):
    per = {m: position_table(idx, m, rate) for m in LINK_MODES}
    if not any(per.values()):
        return skip("fig_grid", "no grid runs")
    # the scale covers the bulk of the cells; a cell beyond it (an N5 that starves at
    # one MAP) saturates, and its printed value still gives the magnitude
    vmax = float(np.percentile([abs(d) for rows in per.values() for (_, _, d, *_) in rows], 85)) or 1e-3
    fig, axes = plt.subplots(1, 3, figsize=(COL2, 2.35), sharey=True, constrained_layout=True)
    for ax, mode in zip(axes, LINK_MODES):
        grid = np.full((len(GRID_Y), len(GRID_X)), np.nan)
        rssi = {}
        for (x, y, d, a_r, n, *_) in per[mode]:
            grid[GRID_Y.index(y), GRID_X.index(x)] = d
            rssi[(x, y)] = a_r
        ax.set_facecolor("#f0efec")
        im = ax.imshow(grid, cmap=DIVERGING, vmin=-vmax, vmax=vmax, origin="lower", aspect="auto",
                       extent=(-0.5, len(GRID_X) - 0.5, -0.5, len(GRID_Y) - 0.5))
        for i, y in enumerate(GRID_Y):
            for j, x in enumerate(GRID_X):
                v = grid[i, j]
                if np.isnan(v):
                    ax.text(j, i, "--", ha="center", va="center", fontsize=6, color="#8a8984")
                else:
                    ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=6,
                            color="white" if abs(v) > 0.6 * vmax else "#0b0b0b")
                    if rssi.get((x, y)) == 1:  # RSSI picks MAP 4: outline the cell
                        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, lw=0.8,
                                                   ec="#0b0b0b"))
        ax.grid(False)
        ax.set_xticks(range(len(GRID_X)), [f"{x:.0f}" for x in GRID_X])
        ax.set_yticks(range(len(GRID_Y)), [f"{y:.0f}" for y in GRID_Y])
        ax.set_title(MODE_NAME[mode] if mode != "mloConfined" else "MLO-confined")
        ax.set_xlabel("$x_{N_5}$ [m]")
    axes[0].set_ylabel("$y_{N_5}$ [m]")
    cb = fig.colorbar(im, ax=axes, shrink=0.9, pad=0.01, extend="both")
    cb.set_label("sum-log, MAP 1 $-$ MAP 4")
    cb.outline.set_linewidth(0.4)
    save_fig(fig, "fig_grid")


# ------------------------------------------------------------------ Table + Fig: policies
def tab_policies(pol):
    if not pol:
        return skip("tab_policies", "no link mode has enough grid positions")
    order = [n for n in ("RSSI", "LoadAware", "Airtime", "AirtimeThr", "ucb1", "linucb", "neural", "Oracle")]
    body = ["\\begin{tabular}{ll ccc cc cc}", "\\toprule",
            "Config. & Policy & $\\Delta$ sum-log vs RSSI & $\\Delta$ vs AirtimeThr & Regret & Agree & Train. & $\\Delta$ tput & Jain \\\\",
            " & & [95\\% CI] & [95\\% CI] & [95\\% CI] & [\\%] & SD & [\\%] & \\\\", "\\midrule"]
    for i, mode in enumerate(LINK_MODES):
        res = pol.get(mode)
        if res is None:
            continue
        if i:
            body.append("\\addlinespace")
        first = True
        for n in order:
            if n not in res:
                continue
            r = res[n]
            body.append(f"{MODE_NAME[mode] if first else ''} & {POL_NAME[n]} & "
                        f"{boot(r.get('gain_boot'))} & {boot(r.get('vs_AirtimeThr_boot'))} & {boot(r.get('regret_boot'))} & "
                        f"{num(100 * r['oracle_agree'], 0)} & {num(r.get('train_sd'), 3) if r.get('train_sd') is not None else '--'} & "
                        f"{num(r['sumTput_gain_pct_vs_rssi'], 2)} & {num(r['jain'][0], 3)} \\\\")
            first = False
    body += ["\\bottomrule", "\\end{tabular}"]
    n_ctx = {m: pol[m]["RSSI"]["n_contexts"] for m in pol}
    write_table("tab_policies", "\n".join(body),
                "Policy comparison, leave-one-position-out (mean $\\pm$ 95\\% CI).",
                "tab:policies", wide=True, sep=2.5,
                note="Contexts per configuration: " + ", ".join(f"{MODE_NAME[m]} {n}" for m, n in n_ctx.items())
                     + ". Means over contexts (grid positions x rates of $N_4$). Intervals: paired two-stage "
                       "bootstrap over grid positions and, within each context, seeds (4000 resamples), the same "
                       "for every row; learner rows use the replicate-averaged choices; $\\Delta$ vs AirtimeThr is paired on the same contexts and seeds. Train. SD: standard "
                       "deviation of a learner's mean gain over its training replicates. Agree: share of contexts in "
                       "which the policy picks the same MAP as the oracle. $\\Delta$ tput: change of the sum "
                       "throughput against RSSI. The oracle is an empirical hindsight bound on the same seeds.")


def tab_training(pol_c, pol_u):
    """Learner training-variant sensitivity: constrained (main) vs unconstrained training."""
    learners = [n for n in ("ucb1", "linucb", "neural") if any(n in pol_c.get(m, {}) for m in LINK_MODES)]
    if not learners or not pol_u:
        return skip("tab_training", "learners not run")
    body = ["\\begin{tabular}{ll cc cc}", "\\toprule",
            " & & \\multicolumn{2}{c}{Constrained (main)} & \\multicolumn{2}{c}{Unconstrained} \\\\",
            "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}",
            "Config. & Learner & $\\Delta$ vs RSSI & Regret & $\\Delta$ vs RSSI & Regret \\\\", "\\midrule"]
    first_mode = True
    for mode in LINK_MODES:
        if mode not in pol_c or mode not in pol_u:
            continue
        if not first_mode:
            body.append("\\addlinespace")
        first_mode = False
        for i, n in enumerate(learners):
            c, u = pol_c[mode][n], pol_u[mode][n]
            body.append(f"{MODE_NAME[mode] if i == 0 else ''} & {POL_NAME[n]} & "
                        f"{boot(c.get('gain_boot'))} & {boot(c.get('regret_boot'))} & "
                        f"{boot(u.get('gain_boot'))} & {boot(u.get('regret_boot'))} \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    write_table("tab_training", "\n".join(body),
                "Learners trained with and without the candidate restriction.", "tab:training", wide=True,
                note="Same training budget, folds, seeds and test-time candidate restriction in both columns. "
                     "Unconstrained training lets a learner try the MAP that fails the per-link floor and "
                     "observe its offline outcome.")


def fig_policies(pol):
    if not pol:
        return skip("fig_policies", "no link mode has enough grid positions")
    order = ["RSSI", "LoadAware", "Airtime", "AirtimeThr", "ucb1", "linucb", "neural", "Oracle"]
    names = [n for n in order if any(n in pol[m] for m in pol)]
    fig, ax = plt.subplots(figsize=(COL1, 0.28 * len(names) + 0.7))
    ys = np.arange(len(names))[::-1]
    off = {"slo": 0.22, "mlo": 0.0, "mloConfined": -0.22}
    for mode in LINK_MODES:
        if mode not in pol:
            continue
        st = MODE_STYLE[mode]
        for y, n in zip(ys, names):
            r = pol[mode].get(n)
            if r is None:
                continue
            m, lo, hi = r["gain_boot"]
            ax.errorbar(m, y + off[mode], xerr=[[m - lo], [hi - m]], fmt=st["marker"], color=st["color"], ms=4,
                        mec="white", mew=0.4, elinewidth=0.8, capsize=1.5,
                        label=MODE_NAME[mode] if n == names[0] else None)
    ax.axvline(0, color="#52514e", lw=0.6)
    ax.set_yticks(ys, [POL_NAME[n] for n in names])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Sum-log throughput gain over RSSI")
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    save_fig(fig, "fig_policies")


# ------------------------------------------------------------------ Table + Fig: backhaul / sensitivity
def state_delta(st_json, mode, sid, with_n=False):
    """MAP 1 - MAP 4 sum-log difference on the seeds both options have, and its p-value
    (with_n: also the number of shared seeds)."""
    r = st_json.get(f"{mode}|state{sid}", {})
    if not r.get("n_common"):
        return (None, None, 0) if with_n else (None, None)
    d, p = r["delta_sumLog_MAP1_minus_MAP4"], r.get("welch_p_sumLog_MAP1_vs_MAP4")
    return (d, p, r["n_common"]) if with_n else (d, p)


def sens_tables():
    """Backhaul width and transport/direction/distance sensitivity; one delta table each.

    All columns, including the 80 MHz / TCP-uplink baseline, are code-2.1 runs, so
    the delay split and the downlink rate control are the same in every column.
    """
    part = "_partial" if PARTIAL else ""
    base = A.states(tag="_v21" + part, modes=SENS_MODES, version=CODE_VERSION)
    bh = {80: base}
    for w in (20, 160):
        bh[w] = A.states({"backhaulWidth": w}, tag=f"_bh{w}" + part, modes=SENS_MODES,
                         version=CODE_VERSION)
    sens = {"base": base}
    for label, f in SENS[1:]:
        tag = "_" + label.split()[0] + part
        sens[label] = A.states(f, tag=tag, modes=SENS_MODES, version=CODE_VERSION)
    tab_delay(bh)

    def table(name, cols, data, caption, label, extra_note=""):
        head = " & ".join(cols)
        body = ["\\begin{tabular}{cl " + "c" * len(cols) + "}", "\\toprule",
                f"State & Config. & {head} \\\\", "\\midrule"]
        n_have = 0
        short = set()  # shared-seed counts below len(STATE_SEEDS)
        for i, st in enumerate(STATES):
            if i:
                body.append("\\addlinespace")
            for mode in SENS_MODES:
                cells = []
                for c in data:
                    d, p, nc = state_delta(data[c], mode, st["id"], with_n=True)
                    if d is None:
                        cells.append("--")
                    else:
                        n_have += c != 80 and c != "base"
                        star = "$^{*}$" if p is not None and p < 0.05 else ""
                        dag = ""
                        if nc < len(STATE_SEEDS):
                            short.add(nc)
                            dag = "$^{\\dagger}$"
                        cells.append(f"${d:+.3f}${star}{dag}")
                body.append(f"{st['id'] if mode == SENS_MODES[0] else ''} & {MODE_NAME[mode]} & "
                            + " & ".join(cells) + " \\\\")
        body += ["\\bottomrule", "\\end{tabular}"]
        if n_have == 0:
            return skip(name, "sweep not run yet")
        note = (f"Entries: sum-log throughput with $N_5$ at MAP 1 minus at MAP 4 ({len(STATE_SEEDS)} seeds). "
                "$^{*}$: $p < 0.05$, Welch's $t$-test.")
        if short:
            note += (" $^{\\dagger}$: " + "/".join(str(n) for n in sorted(short))
                     + " shared seeds; a run that aborted in ns-3 is excluded from both options"
                     " (Section~\\ref{sec:disc-limits}).")
        write_table(name, "\n".join(body), caption, label, note=note + extra_note, sep=3.5)

    table("tab_backhaul", [f"{w} MHz" for w in BACKHAUL_W], {w: bh[w] for w in BACKHAUL_W},
          "Effect of backhaul width on the MAP 1 $-$ MAP 4 difference.", "tab:backhaul")
    table("tab_sens", [lab.split()[0] for lab, _ in SENS], sens,
          "Sensitivity to transport, direction and station distance.", "tab:sens",
          extra_note=" near: fast stations 10~m from their AP.")

    # figure: state 3 and state 1 vs backhaul width
    pts = {(m, sid): [state_delta(bh[w], m, sid)[0] for w in BACKHAUL_W] for m in SENS_MODES for sid in (1, 3)}
    if sum(v is not None for vals in pts.values() for v in vals) <= len(pts):
        return skip("fig_backhaul", "backhaul sweep not run yet")
    fig, axes = plt.subplots(1, 2, figsize=(COL1, 1.7), sharey=True)
    for ax, sid in zip(axes, (3, 1)):
        for m in SENS_MODES:
            st = MODE_STYLE[m]
            v = [np.nan if d is None else d for d in pts[(m, sid)]]
            ax.plot(BACKHAUL_W, v, marker=st["marker"], color=st["color"], label=MODE_NAME[m])
        ax.axhline(0, color="#52514e", lw=0.6)
        ax.set_xscale("log", base=2)
        ax.set_xticks(BACKHAUL_W, [str(w) for w in BACKHAUL_W])
        ax.minorticks_off()
        ax.set_title(f"State {sid}")
        ax.set_xlabel("Backhaul width [MHz]")
    axes[0].set_ylabel("sum-log, MAP 1 $-$ MAP 4")
    axes[0].legend(frameon=False, loc="best")
    save_fig(fig, "fig_backhaul")


# ------------------------------------------------------------------ Table: delay split
def tab_delay(bh):
    """Matched per-packet delay split (code 2.1) for States 1 and 3 vs backhaul width."""
    comps = ("dAccMs", "dWbhMs", "dWiredMs", "dE2eMs")
    body = ["\\begin{tabular}{cll c cccc}", "\\toprule",
            "State & Config. & Assoc. & Backhaul & Access & Wireless bh & Wired & End-to-end \\\\",
            " & & & [MHz] & [ms] & [ms] & [ms] & [ms] \\\\", "\\midrule"]
    n_have = 0
    for i, sid in enumerate((1, 3)):
        if i:
            body.append("\\addlinespace")
        for mode in SENS_MODES:
            for mp in ("MAP1", "MAP4"):
                for w in BACKHAUL_W:
                    r = bh[w].get(f"{mode}|state{sid}", {}).get(mp, {})
                    if not all(k in r for k in comps):
                        cells = ["--"] * 4
                    else:
                        n_have += 1
                        cells = [f"${r[k][0]:.1f}$" for k in comps]
                    body.append(f"{sid} & {MODE_NAME[mode]} & {mp.replace('MAP', 'MAP~')} & {w} & "
                                + " & ".join(cells) + " \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    if n_have == 0:
        return skip("tab_delay", "code-2.1 sweeps not run yet")
    write_table("tab_delay", "\n".join(body),
                "Mean delay of the same delivered packets, split by path segment.", "tab:delay", wide=True,
                note="Uplink TCP, 10 seeds. Each packet is time-stamped at its source, the serving "
                     "MAP, the gateway MAP and the server; the components add up to the end-to-end delay.")


# ------------------------------------------------------------------ Table + Fig: arrivals
def arrivals():
    files = sorted(glob.glob(os.path.join(HERE, "results", "arrivals_*_EhtMcs0.json")))
    data = {}
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        data[d["mode"]] = d
    if not data:
        skip("tab_arrivals", "arrivals.py not run yet")
        return skip("fig_arrivals", "arrivals.py not run yet")
    order = ["RSSI", "LoadAware", "Airtime", "AirtimeThr", "ucb1", "linucb", "neural", "GreedyOracle"]
    body = ["\\begin{tabular}{ll ccc c}", "\\toprule",
            "Config. & Policy & $\\Delta$ sum-log vs RSSI & Sum tput [Mbit/s] & Jain & MAP 1 [\\%] \\\\",
            "\\midrule"]
    for i, mode in enumerate(m for m in LINK_MODES if m in data):
        if i:
            body.append("\\addlinespace")
        pols = data[mode]["policies"]
        first = True
        for n in order:
            if n not in pols:
                continue
            last = pols[n]["per_step"][-1]
            body.append(f"{MODE_NAME[mode] if first else ''} & {POL_NAME[n]} & "
                        f"{pm(last['sumLog_gain_vs_rssi'], 3)} & {pm(last['sumTput'], 1)} & "
                        f"{pm(last['jain'], 3)} & {num(100 * pols[n]['frac_map1'], 0)} \\\\")
            first = False
    body += ["\\bottomrule", "\\end{tabular}"]
    k = next(iter(data.values()))["k"]
    tr = next(iter(data.values()))["trials"]
    write_table("tab_arrivals", "\n".join(body),
                f"Sequential arrivals: network after all {k} new stations ({tr} trials).",
                "tab:arrivals", wide=True,
                note="Mean $\\pm$ 95\\% CI over the trials. MAP 1: share of the new stations placed at MAP 1.")

    modes = [m for m in ("mlo", "mloConfined") if m in data]
    fig, axes = plt.subplots(1, len(modes), figsize=(COL1 if len(modes) == 1 else COL2 * 0.62, 2.0),
                             sharey=True, squeeze=False)
    for ax, mode in zip(axes[0], modes):
        pols = data[mode]["policies"]
        steps = np.arange(1, data[mode]["k"] + 1)
        for n in order:
            if n not in pols or n == "RSSI":
                continue
            st = POL_STYLE[n]
            m = [s["sumLog_gain_vs_rssi"][0] for s in pols[n]["per_step"]]
            c = [s["sumLog_gain_vs_rssi"][1] for s in pols[n]["per_step"]]
            ax.errorbar(steps, m, yerr=c, color=st["color"], marker=st["marker"], ls=st["ls"], ms=3.5,
                        elinewidth=0.6, capsize=1.2, label=POL_NAME[n])
        ax.axhline(0, color="#52514e", lw=0.6)
        ax.set_xticks(steps)
        ax.set_xlabel("New stations placed")
        ax.set_title("MLO" if mode == "mlo" else "MLO-confined")
    axes[0][0].set_ylabel("Sum-log gain over RSSI")
    axes[0][-1].legend(frameon=False, fontsize=6, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    save_fig(fig, "fig_arrivals")
    arrival_seeds()


def arrival_seeds():
    """Training-seed table: summarize_arrival_seeds.py + stall_arrivals.py outputs."""
    res = os.path.join(HERE, "results")
    seeds = {m: os.path.join(res, f"arrival_seeds_{m}_EhtMcs0.json") for m in ("mlo", "mloConfined")}
    stall_f = os.path.join(res, "arrival_stall_trace", "stalls.json")
    if not all(os.path.exists(f) for f in seeds.values()) or not os.path.exists(stall_f):
        return skip("tab_arrival_seeds", "summarize_arrival_seeds.py / stall_arrivals.py not run")
    with open(stall_f) as f:
        stalls = json.load(f)

    def ci(lo_hi):
        return f"$[{lo_hi[0]:.3f}, {lo_hi[1]:.3f}]$"

    body = ["\\begin{tabular}{ll ccccc cc c}", "\\toprule",
            "Config. & Learner & \\multicolumn{5}{c}{Training seed} & Pooled & 95\\% CI & "
            "Excl.\\ stalled [95\\% CI] \\\\",
            "\\cmidrule(lr){3-7}",
            " & & 0 & 1 & 2 & 3 & 4 & & & \\\\", "\\midrule"]
    for i, mode in enumerate(("mlo", "mloConfined")):
        if i:
            body.append("\\addlinespace")
        with open(seeds[mode]) as f:
            rep = json.load(f)
        for j, n in enumerate(("ucb1", "linucb", "neural")):
            r = rep["learners"][n]
            s = stalls[mode]["sensitivity_excl_stalled"][n]
            removed = sum(s["trials_removed_per_seed"].values())
            ex = s["excl_stalled"]
            per = " & ".join(num(r["per_seed_mean"][str(k)], 3) for k in rep["seeds"])
            body.append(f"{MODE_NAME[mode] if j == 0 else ''} & {POL_NAME[n]} & {per} & "
                        f"{num(r['pooled_mean'], 3)} & {ci(r['crossed_boot_95'])} & "
                        f"{num(ex['pooled_mean'], 3)} {ci(ex['crossed_boot_95'])}"
                        + (f" ({removed})" if removed else "") + " \\\\")
    body += ["\\bottomrule", "\\end{tabular}"]
    write_table("tab_arrival_seeds", "\n".join(body),
                "Sequential arrivals: sum-log gain over RSSI after 5 new stations, by learner training seed.",
                "tab:arrival_seeds", wide=True,
                note="Each seed: mean over the same 15 placement trials. Pooled: mean of the five seeds; "
                     "crossed bootstrap over seeds and trials. Excl.\\ stalled: sensitivity check without "
                     "trials whose final run (learner or RSSI) had a station below 0.05~Mbit/s or without "
                     "data frames; number of removed trial-seed pairs in parentheses.")


# ------------------------------------------------------------------ preview document
def preview():
    tex = ["\\documentclass[10pt]{article}",
           "\\usepackage[margin=1.8cm]{geometry}\\usepackage{booktabs,graphicx,xcolor,amsmath}",
           "\\begin{document}", "\\section*{DAMA-MLO revision: generated tables and figures}",
           "{\\footnotesize\\begin{verbatim}"] + STATUS + ["\\end{verbatim}}"]
    tex += [f"\\input{{{t}.tex}}" for t in MADE["tables"]]
    tex += ["\\clearpage"]
    for fname in MADE["figures"]:
        wide = fname in ("fig_grid", "fig_arrivals")
        tex += [f"\\begin{{figure{'*' if wide else ''}}}[h]\\centering",
                f"\\includegraphics[width={'\\textwidth' if wide else '0.55\\textwidth'}]{{../figures/{fname}.pdf}}\\caption{{\\texttt{{{fname.replace('_', chr(92) + '_')}}}}}",
                f"\\end{{figure{'*' if wide else ''}}}"]
    tex += ["\\end{document}"]
    with open(os.path.join(TAB, "preview.tex"), "w") as f:
        f.write("\n".join(tex))
    p = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "preview.tex"],
                       cwd=TAB, capture_output=True, text=True)
    return p.returncode == 0, p.stdout[-1500:]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5, help="learner training replicates")
    ap.add_argument("--no-learners", action="store_true")
    ap.add_argument("--from-json", action="store_true",
                    help="read the policy comparison from results/policies*.json instead of retraining "
                         "the learners (layout changes only; the files must come from a full run)")
    ap.add_argument("--min-positions", type=int, default=10,
                    help="grid positions a link mode needs before the policy comparison runs")
    opt = ap.parse_args()
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)

    idx, cov = coverage()
    tag = "_partial" if PARTIAL else ""
    STATUS.extend(["Coverage (cached runs / runs in the sweep):"] + cov + [""])

    st = A.states(tag=tag)
    tab_states_util(st)
    tab_states_results(st)

    abl = A.ablation(tag=tag)
    rows = ablation_rows(idx, abl, opt.min_positions)
    tab_ablation(rows)
    fig_ablation(rows)
    fig_grid(idx)

    learners = [] if opt.no_learners else A.LEARNERS
    if opt.from_json:
        with open(os.path.join(HERE, "results", f"policies{tag}.json")) as f:
            pol = {m: v for m, v in json.load(f).items() if m != "_meta"}
    else:
        pol = A.policies(tag=tag, reps=opt.reps, learners=learners, min_positions=opt.min_positions)
    for m in LINK_MODES:
        if m not in pol:
            skip(f"policies/{m}", f"fewer than {opt.min_positions} grid positions")
    tab_policies(pol)
    fig_policies(pol)
    if opt.from_json:
        with open(os.path.join(HERE, "results", f"policies{tag}_unconstrained.json")) as f:
            pol_u = {m: v for m, v in json.load(f).items() if m != "_meta"}
    else:
        pol_u = (A.policies(tag=tag + "_unconstrained", reps=opt.reps, learners=learners,
                            min_positions=opt.min_positions, training="unconstrained")
                 if learners else {})
    tab_training(pol, pol_u)

    sens_tables()
    arrivals()

    STATUS.append("")
    STATUS.append(f"learners: {learners or 'none'}, replicates: {opt.reps}"
                  + (" (policy results read from results/policies*.json)" if opt.from_json else ""))
    STATUS.append("tables:  " + ", ".join(MADE["tables"]))
    STATUS.append("figures: " + ", ".join(MADE["figures"]))
    ok, log = preview()
    STATUS.append("preview.pdf: " + ("built" if ok else "FAILED (see tables/preview.log)"))
    with open(os.path.join(TAB, "STATUS.txt"), "w") as f:
        f.write(("PARTIAL DATA\n\n" if PARTIAL else "COMPLETE\n\n") + "\n".join(STATUS) + "\n")
    print("\n".join(STATUS))


if __name__ == "__main__":
    main()
