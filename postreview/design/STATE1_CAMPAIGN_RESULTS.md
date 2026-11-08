# State 1 start-up campaign -- RESULTS (2026-11-08)

Plan: STATE1_STARTUP_CHECK.md Sec. 5 (rules A0-A6). Author approval 2026-11-08. 38 new runs (diag build 746687e2...;
runner run_state1_campaign.py e0c645e1...) plus 2 reused traces (SLO MAP 4 seeds 9 and 10, case_cd_trace). Analysis
analyze_state1_campaign.py (2476342e...; written before the results); output state1_campaign_analysis.json.
Validity: 38/38 runs exit 0, every stored field identical, no My file. No seed or run is excluded.

A0 resolution: start bins are 1 s, from the per-station TPUT lines. ARP times are 0.5 s polls: "1.5 s" means REACHABLE
first seen at the 1.5 s poll, i.e. resolved in (1.0, 1.5] s. A6: MAC drops are not measured.

## Results (State 1, N4 MCS 0; arms: N5 -> MAP 1 / N5 -> MAP 4; seeds 1-10)
| | MAP 1 arm late starts | MAP 4 arm late starts | of which MAP 4 next-hop ARP first REACHABLE at 2.5 s | late with ARP at 1.5 s |
|---|---|---|---|---|
| SLO | 0/10 | 3/10 (seeds 6, 8, 9) | seeds 8, 9 | seed 6 (only N5 late, bin 2) |
| MLO | 0/10 | 5/10 (seeds 1, 2, 5, 7, 10) | seeds 1, 2, 10 | seeds 5 (bin 4), 7 (bin 2) |

- No station ever failed to start. Every paired N5 difference (MAP 1 arm minus MAP 4 arm) is defined, ranging from 0
  to -3 bins.
- In the late MAP 4 runs where the next-hop ARP resolved late, N3, N4 and N5 all start late together, the pattern of
  seed 9.
- In SLO seed 6, only N5 is late. In MLO seeds 5 and 7, all three start late although the ARP had resolved by 1.5 s.
  Their cause is not identified.
- A5 (descriptive, n = 10 per mode, no test): mean gap (MAP 1 - MAP 4)
  - SLO: late seeds 0.631, others 0.728 (median 0.669). The outlier seed 10 (gap 1.407) is NOT a late-start seed.
  - MLO: late seeds 0.263, others 0.219.

## Reading (bounded)
- Start-up delays are common in State 1. They fall only on the MAP 4 arm: 3/10 seeds under SLO and 5/10 under MLO;
  0/10 on the MAP 1 arm in either mode. So start-up timing is unevenly distributed across the arms of the ablation
  comparison. The arm imbalance is larger under MLO.
- Five late starts are accompanied by late ARP resolution at MAP 4's next hop. ARP is not separately established as
  their cause in all five; it is established only in the traced seed 9. Three late starts show no late ARP at this
  resolution, and their cause is unidentified.
- Late starts do not show a consistent directional association with the gap across the two modes. Under SLO the late
  seeds have a smaller mean gap (0.631 vs 0.728); under MLO a slightly larger one (0.263 vs 0.219). Under SLO the gap is
  dominated by the non-late seed 10. This is descriptive and does not establish that start-up timing has no effect.
- Not established: a causal effect of start-up timing on the gap (would need an intervention that preserves the
  experiment, not proposed); the cause of the 3 late starts without late ARP; the prevalence of seed-10-type MAC drops;
  the validity of the ablation claim (0.70 -> 0.24).
