"""Simulation sweeps for the DAMA-MLO major revision.

Usage: python3 experiments.py <name> [<name> ...]
  states21  named states under MLO and MLO-confined with code 2.1 (80 MHz delay baseline)
  pilot     steady-state check: 30 s window with per-second throughput traces (code 2.1)
  grid      main grid: N5 positions x N4 rate x link mode x action x seeds,
            plus pre-association (scenario 0) runs; feeds Tables/Figs for the
            ablation (R1.3) and the policy comparison (R1.2, R1.5)
  states    the five named states of the original Table III, 10 seeds
  backhaul  backhaul-capacity sensitivity (R1.6, R3.4)
  sens      transport/direction/fast-MCS sensitivity (R1.4a, R3.5, R3.6)
All results go to results/runs.jsonl via simlib.
"""

import sys

from simlib import CODE_VERSION, LEGACY_VERSION, run_many

GRID_X = [10.0, 40.0, 70.0, 100.0]
GRID_Y = [165.0, 195.0, 225.0, 255.0, 285.0]
# EhtMcs7 replaced by EhtMcs4 on 2026-09-29: at n4X = 120 m N4's SNR is ~15 dB under
# log-distance propagation, so no MCS 7 (or MCS 5) frame is decoded. EhtMcs4 is the
# fastest mode N4 decodes there (decode check: 13.0 Mbps, MAP 4 utilization 0.25).
N4_RATES = ["EhtMcs0", "EhtMcs2", "EhtMcs4"]
LINK_MODES = ["slo", "mlo", "mloConfined"]
GRID_SEEDS = list(range(1, 6))

STATES = [
    {"id": 0, "n5X": 30.0, "n5Y": 300.0, "n4Rate": "EhtMcs0"},
    {"id": 1, "n5X": 70.0, "n5Y": 225.0, "n4Rate": "EhtMcs0"},
    {"id": 2, "n5X": 70.0, "n5Y": 225.0, "n4Rate": "EhtMcs4"},  # was EhtMcs7, see N4_RATES
    {"id": 3, "n5X": 10.0, "n5Y": 180.0, "n4Rate": "EhtMcs0"},
    {"id": 4, "n5X": 70.0, "n5Y": 225.0, "n4Rate": "EhtMcs2"},
]
STATE_SEEDS = list(range(1, 11))
SENS_MODES = ["mlo", "mloConfined"]


def grid_args(extra=None, seeds=GRID_SEEDS, modes=LINK_MODES):
    extra = extra or {}
    out = []
    for mode in modes:
        for rate in N4_RATES:
            for s in seeds:
                a = {"scenario": 0, "linkMode": mode, "n4Rate": rate, "rngRun": s}
                a.update(extra)
                out.append(a)
                for x in GRID_X:
                    for y in GRID_Y:
                        for sc in (1, 2):
                            a = {"scenario": sc, "linkMode": mode, "n4Rate": rate,
                                 "n5X": x, "n5Y": y, "rngRun": s}
                            a.update(extra)
                            out.append(a)
    return out


def state_args(extra=None, modes=LINK_MODES, seeds=STATE_SEEDS):
    extra = extra or {}
    out = []
    for mode in modes:
        for st in STATES:
            for s in seeds:
                a0 = {"scenario": 0, "linkMode": mode, "n4Rate": st["n4Rate"], "rngRun": s}
                a0.update(extra)
                out.append(a0)
                for sc in (1, 2):
                    a = {"scenario": sc, "linkMode": mode, "n4Rate": st["n4Rate"],
                         "n5X": st["n5X"], "n5Y": st["n5Y"], "rngRun": s}
                    a.update(extra)
                    out.append(a)
    return out


def main(names):
    for name in names:
        # grid and states are the code-2.0 sweeps (frozen binary); everything that
        # reports delay or downlink uses code 2.1, including its own 80 MHz baseline
        if name == "grid":
            run_many(grid_args(), label="grid", version=LEGACY_VERSION)
        elif name == "states":
            run_many(state_args(), label="states", version=LEGACY_VERSION)
        elif name == "states21":
            run_many(state_args(modes=SENS_MODES), label="states21", version=CODE_VERSION)
        elif name == "pilot":
            # steady-state check (R1.4): 30 s window with per-second traces, archived in
            # runs.jsonl; States 1 and 3 and the MLO edge position (100, 195), N4 at MCS 0
            out = []
            for mode in LINK_MODES:
                for x, y in ((70.0, 225.0), (10.0, 180.0), (100.0, 195.0)):
                    for sc in (1, 2):
                        for s in (1, 2, 3):
                            out.append({"scenario": sc, "linkMode": mode, "n4Rate": "EhtMcs0",
                                        "n5X": x, "n5Y": y, "rngRun": s,
                                        "simTime": 33.0, "tputTrace": "true"})
            run_many(out, label="pilot", version=CODE_VERSION)
        elif name == "backhaul":
            for w in (20, 160):
                run_many(state_args({"backhaulWidth": w}, modes=SENS_MODES),
                         label=f"backhaul{w}", version=CODE_VERSION)
        elif name == "sens":
            run_many(state_args({"useTcp": "false"}, modes=SENS_MODES), label="udp", version=CODE_VERSION)
            run_many(state_args({"downlink": "true"}, modes=SENS_MODES), label="downlink",
                     version=CODE_VERSION)
            run_many(state_args({"staDist": 10.0}, modes=SENS_MODES), label="near", version=CODE_VERSION)
        else:
            raise SystemExit(f"unknown experiment {name}")


if __name__ == "__main__":
    main(sys.argv[1:])
