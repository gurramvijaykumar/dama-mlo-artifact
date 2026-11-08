# Errata to F2_VALIDATION_SPEC.md v2 (frozen; not edited so its sha256 stays valid)

E1 (2026-11-08, wording only): Sec. 5 says d_N = 0.01 N keeps "a 1.0% geometric-mean throughput
difference". Exactly, exp(0.01) - 1 = 1.005%, i.e. approximately 1%. The threshold and the batch are unchanged.
The same wording applies to "d = 0.05 means 1.0%" at N = 5 (GENERALITY_DESIGN_FEASIBILITY Sec. 1 gives 1.0%).
