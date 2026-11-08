# F1 measurement-realism check: pre-registered rules (written 2026-11-08 BEFORE any F1 output was computed)

Source design: GENERALITY_DESIGN_FEASIBILITY_2026-11-08.md, Sec. 1, 3 (F1), 5. Desk only; no simulation.
Data: the stored grid (results/runs.jsonl, legacy version), contexts built exactly as analyze.build_dataset.
Identity unchanged: same positions, rates, seeds, policies, oracle, candidate set J and sum-log reward.

## Idealisation being removed
R1 (and the manuscript) give every policy the pre-arrival utilisation averaged over the 5 seeds, at full
precision. A station would instead read one BSS Load element: 8-bit channel utilisation (u -> round(255 u)/255),
measured on one network realisation that is not the one it then joins.

## Input conditions
- D0 ideal: as R1. Validity check: AirtimeThr, Airtime, RSSI and Oracle summaries must equal results/policies.json
  (mean gain and mean regret to 1e-9). If not, stop and report.
- D1 quantised: seed mean, 8-bit.
- D2 own-seed: evaluation seed s sees seed s's own pre-arrival utilisation, 8-bit (estimation noise without lag).
- D3 cross-seed (PRIMARY): evaluation seed s sees seed s' != s (all four s'), 8-bit; the reward for seed s is the
  mean over the four s' of rew[a(s, s')][s] (expected outcome under a stale estimate from another realisation).
  Worst single offset also reported (descriptive).
Choices may differ per seed in D2/D3; the reward of seed s is always that seed's stored reward for the chosen MAP.
The oracle stays the context-level hindsight oracle over J (as R1); RSSI is unaffected by u.

## Quantities (per link mode: slo, mlo, mlo_conf)
- Shortfall S = Oracle - AirtimeThr (sum-log), per-seed values -> analyze.cluster_boot (positions, then seeds).
- Also: AirtimeThr - RSSI, Airtime shortfall, number of (context, seed) choices that differ from D0.
- d = 0.05 (fixed in the design). Training variation does not apply to fixed rules.

## Outcomes (per mode, D3 primary)
- SUFFICIENT: upper 95% bound of S < d.
- BOUNDARY: lower 95% bound of S > d. Predicted only where utilisation differences lie near delta = 0.2.
- INCONCLUSIVE: otherwise.
- MLO caveat fixed now: the ideal MLO oracle gain over RSSI is 0.015 < d, so a SUFFICIENT MLO result is weakly
  informative (RSSI alone passes). SLO (ideal gain 0.116) is where F1 can discriminate.
No Holm adjustment is needed for SUFFICIENT; any BOUNDARY claim is Holm-adjusted over the 3 modes.

## Learners (H-LRN under F1), second step in the same check
Learners trained exactly as R1 (ideal contexts, leave-one-position-out, 5 replicates), then executed on D3 test
contexts. Paired learner - AirtimeThr (both on D3), cluster bootstrap on replicate-averaged per-seed values (as R1;
training variation reported separately as the replicate spread). H-LRN holds in a mode if every learner's upper
bound < d. Retraining on degraded contexts is NOT part of F1.

## What F1 does not test
Beacon loss, the newcomer's own load after joining, per-second BSS Load variation (not stored; utilisation is a
whole-run mean), other topologies (F2-F4).
