# Stage A result and Stage P frozen choices (2026-11-08). Stage B NOT run (gate 3 pending)

## Stage A (approved; executed)
- Controls first (amendment A1): 4/4 exit 0. v2.2 at its defaults matches the stored v2.0 records in every field
  (41, 47, 55 and 64 fields; 0 mismatches). ns-3.48/My absent.
- Pre-arrival: 30/30 exit 0, wall time 79-163 s. Health (amendment A2, < 0.01 Mbit/s): 1 flagged run of 34 (2.9%,
  below the 5% pause rule).
- The flagged run is A_T2_mlo_pre_s1. N3 and N4 delivered 0.00009 Mbit/s (0 data frames), with TCP stuck in
  SYN_SENT. MAP 6's backhaul ARP entry for 10.1.1.5 never resolved, and MAP 4's access-side ARP table stayed empty.
  This matches the documented backhaul-ARP fault class; the root cause is undiagnosed. The run is kept.
- Pre-arrival u4 - u1 (link-averaged), seeds 1-5:
  - T1 SLO 0.47-0.50; MLO 0.52-0.67.
  - T2 SLO 0.34-0.38; MLO -0.45 (the flagged seed), then 0.50-0.57.
  - T3 SLO 0.19-0.29; MLO 0.10-0.16.

## Stage P (desk): frozen policy choices (stageP_choices.json)
Choices at the 8 frozen positions per condition. "Departs" = the share of (position, seed) choices where AirtimeThr
differs from RSSI; RSSI chooses MAP 4 at every selected position by construction.
| Cell | AirtimeThr departs: SEEDMEAN / OWNSEED | Learners choosing MAP 4 (DAMA-MLO / UCB1 / LinUCB, SEEDMEAN) |
|---|---|---|
| T1 SLO | 1.00 / 1.00 | 0.00 / 0.00 / 0.00 |
| T1 MLO | 1.00 / 1.00 | 0.00 / 0.00 / 0.00 |
| T2 SLO | 1.00 / 1.00 | 0.00 / 0.00 / 0.00 |
| T2 MLO | 1.00 / 0.80 | 0.00 / 0.00 / 0.00 |
| T3 SLO | 1.00 / 0.60 | 0.33 / 0.38 / 0.00 |
| T3 MLO | 0.00 / 0.00 | 0.20 / 0.38 / 0.00 |
Within most cells AirtimeThr makes the same choice at every position: MAP 1 in five cells, and MAP 4 (= RSSI) in
T3 MLO.

## Analysis code (frozen; stageB_analysis.py)
- --check-wrapper: the condition-geometry wrapper at S = 150 reproduces the stored fixed-rule gains exactly (all
  modes and rules).
- --selftest on T0 descriptive cells runs end to end. In the T0 decision-relevant region (MCS 0), G = 0.341 [0.247,
  0.430] under SLO and 0.159 [0.082, 0.243] under MLO, and AirtimeThr equals the oracle. The learners are trained
  in sample there, so this is descriptive only.
- A synthetic Stage B tree (MAP 1 = 1, MAP 4 = 0, one missing run) returns the expected G, D, S, learner
  differences and departure rates; Holm step-down was checked on a known example. A departure-rate bug found by
  this test was fixed before freezing.
- run_stageB.py --dry: 480 unique tags; nothing executed.
