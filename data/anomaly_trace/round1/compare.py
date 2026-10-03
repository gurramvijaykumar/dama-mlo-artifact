"""Compare diagnostic traces of the 2.1 zero-throughput anomalies (failing vs control seed)."""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import simlib as S
d = os.path.dirname(os.path.abspath(__file__))
cache = S._load()
for line in open(os.path.join(d, "jobs.txt")):
    name, *args = line.split()
    p = os.path.join(d, name + ".txt")
    if not os.path.exists(p):
        print(f"== {name}: not finished"); continue
    text = open(p).read()
    a = dict(x[2:].split("=", 1) for x in args)
    out = S.parse(text)
    ref = cache.get(S._key(a, S.CODE_VERSION))
    diff = [k for k, v in (ref or {}).items() if out.get(k) != v]
    rc = re.search(r"^rc (-?\d+)", text, re.M).group(1)
    print(f"\n== {name}  rc={rc}  "
          f"reproduces stored record: {ref is not None and not diff} ({len(ref or {})} keys, {len(diff)} differ {diff[:5]})")
    print("  tput  :", {k[5:]: round(v, 3) for k, v in out.items() if k.startswith("tput_")})
    print("  frames:", {k[7:]: int(v) for k, v in out.items() if k.startswith("frames_")})
    print("  txair :", {k[6:]: round(v, 3) for k, v in out.items() if k.startswith("txair_")})
    print("  util  :", {k[5:]: round(v, 3) for k, v in out.items() if k.startswith("util_")})
    print("  dN    :", {k[3:]: int(v) for k, v in out.items() if k.startswith("dN_")}, " dMiss:",
          {k[6:]: int(v) for k, v in out.items() if k.startswith("dMiss_")})
    print("  apframes:", {k[9:]: int(v) for k, v in out.items() if k.startswith("apframes_")})
    for l in re.findall(r"^E .*$", text, re.M)[:40]: print("  ", l)
    for l in re.findall(r"^S .*$", text, re.M): print("  ", l)
    for l in re.findall(r"^M .*$", text, re.M): print("  ", l)
    for l in re.findall(r"^L \S+ (?:decoded_data|tx_data|tx_assoc|decoded_assoc|arrival_beacon|decoded_beacon|txDataMpdus|macTxDataFailed|macTxFinalDataFailed|rxDataPerSec|txDataPerSec)\b.*$", text, re.M):
        print("  ", l)
