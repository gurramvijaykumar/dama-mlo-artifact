# Generality design and feasibility step (desk, 2026-11-08; NO simulation authorised)

Purpose: before deciding on any experiment, specify the claim, the closest-work distinction, the
minimum discriminating scenarios, measurement realism, validity rules, uncertainty (including training variation)
and a measured cost. Then decide whether the experiment is worth doing; if no consequential, distinguishable claim
survives, stop the submission path.
Corrections adopted from the review of CONTRIBUTION_ASSESSMENT_2026-11-08.md:
- more scenarios do not create a contribution by themselves;
- no capture-ratio target alone;
- a failure boundary specified in advance is a valid outcome;
- hidden-station cases are not excluded automatically;
- "weeks" and the "lower-quartile ceiling" were estimates, and are withdrawn as conclusions.

Study identity (unchanged): association of an arriving station under SLO / MLO / MLO-confined in the ns-3 mesh;
policies RSSI, LoadAware, Airtime, AirtimeThr (delta = 0.2 as in R1), UCB1, LinUCB, DAMA-MLO and the empirical oracle;
sum-log utility.

## 1. The precise claim (pre-registered form)
H-SUFF: under MLO, the beacon-only threshold rule AirtimeThr is practically sufficient, i.e. its absolute
utility shortfall against the empirical oracle is below a practical-effect threshold d, including under conditions
chosen because the airtime model predicts that a utilization proxy can mislead.
H-LRN: no learner improves on AirtimeThr by more than d, measured by the paired learner-minus-AirtimeThr difference.
Practical-effect threshold d = 0.05 sum-log. With 5 stations this is exp(0.05/5) - 1 = 1.0% higher geometric-mean
per-station throughput. It is of the order of the seed-to-seed SD in the named states (0.03-0.09). Consequence: on the
EXISTING grid the MLO oracle gain over RSSI (0.015) is already below d, so there even RSSI is practically sufficient.
[CORRECTED 2026-11-08 during F1: the SLO gain was given here as 0.116; that figure has no source. The stored SLO
oracle gain over RSSI is 0.046 (results/policies.json; manuscript l. 667), also below d as a point estimate, with
RSSI's upper 95% bound 0.080.] H-SUFF therefore discriminates only in families where the model predicts a
larger available gain (F2, F3); the existing grid alone cannot test it. Alternative for the author: d = 0.10
(2.0%). The threshold is fixed before any run and is reported with the absolute shortfall, never as a ratio alone.
Outcomes, fixed now:
- SUFFICIENT in a family if the upper 95% bound of (oracle - AirtimeThr) < d.
- BOUNDARY if the lower 95% bound > d in a family where the model predicted failure (Sec. 3). This is a reproducible
  condition under which the threshold fails, and it answers the original question: "when does association still
  matter under MLO, and when does a simple rule suffice?"
- INCONCLUSIVE otherwise (interval straddles d).
- Unexpected BOUNDARY in a family with no predicted failure: reported, but not claimed as a boundary result without a
  mechanism.

## 2. Distinction from the closest work
- Zhang et al. 2024 (IoT J.): a controller with the full per-pair rate matrix and a sum-rate objective, so no
  anomaly and no beacon-only rule. H-SUFF instead asks whether decentralized, beacon-only information suffices under
  a proportional-fair objective with the anomaly present. Different information and objective; same decision.
- Bejerano 2004 / Shakkottai 2006 / Heusse 2003: they predict the SLO result and the direction under MLO (per-link
  reduction, REBUILD Part 3). The distinguishing content of H-SUFF is not a new mechanism. It is the empirical
  boundary of a beacon proxy under MLO, under proxy-defeating conditions, with a learned-policy comparison against
  an oracle. Prior learned MLO work (link activation / channel selection; e.g. Ali & Almagrabi 2026) uses no oracle or
  simple-rule baseline.
- Honest limit: if every family comes out SUFFICIENT, the result confirms the per-link prediction plus beacon
  observability. That is incremental. If a BOUNDARY appears where predicted, the result is more informative.

## 3. Minimum discriminating scenario families (each with a model prediction fixed now)
| Family | Condition | Why it could defeat the threshold (airtime model) | Prediction | Simulation needed? |
|---|---|---|---|---|
| F1 Measurement realism | Same grid; the utilization input degraded to the BSS Load element: 8-bit quantization (u -> round(255u)/255), computed from a different seed's pre-arrival run (lag / estimation error), with the newcomer excluded as now | The threshold acts on u; estimation error moves it across delta = 0.2 | Small effect where the u differences are far from delta; larger near delta | NO: re-score the existing grid (policies' choices recomputed from degraded contexts; rewards are stored). Desk |
| F2 Utilization masking | Two candidates with EQUAL saturated utilization but different composition: MAP 4 = one slow (MCS 0) + one fast station; MAP 1 = three or four fast stations | Utilization near saturation on both hides which AP holds the slow station; the anomaly penalises joining the slow-station AP | AirtimeThr = RSSI (no u difference), and the oracle differs, so a shortfall is predicted when RSSI favours the slow-station AP | YES: new station sets (scenario v2.2) |
| F3 Per-band asymmetry (MLO) | A candidate whose 6 GHz link is eligible but within 1-3 dB of the detection level, with the other candidate symmetric | The utilization proxy ignores per-link rate; a weak link is a slow link | Shortfall when RSSI picks the asymmetric AP | YES (positions exist in the grid region; may reuse grid positions plus a 6 GHz offset parameter) |
| F4 Three candidates | A third AP MLD as candidate | The two-candidate rule ("the other candidate") is undefined; generalize to argmin u | Fixed rules and the oracle only: DAMA-MLO's network has two outputs, so H-LRN is NOT tested in F4 (identity kept) | YES (scenario v2.2) |
SLO is run alongside MLO in every family (the ablation contrast); MLO-confined is optional.
Recommended order: F1 first, desk only. If F1 already gives a BOUNDARY under realistic BSS Load, H-SUFF fails without
any run.

## 4. Validity rules (from the 2026-11-08 traces)
- Candidate-rule violations: screened geometrically BEFORE runs (per-link -82 dBm with the 0.029 dB offset). An action
  outside J is a forced choice, as in R1, never a comparison.
- Legitimate difficult conditions (hidden stations, near-threshold links that are eligible, start-up ordering): KEPT
  in every analysis and labelled. Geometry flags are computed in advance (grid_hidden_screen.py extended).
- Implementation failures (watchdog disassociation, dead backhaul ARP, stuck ADDBA, zero delivery with no physical
  explanation): detected by running EVERY simulation with the diag build (same cost as untraced; records ARP, TCP, BA,
  association and per-second TPUT). Reported. Primary analysis keeps all runs. One sensitivity analysis excludes only
  failures diagnosed by a pre-set signature. An undiagnosed zero-delivery run is NOT excluded (lesson of C6 F2).
- Known instrumentation limits carried forward: the sniffer misses aggregated frames; BlockAck credits unverified;
  1 s TPUT bins.

## 5. Uncertainty analysis (fixed now)
- Shortfall and learner differences: a three-stage cluster bootstrap (positions -> training replicates -> seeds), so
  TRAINING VARIATION is inside the interval (unlike R1). Report the per-replicate spread as well.
- SUFFICIENT / BOUNDARY decisions as in Sec. 1 (interval vs d). For H-LRN, "no learner improves by more than d" needs
  the upper bound of (learner - AirtimeThr) < d for every learner; otherwise INCONCLUSIVE.
- Multiplicity: Holm across families x configurations for the BOUNDARY claims; unadjusted intervals reported too.
- Seeds: 5 per context as in the grid. Increase to 10 only if pre-computed power shows that 5 cannot resolve d
  (seed SD 0.03-0.09 -> 5 seeds give a per-context SE of about 0.015-0.04).

## 6. Cost (measured where possible)
- Measured: diag-build run wall time median 61 s (57-89 s, n = 38, 2026-11-08); machine with 4 cores and 15 GB
  (about 100 MB per run). At 3 runs in parallel, about 3.4 min of wall time per 10 runs.
- Run counts (estimate from the design; positions to be fixed by the geometry screen):
  F1 0 runs (desk); F2 about 2 compositions x 6 positions x 2 modes x 2 actions x 5 seeds + pre-arrival = about 260;
  F3 about 6 x 2 x 2 x 5 + pre-arrival = about 130; F4 about 6 x 2 x 3 x 5 + pre-arrival = about 190. Total about
  580 runs, about 10 CPU-hours, about 3.5 h of wall time at 3 in parallel. Measured per-run time x estimated count.
- NOT measured: implementation effort for scenario v2.2 (station sets, a third candidate, a 6 GHz offset) and its
  validation (v2.2 must reproduce v2.0 outputs on unchanged configurations: about 20 check runs); the learner
  re-training analysis (about 25 min per family per mode, from today's measured 4.9 s per training).

## 7. Decision gate (author)
A consequential, distinguishable claim can be specified (H-SUFF / H-LRN with d, and BOUNDARY as a pre-registered
alternative outcome). Families F1 and F2 have model-based failure predictions, so the test can discriminate.
Recommended sequence:
1. F1 (desk, no run): re-score the existing grid with realistic BSS Load inputs.
2. Decide on F2-F4 (about 580 runs) only after F1, and only if the author accepts the cost.
