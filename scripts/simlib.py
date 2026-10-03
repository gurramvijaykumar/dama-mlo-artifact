"""Runner and cache for scratch/dama-mlo-v2.cc (DAMA-MLO major revision).

Every run is keyed by its full argument set and stored as one JSON line in
results/runs.jsonl, so sweeps can be interrupted and resumed, and every number
in the revised manuscript can be traced back to a raw ns-3 run.
"""

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

NS3_DIR = os.environ.get("NS3_DIR", "/home/vijay/ns-allinone-3.48/ns-3.48")
# Scenario code versions. A run's cache key includes its code version, so a run
# made with changed instrumentation or rate behavior never reuses an older result.
#   2.0: submitted-revision scenario (grid and named states; records written
#        before versioning have no codeVersion field and count as 2.0).
#   2.1: matched per-packet delay split (access / wireless backhaul / wired) and,
#        in downlink runs, the AP sends to each slow station at its fixed rate.
# 2.0 runs use a frozen copy of the 2.0 binary, so an interrupted 2.0 sweep can
# still be completed with identical code.
LEGACY_VERSION = "2.0"
CODE_VERSION = "2.1"
BINARIES = {
    "2.0": os.path.join(NS3_DIR, "build/scratch/ns3.48-dama-mlo-v2.0-frozen"),
    "2.1": os.path.join(NS3_DIR, "build/scratch/ns3.48-dama-mlo-v2-optimized"),
}
BINARY = BINARIES[CODE_VERSION]
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_FILE = os.path.join(HERE, "results", "runs.jsonl")
# Runs that exited non-zero. They are skipped on later sweeps unless
# DAMA_RETRY_FAILED=1 is set, so a deterministic crash is not rerun on every resume.
FAILED_FILE = os.path.join(HERE, "results", "failed_runs.jsonl")
RETRY_FAILED = os.environ.get("DAMA_RETRY_FAILED") == "1"

# Primary configuration of the revised paper. Every experiment starts from
# these values and overrides only the factor it studies.
BASE = {
    "linkMode": "mlo",
    "prop": "logdist",
    "accessExp": 2.5,
    "backhaulExp": 2.0,
    "txPower": 20.0,
    "backhaulWidth": 80,
    "backhaulBand": "5",
    "useTcp": "true",
    "downlink": "false",
    "simTime": 13.0,
    "warmup": 3.0,
    "fastRate": "ideal",
    "n4Rate": "EhtMcs0",
    "n4X": 120.0,
    "staDist": 20.0,
}

_lock = threading.Lock()
_cache = None


def _key(args, version=CODE_VERSION):
    d = {k: str(v) for k, v in sorted(args.items())}
    if version != LEGACY_VERSION:
        d["codeVersion"] = version  # legacy keys stay exactly as they were
    return json.dumps(d, sort_keys=True)


def record_version(rec):
    """Code version of a stored record (records without the field are 2.0)."""
    return rec.get("codeVersion", LEGACY_VERSION)


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        if os.path.exists(RUNS_FILE):
            # a crash mid-write leaves no trailing newline; add one so the
            # next record starts on its own line instead of joining the stub
            with open(RUNS_FILE, "rb+") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
            with open(RUNS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # line cut off by a crash mid-write; that run is redone
                        _cache[rec["key"]] = rec["out"]
    return _cache


def parse(stdout):
    out = {}
    for line in stdout.splitlines():
        if line.startswith("T "):
            # per-second aggregate throughput (--tputTrace): kept for steady-state checks
            _, t, v = line.split()
            out.setdefault("tputTrace", []).append([float(t), float(v)])
        elif line.startswith("R "):
            _, k, v = line.split(" ", 2)
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


class SimFailure(RuntimeError):
    """An ns-3 run that exited with a non-zero status (assert, NS_FATAL, signal)."""

    def __init__(self, key, args, version, cmd, returncode, stderr):
        super().__init__(f"ns-3 failed ({returncode}): {' '.join(cmd)}\n{stderr[-2000:]}")
        self.key, self.run_args, self.version = key, args, version
        self.cmd, self.returncode, self.stderr = cmd, returncode, stderr


def _load_failed():
    """Keys of runs recorded in results/failed_runs.jsonl."""
    keys = set()
    if os.path.exists(FAILED_FILE):
        with open(FAILED_FILE) as f:
            for line in f:
                try:
                    keys.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return keys


def _record_failure(e, label):
    """Append a failed run to results/failed_runs.jsonl (never to runs.jsonl)."""
    rec = {"key": e.key, "args": e.run_args, "codeVersion": e.version, "label": label,
           "cmd": " ".join(e.cmd), "returncode": e.returncode,
           "time": time.strftime("%Y-%m-%d %H:%M:%S"), "stderr": e.stderr[-20000:]}
    with _lock:
        with open(FAILED_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")


def run(args, force=False, version=CODE_VERSION):
    """Run one simulation with the given code version (or return the cached result)."""
    full = dict(BASE)
    full.update(args)
    key = _key(full, version)
    cache = _load()
    if not force and key in cache:
        return cache[key]
    cmd = [BINARIES[version]] + [f"--{k}={v}" for k, v in sorted(full.items())]
    p = subprocess.run(cmd, cwd=NS3_DIR, capture_output=True, text=True)
    if p.returncode != 0:
        raise SimFailure(key, full, version, cmd, p.returncode, p.stderr)
    out = parse(p.stdout)
    got = str(out.get("codeVersion", LEGACY_VERSION))
    if got != version:
        raise RuntimeError(f"binary {BINARIES[version]} reports code version {got}, expected {version}")
    with _lock:
        cache[key] = out
        rec = {"key": key, "args": full, "out": out}
        if version != LEGACY_VERSION:
            rec["codeVersion"] = version
        with open(RUNS_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    return out


def run_many(arg_list, workers=4, label="", version=CODE_VERSION, allow_fail=True):
    """Run a list of argument dicts in parallel; returns results in order.

    A run that exits non-zero is recorded in results/failed_runs.jsonl and its
    result is None. Runs already recorded there are skipped (result None) unless
    DAMA_RETRY_FAILED=1. The call aborts if more than max(2, 1%) of its runs fail,
    and on any failure when allow_fail is False.
    """
    results = [None] * len(arg_list)
    cache = _load()
    failed_keys = set() if RETRY_FAILED else _load_failed()
    todo = []
    known_failed = 0
    for i, a in enumerate(arg_list):
        full = dict(BASE)
        full.update(a)
        k = _key(full, version)
        if k in cache:
            results[i] = cache[k]
        elif k in failed_keys:
            known_failed += 1
        else:
            todo.append(i)
    print(f"[{label}] {len(arg_list)} runs (code {version}), {len(todo)} to simulate"
          + (f", {known_failed} skipped as known failures" if known_failed else ""), flush=True)
    if known_failed and not allow_fail:
        raise RuntimeError(f"[{label}] {known_failed} runs are known failures (results/failed_runs.jsonl)")
    max_fail = max(2, len(arg_list) // 100)
    done = 0
    failures = known_failed
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, arg_list[i], False, version): i for i in todo}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except SimFailure as e:
                _record_failure(e, label)
                failures += 1
                print(f"[{label}] FAILED (exit {e.returncode}), recorded in results/failed_runs.jsonl: "
                      f"{' '.join(e.cmd[1:])}", flush=True)
                if not allow_fail or failures > max_fail:
                    ex.shutdown(wait=True, cancel_futures=True)
                    raise RuntimeError(f"[{label}] {failures} failed runs (limit {max_fail}"
                                       f"{', no failures allowed' if not allow_fail else ''}); stopping") from e
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"[{label}] {done}/{len(todo)}", flush=True)
    return results
