# F1 input-sensitivity check (quantised, cross-seed BSS Load): results (desk, 2026-11-08; no simulation)

Scope note (2026-11-08, after review): F1 tests sensitivity to a quantised, cross-seed utilisation input. It does not
establish deployment realism (no beacon loss, no newcomer load, no time variation). The spec title "measurement-realism
check" is kept unchanged as pre-registered; this results file uses the narrower description.

Rules: F1_SPEC.md (written before any output; sha256 d39107847e67b86e...). Scripts: f1_rescore.py (50d20f601e5c3bb4...),
f1_learners.py (0fdbcff749e8ebc3...). Outputs: f1_fixed_rules.json, f1_learners_{slo,mlo,mloConfined}.json.
d = 0.05 sum-log. 60 contexts per mode (20 positions x 3 N4 rates), 5 seeds each.

## 1. Validity
- Contexts rebuilt per seed equal analyze.build_dataset (asserted for every context and mode).
- D0 (ideal input) reproduces results/policies.json: AirtimeThr and Airtime gain and regret differ by 0.0; every
  learner's gain differs by < 1e-16 and its paired vs-AirtimeThr interval by < 1e-16. The replication is exact.

## 2. H-SUFF: AirtimeThr shortfall against the oracle (cluster bootstrap, positions then seeds)
| Mode | D0 ideal | D1 8-bit | D2 own seed, 8-bit | D3 other seed, 8-bit (primary) | worst single offset (upper bound) | Verdict (D3) |
|---|---|---|---|---|---|---|
| SLO | 0.0014 [-0.0004, 0.0045] | same as D0 | 0.0037 [0.0000, 0.0097] | 0.0027 [0.0003, 0.0065] | 0.0090 | SUFFICIENT |
| MLO | 0.0031 [-0.0001, 0.0072] | same as D0 | 0.0048 [0.0007, 0.0101] | 0.0033 [-0.0000, 0.0077] | 0.0106 | SUFFICIENT |
| MLO-conf. | 0.0020 [0.0000, 0.0047] | same as D0 | same as D0 | 0.0020 [0.0000, 0.0047] | 0.0047 | SUFFICIENT |
Reference (ideal input): RSSI shortfall SLO 0.0461 [0.0173, 0.0799] (INCONCLUSIVE against d), MLO 0.0154
[0.0024, 0.0329], MLO-conf. 0.0021 [-0.0004, 0.0064]. Airtime (residual-airtime rule) under D3: 0.0019 / 0.0037 /
0.0009, all SUFFICIENT.

Where the degraded input changes a choice (AirtimeThr, D3): SLO 28/1200 (context, seed, estimate) choices, all at
N4 MCS 4, ideal MAP 4 -> MAP 1; MLO 20/1200, all at MCS 2, MAP 1 -> MAP 4; MLO-conf. 0/1200. These are the two
rates whose per-seed utilisation differences lie near delta = 0.2 (SLO MCS 4: -0.15 to -0.21; MLO MCS 2: -0.11 to
-0.27; every other rate is at least 0.06 from delta in every seed). Mean cost of a changed choice: SLO 0.053 (max
0.231), MLO 0.013 (max 0.152). The 8-bit quantisation alone changes no choice.

## 3. H-LRN: learner minus AirtimeThr, both on D3 (replicate-averaged per-seed values; training spread separate)
| Mode | UCB1 | LinUCB | Neural |
|---|---|---|---|
| SLO | +0.0008 [-0.0009, 0.0023] (SD 0.0000) | -0.0054 [-0.0108, -0.0012] (SD 0.0016) | -0.0015 [-0.0035, 0.0003] (SD 0.0027) |
| MLO | -0.0057 [-0.0188, 0.0005] (SD 0.0005) | -0.0105 [-0.0190, -0.0032] (SD 0.0064) | +0.0012 [-0.0010, 0.0043] (SD 0.0004) |
| MLO-conf. | -0.0012 [-0.0048, 0.0008] (SD 0.0005) | -0.0332 [-0.0719, -0.0102] (SD 0.0362) | -0.0034 [-0.0075, 0.0003] (SD 0.0017) |
SD = training spread of the gain over the 5 replicates (outside the interval, as in R1).
Every upper bound is below d (largest 0.0043): H-LRN holds in all three modes under the F1 rule. The D3 values are
within 0.0013 of the D0 values for every learner: the stale input moves the learners as little as it moves the rule.
LinUCB under MLO-conf. has an interval below zero but a training SD (0.036) of the same size as its interval width;
that "favours AirtimeThr" reading is not robust to training variation.

## 4. Reading
- Supported: on this grid, replacing the idealised BSS Load (5-seed mean, full precision) by one 8-bit reading from
  another realisation leaves AirtimeThr practically sufficient in all three modes (upper bounds <= 0.011 even for the
  worst single estimate), and no learner gains more than d over it. This bears on one part of the R1 "idealised
  measurements" objection (a precise, same-realisation airtime input) for this topology; it is not deployment realism.
- Mechanism of the robustness: the degraded input rarely crosses delta. When it does (SLO), the cost of a wrong
  choice averages 0.053, i.e. about d. Robustness here therefore comes from few contexts lying near the threshold,
  not from errors being cheap. This is the failure region the airtime model predicts, and F2 (utilisation masking)
  is designed to place contexts in it.
- Weakly informative, as fixed in the spec: the ideal oracle gain over RSSI is below d in every mode as a point
  estimate (SLO 0.046, MLO 0.015, MLO-conf. 0.002), so SUFFICIENT cannot discriminate between rules except in SLO,
  where AirtimeThr (upper 0.0065) separates from RSSI (upper 0.080). No BOUNDARY outcome was possible on this grid.
- Not tested: beacon loss; the newcomer's own load after joining; per-second BSS Load variation (only whole-run means
  are stored); other topologies, compositions and candidate counts (F2-F4). The single-topology objection of R1 is
  unchanged by F1.

## 5. Decision for the author (design Sec. 7)
F1 did not produce a BOUNDARY, so H-SUFF does not fail without runs. The next step in the pre-registered sequence is
the author's decision on F2-F4 (about 580 diag-build runs, about 3.5 h wall time at 3 in parallel, plus unmeasured
effort to build and validate scenario v2.2). Nothing is started.
