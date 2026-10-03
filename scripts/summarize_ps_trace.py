"""Summarize the power-save traces of run_ps_trace.sh (failed-run follow-up, 2026-10-01).

For every traced run: exit status; station links that the AP still holds in
power-save mode at the end of the run (and since when); for N5's links, whether
anything was decodable on that link in either direction (AP decoded N5 frames,
N5 decoded AP frames; ACK/CTS "_any" counts are excluded, since they carry no
transmitter address and include other stations' frames) and the mean received power; group-addressed frames the
AP sent per link; N5 and aggregate results; and whether the traced result
equals the sweep's stored result in runs.jsonl (same arguments, code 2.1).

Usage: python3 summarize_ps_trace.py [dir]   (default results/ps_trace)
Writes <dir>/summary.json and prints one line per run.
"""

import json
import os
import re
import sys

import simlib as S

d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(S.HERE, "results", "ps_trace")
jobs = {}
with open(os.path.join(d, "jobs.txt")) as f:
    for line in f:
        name, *args = line.split()
        jobs[name] = dict(a[2:].split("=", 1) for a in args)
cache = S._load()

rows = []
for name, args in sorted(jobs.items()):
    path = os.path.join(d, name + ".txt")
    if not os.path.exists(path):
        continue
    text = open(path).read()
    rc = int(re.search(r"^rc (-?\d+)$", text, re.M).group(1))
    err = open(os.path.join(d, name + ".err")).read() if os.path.exists(os.path.join(d, name + ".err")) else ""
    fatal = re.search(r'msg="([^"]+)", \+([\d.]+)s (\d+)', err)
    # AP-side power-save state of each station link: last reported value and since when
    ps = {}
    for t, ap, link, sta, v in re.findall(r"^P ([\d.]+) apPs (\S+) (L\d) sta=(\S+) ps=(\d)", text, re.M):
        ps[(ap, link, sta)] = (int(v), float(t))
    stuck = {f"{ap} {link} {sta}": t for (ap, link, sta), (v, t) in ps.items() if v == 1}
    grp = {}
    for ap, link in re.findall(r"^P [\d.]+ grp (\S+) (L\d) ", text, re.M):
        grp[f"{ap} {link}"] = grp.get(f"{ap} {link}", 0) + 1
    # N5 <-> serving AP per-link viability (edge-stall trace "L" lines)
    lt = {}
    for key, field, rest in re.findall(r"^L (\S+) (\S+) (.*)$", text, re.M):
        lt.setdefault(key, {})[field] = rest

    def n_of(key, field):
        m = re.search(r"n=(\d+)", lt.get(key, {}).get(field, ""))
        return int(m.group(1)) if m else 0

    def dbm_of(key, field):
        m = re.search(r"meanDbm=(-?[\d.]+)", lt.get(key, {}).get(field, ""))
        return float(m.group(1)) if m else None

    n5links = {}
    for l in ("0", "1"):
        if f"up_{l}" in lt or f"dn_{l}" in lt:
            n5links["L" + l] = {
                "apDecodedN5Data": n_of(f"up_{l}", "decoded_data"),
                "apDecodedN5Any": sum(n_of(f"up_{l}", k) for k in lt.get(f"up_{l}", {}) if k.startswith("decoded_") and not k.endswith("_any")),
                "n5DecodedApAny": sum(n_of(f"dn_{l}", k) for k in lt.get(f"dn_{l}", {})
                                  if k.startswith("decoded_") and not k.endswith("_any")),
                "n5RxDbm": dbm_of(f"dn_{l}", "arrival_beacon") or dbm_of(f"dn_{l}", "arrival_data"),
                "apTxDataMpdusToN5": int(lt.get(f"dn_{l}", {}).get("txDataMpdus", "0") or 0),
            }
    out = S.parse(text) if rc == 0 else {}
    key = S._key(args, S.CODE_VERSION)
    ref = cache.get(key)
    match = None
    if ref is not None and out:
        match = all(out.get(k) == v for k, v in ref.items())
    rows.append({
        "run": name, "rc": rc, "fatal": fatal.groups() if fatal else None,
        "stuckPs": stuck, "groupFrames": grp, "n5Links": n5links,
        "tput_N5": out.get("tput_N5"), "sumLog": out.get("sumLog"), "sumTput": out.get("sumTput"),
        "matchesSweep": match, "inSweep": ref is not None,
    })

FLOOR_DBM = -82.0  # ns-3 ThresholdPreambleDetectionModel MinimumRssi
MARGIN_DB = 3.0    # received power within this of the floor counts as borderline


def classify(stuck_key, n5links):
    """Class of one link held in power-save at the AP:
    unusable   nothing decoded on the link in either direction and rx below the floor
               by more than MARGIN_DB (PS withholds nothing the link could carry);
    usable     the station decodes AP frames on that link (PS withholds downlink
               traffic the link could deliver);
    borderline anything else, or rx within MARGIN_DB of the floor;
    no-data    not an N5 link (the per-link viability trace covers N5 only)."""
    ap, link, sta = stuck_key.split()
    if not sta.startswith("N5/"):
        return "no-data"
    v = n5links.get(link)
    if not v:
        return "no-data"
    if v["n5DecodedApAny"] > 0:
        return "usable"
    rx = v["n5RxDbm"]
    if v["apDecodedN5Any"] == 0 and rx is not None and rx < FLOOR_DBM - MARGIN_DB:
        return "unusable"
    return "borderline"


for r in rows:
    r["stuckClass"] = {k: classify(k, r["n5Links"]) for k in r["stuckPs"]}

with open(os.path.join(d, "summary.json"), "w") as f:
    json.dump(rows, f, indent=1)
for r in rows:
    stuck = "; ".join(f"{k} since {v:.3f}s" for k, v in r["stuckPs"].items()) or "-"
    via = []
    for k in r["stuckPs"]:
        ap, link, sta = k.split()
        if sta.startswith("N5/"):
            v = r["n5Links"].get(link, {})
            via.append(f"{link} [{r['stuckClass'][k]}]: apDecN5={v.get('apDecodedN5Any')} n5DecAp={v.get('n5DecodedApAny')} "
                       f"rx={v.get('n5RxDbm')}")
    print(f"{r['run']:<36} rc={r['rc']:<4} match={str(r['matchesSweep']):<5} N5={r['tput_N5']} "
          f"stuck=[{stuck}] {' | '.join(via)}")
cls = [c for r in rows for c in r["stuckClass"].values()]
print("stuck PS links by class: " + ", ".join(f"{c} {cls.count(c)}"
                                              for c in ("unusable", "borderline", "usable", "no-data")))
print(f"{len(rows)} runs; with stuck PS: {sum(1 for r in rows if r['stuckPs'])}; "
      f"crashed: {sum(1 for r in rows if r['rc'] != 0)}; "
      f"sweep mismatch: {sum(1 for r in rows if r['matchesSweep'] is False)}")
