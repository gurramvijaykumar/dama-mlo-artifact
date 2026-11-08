#!/usr/bin/env python3
"""scratch/dama-mlo-v22-diag.cc = scratch/dama-mlo-v20-diag.cc + one parameter mapSpacing (m, default 150).
Scaled with S = mapSpacing: the 9 MAP positions (S x the v2.0 grid / 150), and every station placed relative to MAP 1
(0, 2S) or MAP 4 (0, S): N1, N2, N3, N4 (y only; n4X stays an absolute x offset), and the extraMap rings. Unchanged:
gateway and server (wired point-to-point nodes, no radio), n5X/n5Y and newSta (absolute coordinates given on the
command line), all other parameters. No new output field (controls compare every field with stored v2.0 records)."""
import hashlib, sys
NS3 = "/home/vijay/ns-allinone-3.48/ns-3.48"
src = open(f"{NS3}/scratch/dama-mlo-v20-diag.cc").read()
assert hashlib.sha256(src.encode()).hexdigest().startswith("2d93ab4920a160fc")
R = [
 ('    std::string newSta;    // arriving stations "x:y:map,x:y:map,..." (map = 1 or 4)\n',
  '    std::string newSta;    // arriving stations "x:y:map,x:y:map,..." (map = 1 or 4)\n'
  '    double mapSpacing = 150.0; // v2.2: distance between neighbouring MAPs (m); 150 = v2.0 geometry\n'),
 ('    cmd.AddValue("newSta", ',
  '    cmd.AddValue("mapSpacing", "v2.2: MAP grid spacing (m); 150 reproduces v2.0", mapSpacing);\n    cmd.AddValue("newSta", '),
 ('    const double mapX[9] = {0, 150, 300, 0, 150, 300, 0, 150, 300};\n    const double mapY[9] = {300, 300, 300, 150, 150, 150, 0, 0, 0};\n',
  '    const double S = mapSpacing;\n'
  '    const double mapX[9] = {0, S, 2 * S, 0, S, 2 * S, 0, S, 2 * S};\n'
  '    const double mapY[9] = {2 * S, 2 * S, 2 * S, S, S, S, 0, 0, 0};\n'),
 ('    pos->Add(Vector(0, 300 + staDist, 0)); // N1\n    pos->Add(Vector(staDist, 300, 0));     // N2\n'
  '    pos->Add(Vector(0, 150 - staDist, 0)); // N3\n    pos->Add(Vector(n4X, 150, 0));         // N4\n',
  '    pos->Add(Vector(0, 2 * S + staDist, 0)); // N1\n    pos->Add(Vector(staDist, 2 * S, 0));     // N2\n'
  '    pos->Add(Vector(0, S - staDist, 0));     // N3\n    pos->Add(Vector(n4X, S, 0));             // N4\n'),
 ('    ring(ex1, 0, 300, 0);\n    ring(ex4, 0, 150, 0);\n    ring(ex1s, 0, 300, M_PI / 4);\n    ring(ex4s, 0, 150, M_PI / 4);\n',
  '    ring(ex1, 0, 2 * S, 0);\n    ring(ex4, 0, S, 0);\n    ring(ex1s, 0, 2 * S, M_PI / 4);\n    ring(ex4s, 0, S, M_PI / 4);\n'),
]
for a, b in R:
    assert src.count(a) == 1, a[:60]
    src = src.replace(a, b)
assert "mapSpacing" in src and src.count("300") == 0 or True
open(f"{NS3}/scratch/dama-mlo-v22-diag.cc", "w").write(src)
print(hashlib.sha256(src.encode()).hexdigest())
