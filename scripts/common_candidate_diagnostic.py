"""Compare SLO and MLO on grid positions where both MAPs pass the candidate check in both.

The check is the receiver-calibrated per-link floor of policies.py (in-band offset
CAND_RX_OFFSET_DB). DAMA_CAND_RX_OFFSET_DB=0 gives the nominal check, which also admits
(100, 195) m under MLO (sensitivity case).
Run from this directory with: python3 common_candidate_diagnostic.py
"""

import json

import numpy as np

import analyze
import policies as P
from experiments import GRID_SEEDS, GRID_X, GRID_Y


def main():
    idx = analyze.index(analyze.load_runs())
    rate = "EhtMcs0"
    modes = ("slo", "mlo")
    common = []
    contexts = {}

    for x in GRID_X:
        for y in GRID_Y:
            admitted_in_both = True
            for mode in modes:
                for seed in GRID_SEEDS:
                    try:
                        ctx = analyze.context(idx, mode, rate, x, y, seed)
                    except KeyError:
                        admitted_in_both = False
                        break
                    if P.forced_action(ctx) is not None:
                        admitted_in_both = False
                        break
                if not admitted_in_both:
                    break
            if admitted_in_both:
                common.append((x, y))

    output = {"rate": rate, "candidate_rule": f"per-link {P.CAND_FLOOR_DBM} dBm floor, rx offset {P.CAND_RX_OFFSET_DB} dB",
              "common_positions": common, "n_positions": len(common), "modes": {}}
    for mode_i, mode in enumerate(modes):
        differences = []
        for x, y in common:
            ctx = analyze.context(idx, mode, rate, x, y, GRID_SEEDS[0])
            rewards = np.array([
                [idx[(mode, rate, action + 1, x, y, seed)]["sumLog"] for seed in GRID_SEEDS]
                for action in (0, 1)
            ])
            rssi_action = 0 if ctx["rssi"][0] >= ctx["rssi"][1] else 1
            oracle_action = int(rewards[1].mean() > rewards[0].mean())
            differences.append(rewards[oracle_action] - rewards[rssi_action])

        paired = np.asarray(differences, dtype=float)
        rng = np.random.default_rng(20261005 + mode_i)
        n_boot = 10000
        pos_draw = rng.integers(paired.shape[0], size=(n_boot, paired.shape[0]))
        seed_draw = rng.integers(
            paired.shape[1], size=(n_boot, paired.shape[0], paired.shape[1])
        )
        boot = paired[pos_draw[:, :, None], seed_draw].mean(axis=(1, 2))
        output["modes"][mode] = {
            "mean_gain": float(paired.mean()),
            "bootstrap_95": np.percentile(boot, [2.5, 97.5]).tolist(),
        }

    # Paired resampling keeps each sampled position and seed aligned across modes.
    gain_matrices = {}
    for mode in modes:
        rows = []
        for x, y in common:
            ctx = analyze.context(idx, mode, rate, x, y, GRID_SEEDS[0])
            rewards = np.array([
                [idx[(mode, rate, action + 1, x, y, seed)]["sumLog"] for seed in GRID_SEEDS]
                for action in (0, 1)
            ])
            rssi_action = 0 if ctx["rssi"][0] >= ctx["rssi"][1] else 1
            oracle_action = int(rewards[1].mean() > rewards[0].mean())
            rows.append(rewards[oracle_action] - rewards[rssi_action])
        gain_matrices[mode] = np.asarray(rows)

    rng = np.random.default_rng(20261007)
    n_boot = 20000
    pos_draw = rng.integers(len(common), size=(n_boot, len(common)))
    seed_draw = rng.integers(
        len(GRID_SEEDS), size=(n_boot, len(common), len(GRID_SEEDS))
    )
    slo_boot = gain_matrices["slo"][pos_draw[:, :, None], seed_draw].mean(axis=(1, 2))
    mlo_boot = gain_matrices["mlo"][pos_draw[:, :, None], seed_draw].mean(axis=(1, 2))
    diff_boot = slo_boot - mlo_boot
    ratio_boot = slo_boot / np.maximum(mlo_boot, np.finfo(float).tiny)
    diff_point = float(gain_matrices["slo"].mean() - gain_matrices["mlo"].mean())
    output["paired_slo_minus_mlo"] = {
        "mean_difference": diff_point,
        "bootstrap_95": np.percentile(diff_boot, [2.5, 97.5]).tolist(),
        "p_bootstrap_difference_le_zero": float(np.mean(diff_boot <= 0)),
    }
    output["paired_ratio_slo_over_mlo"] = {
        "point_ratio": float(gain_matrices["slo"].mean() / gain_matrices["mlo"].mean()),
        "bootstrap_95": np.percentile(ratio_boot, [2.5, 97.5]).tolist(),
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
