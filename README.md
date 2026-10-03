# Airtime-aware user association under Wi-Fi 7 MLO: code and data

Code and raw simulation results for the revised manuscript

> When Does Airtime-Aware User Association Matter in IEEE 802.11be
> Multi-Link Wireless Mesh Networks?
> (Computer Networks, manuscript COMNET-D-26-05038; the submitted version was
> titled "Decentralized Anomaly-Mitigating User Association in IEEE 802.11be
> Multi-Link Wireless Mesh Networks")

Author: G. Vijaya Kumar, SCIM Govt. College, Tanuku, Andhra Pradesh, India.

Every number in the revised manuscript comes from one ns-3 run stored in
`data/runs.jsonl`. The analysis scripts read that file and nothing else. The
trace runs used to diagnose failed or stalled runs are included as raw output.

## Layout

- `scratch/dama-mlo-v2.0.cc`, `scratch/dama-mlo-v2.1.cc`: the two versions of
  the ns-3 scenario (Wi-Fi 7 mesh, 3x3 MAP grid, slow station N4 at MAP 4,
  arriving station N5). See "Scenario versions" below.
- `scripts/simlib.py`: runs the scenario and caches each run as one JSON line.
- `scripts/experiments.py`: the sweeps (`states`, `grid`, `backhaul`, `sens`).
- `scripts/arrivals.py`: the sequential multi-station arrival experiment.
- `scripts/policies.py`: association policies (RSSI, LoadAware, Airtime,
  AirtimeThr, UCB1, LinUCB, neural contextual bandit).
- `scripts/analyze.py`: builds the tables (`ablation`, `policies`, `states`).
- `scripts/make_tables_figs.py`: writes every table (`tables/tab_*.tex`) and
  figure (`figures/fig_*.pdf`) of the manuscript from the cached runs.
- `data/runs.jsonl`: all raw runs. Each line holds the full argument set and
  every metric the scenario printed.
- `data/*.json`: analysis outputs used for the tables and figures.
- `data/failed_runs.jsonl`: runs that aborted in ns-3.48 (the downlink run of
  Section 8.5). They are reported, never imputed.
- `tables/`, `figures/`: the tables and figures of the manuscript as generated
  from the included data.
- `scripts/diag_policy_breakdown.py`, `scripts/diag_pilot.py`,
  `scripts/diag_arrivals.py`: read-only checks behind numbers quoted in the
  text of Section 7 (per-position policy gains and utility-floor rescoring,
  steady-state check, per-trial arrival results). Outputs:
  `data/diag_*.json`.
- `scripts/check_v21.py`, `data/validate_v21.json`: check that a version 2.1
  build reproduces the validation runs of its development build.
- `scratch/dama-mlo-trace.cc`: version 2.1 of the scenario with a per-link
  trace of N5 and its serving access point (cell-edge diagnosis, Section 8.2)
  and, with `--psTrace=true`, a power-save trace (Section 8.5).
- `scratch/dama-mlo-diag.cc`: `dama-mlo-trace.cc` with an added MAC-state and
  ARP trace (`--diagTrace=true`), used for the failed-run diagnosis in
  Sections 7.3 and 7.4.
- `data/edge_trace/`, `data/ps_trace/`, `data/addba_screen/`,
  `data/anomaly_trace/`: raw output of the trace runs; see "Trace runs" below.
- `secondary_analysis/`: the UDP analysis excluding trace-confirmed
  ADDBA-expiry cases (Section 7.4, Table `tab_udp_excl`); see below.
- `MANIFEST.txt`: file list with SHA-256 checksums.

## Scenario versions

The results come from two versions of the scenario. Each record in
`data/runs.jsonl` states its version in the field `codeVersion`; records
without the field are version 2.0. The scripts select the version per
experiment, and a cached result is reused only for the same version.

| Version | Source | Experiments (`experiments.py` / `arrivals.py`) | Used for |
|---|---|---|---|
| 2.0 | `scratch/dama-mlo-v2.0.cc` | `states`, `grid` | named states, grid ablation, policy comparison and training variants |
| 2.1 | `scratch/dama-mlo-v2.1.cc` | `states21`, `backhaul`, `sens`, `pilot`, `arrivals.py` | its own 80 MHz baseline, backhaul width, UDP/downlink/near sensitivity, delay split, steady-state check, sequential arrivals |
| 2.1 + trace | `scratch/dama-mlo-trace.cc` | `run_edge_trace.sh`, `run_ps_trace.sh` | cell-edge diagnosis (Section 8.2), power-save trace (Section 8.5) |
| 2.1 + diag trace | `scratch/dama-mlo-diag.cc` | `run_addba_screen.sh` | zero-output screen and ADDBA-expiry diagnosis (Sections 7.3, 7.4) |

The learners of the sequential-arrival experiment are trained on the version 2.0
grid, while the arrivals themselves are simulated with version 2.1.

Version 2.1 adds a matched per-packet delay split (access, wireless backhaul,
wired) and, in downlink runs, sends to each slow station at its fixed rate.
Its uplink throughput and utilization outputs are identical to version 2.0
for the same arguments. The two trace programs print the same `R` lines as
version 2.1; every trace run was checked to reproduce its stored record
exactly.

## Requirements

- ns-3.48 (https://www.nsnam.org/releases/ns-3-48/). No changes to the ns-3
  source are needed; the scenario uses stock modules only.
- Python 3.10 or later with NumPy, SciPy and matplotlib (tested with Python
  3.12.3, NumPy 1.26.4, SciPy 1.11.4, matplotlib 3.6.3). The table preview of
  `make_tables_figs.py` also needs pdflatex.

## Build

`scripts/simlib.py` runs version 2.0 from
`build/scratch/ns3.48-dama-mlo-v2.0-frozen` and version 2.1 from
`build/scratch/ns3.48-dama-mlo-v2-optimized`. Build version 2.0 first, keep a
copy of its binary, then build version 2.1 under the same name:

```bash
NS3=/path/to/ns-3.48
cd $NS3 && ./ns3 configure --build-profile=optimized && cd -
cp scratch/dama-mlo-v2.0.cc $NS3/scratch/dama-mlo-v2.cc
(cd $NS3 && ./ns3 build dama-mlo-v2)
cp $NS3/build/scratch/ns3.48-dama-mlo-v2-optimized $NS3/build/scratch/ns3.48-dama-mlo-v2.0-frozen
cp scratch/dama-mlo-v2.1.cc $NS3/scratch/dama-mlo-v2.cc
(cd $NS3 && ./ns3 build dama-mlo-v2)
cp scratch/dama-mlo-trace.cc $NS3/scratch/ && (cd $NS3 && ./ns3 build dama-mlo-trace)
cp scratch/dama-mlo-diag.cc $NS3/scratch/ && (cd $NS3 && ./ns3 build dama-mlo-diag)
```

Each binary prints its version (`R codeVersion`); simlib checks it before a
run is stored. Adding or removing a scratch file makes CMake rebuild all of
ns-3; this does not change results.

## Reproduce the tables from the included data

No simulation is needed. Copy the data into the folder the scripts expect:

```bash
cd scripts
mkdir -p results && cp ../data/*.json ../data/*.jsonl results/
python3 make_tables_figs.py --from-json   # about 15 s
```

`--from-json` reads the policy comparison from `results/policies*.json`.
Without it, `make_tables_figs.py` retrains every learner (five repetitions per
configuration), which takes about 75 minutes on a 4-core machine and gives the
same numbers. All other tables are always recomputed from `runs.jsonl`. The
outputs are written to `scripts/results/`, `scripts/tables/` and
`scripts/figures/`; they match the files in `tables/`, `figures/` and `data/`.

The text checks are rerun with:

```bash
python3 diag_pilot.py
python3 diag_arrivals.py
python3 diag_policy_breakdown.py      # retrains the learners; slow
```

## Rerun the simulations

Point the scripts at your ns-3 tree and run the sweeps. Runs already in
`results/runs.jsonl` are skipped, so start from an empty `results/` folder to
simulate everything again.

```bash
export NS3_DIR=/path/to/ns-3.48
cd scripts
python3 experiments.py states grid                # version 2.0
python3 experiments.py states21 backhaul sens     # version 2.1
python3 arrivals.py --trials 15 --k 5 --mode mlo --learners
python3 arrivals.py --trials 15 --k 5 --mode mloConfined --learners
python3 experiments.py pilot                      # version 2.1
python3 analyze.py ablation policies states
```

Each run takes about 2 CPU-minutes. The full set takes several days on a
4-core machine. The scenario has no fading, so results for a given seed
(`rngRun`) are repeatable on the same ns-3 version.

## A single run

```bash
./ns3 run "dama-mlo-v2 --linkMode=mlo --scenario=1 --n5X=70 --n5Y=225 \
  --n4Rate=EhtMcs0 --rngRun=1"
```

The scenario prints `R <key> <value>` lines: per-flow throughput and delay,
per-link AP utilization (`util_MAP1_L0` and so on) and access delay
(`probe_*`). Run it with `--help` to list all options.

## Trace runs

### Cell-edge trace (Section 8.2)

Build the trace scenario like the main one (`./ns3 build dama-mlo-trace`),
then:

```bash
export NS3_DIR=/path/to/ns-3.48
cd scripts
./run_edge_trace.sh                 # writes results/edge_trace/<run>.txt
python3 summarize_edge_trace.py     # prints the table, writes summary.json
python3 summarize_edge_trace.py ../data/edge_trace   # the included runs
```

Besides the `R` lines, the trace scenario prints `E` (association, link setup,
block-ack agreement and first MAC drops), `S` (per-second state of N5), `M`
(MAC drop and timeout counters) and `L` lines (per link and direction:
received power of every signal from the peer, PHY drop reasons, decoded SNR,
transmitted frames and per-second data MPDUs). `up_<l>` is N5 to the access
point on link `l` (0 = 5 GHz, 1 = 6 GHz), `dn_<l>` the reverse. Counts cover
the whole run, not only the measurement window. `--n5Links=5` makes N5 a
single-link 5 GHz device.

### Power-save trace of the downlink runs (Section 8.5)

```bash
export NS3_DIR=/path/to/ns-3.48
cd scripts
./run_ps_trace.sh                   # SEEDS="1 2 ... 10" for all seeds
python3 summarize_ps_trace.py ../data/ps_trace   # the included runs
```

`data/ps_trace/` holds one output per unique downlink run and
`summary.json`.

### Zero-output screen and ADDBA-expiry diagnosis (Sections 7.3, 7.4)

`screen_zero_delivery.py` lists every run of `runs.jsonl` in which a station
transmitted or delivered nothing over the whole run (341 runs) and writes
`candidates.json` and `jobs.txt`. `run_addba_screen.sh DIR` reruns each
candidate listed in `DIR/jobs.txt` with `dama-mlo-diag`, and
`summarize_addba_screen.py` checks that each rerun reproduces its stored
record and classifies it (`classification.json`).

```bash
export NS3_DIR=/path/to/ns-3.48
cd scripts
python3 screen_zero_delivery.py results/addba_screen
./run_addba_screen.sh results/addba_screen
python3 summarize_addba_screen.py results/addba_screen
python3 summarize_addba_screen.py ../data/addba_screen   # the included runs
```

`data/addba_screen/fmt_mismatch_20261003/` holds the first output of six runs
whose throughput-trace lines were printed with a different number format by
an earlier build of `dama-mlo-diag.cc`. They were rerun with the included
source; the reruns are the files in `data/addba_screen/`. The other 335 runs
were made with the earlier build. The fix changes only the format of the `T`
lines, which only these six runs print.

`data/anomaly_trace/round1` to `round3` are the earlier, targeted trace rounds
of the same diagnosis (two UDP runs and one 160 MHz backhaul run, each with a
control seed), with their notes (`FINDINGS*.md`). Round 1 used
`dama-mlo-trace`, rounds 2 and 3 development versions of `dama-mlo-diag`; the
`run.sh` files are kept as used.

## Secondary analysis: UDP excluding trace-confirmed ADDBA-expiry cases

The primary analysis keeps all runs. The secondary analysis removes the six
affected UDP runs and, for each, the run with the same seed on the other MAP
option (12 of 260 UDP runs, listed in `excluded_addba.jsonl`). To reproduce
it, after the primary tables above:

```bash
cd scripts
E=analysis_excl_addba_20261003
mkdir -p $E/results
python3 ../secondary_analysis/make_excl_runs.py results/runs.jsonl \
    ../secondary_analysis/excluded_addba.jsonl $E/results/runs.jsonl
cp results/failed_runs.jsonl ../secondary_analysis/excluded_addba.jsonl $E/results/
cp simlib.py experiments.py arrivals.py policies.py analyze.py $E/
cp ../secondary_analysis/make_tables_figs_excl.py $E/make_tables_figs.py
(cd $E && python3 make_tables_figs.py)        # retrains the learners; slow
cp ../secondary_analysis/compare_excl_addba.py . && python3 compare_excl_addba.py
cp $E/comparison.json ../secondary_analysis/ && python3 ../secondary_analysis/make_tab_udp_excl.py
```

`compare_excl_addba.py` writes `COMPARISON.md` and `comparison.json` into
`$E`, and `make_tab_udp_excl.py` writes `tables/tab_udp_excl.tex`. Only the
UDP sweep changes; `COMPARISON.md` lists every comparison of both analyses.
`make_tables_figs_excl.py` is a copy of an earlier version of
`make_tables_figs.py`, taken before the final table layout and caption edits,
with coverage labels that count the excluded runs. It has no `--from-json`
option.

## Notes on the data

- `data/runs.jsonl` also holds early runs with `n4Rate=EhtMcs7`. At N4's
  distance no MCS 7 frame is decoded, so these runs were dropped from the
  design and are ignored by the analysis. They are kept for completeness.
- Default paths in `simlib.py` and the run scripts point to the author's
  machine; set `NS3_DIR` (or `BIN`) to your ns-3 tree.
- The original submission used a different scenario
  (`user-association-wmn.cc`). It is not part of this archive, because the
  revised manuscript reports no number from it.

## License

GNU General Public License v2.0 only (GPL-2.0-only), the same license as ns-3.
