"""Association policies and offline evaluation for the DAMA-MLO revision.

Context (locally observable before association, from beacons):
    RSSI to MAP 1 and MAP 4 (dBm), and the channel utilization each AP
    advertises per link (BSS Load), measured in the pre-association run
    (scenario 0, same seed, no N5).
Actions: 0 = associate with MAP 1, 1 = associate with MAP 4.
Reward: network proportional-fairness utility, sum_k ln(Th_k [Mbps]),
    over every station in the run (centralized offline training,
    decentralized execution).

Evaluation is leave-one-position-out: learners never see the test position.
"""

import math
import os

import numpy as np

MAP_POS = {0: (0.0, 300.0), 1: (0.0, 150.0)}  # action -> MAP 1 / MAP 4 coordinates


def rssi_dbm(x, y, ap, tx_dbm=20.0, exponent=2.5, freq_hz=5.2e9):
    """Beacon RSSI from the same log-distance model the simulator uses."""
    ax, ay = MAP_POS[ap]
    d = max(math.hypot(x - ax, y - ay), 1.0)
    ref = 20.0 * math.log10(4.0 * math.pi * freq_hz / 299792458.0)
    return tx_dbm - ref - 10.0 * exponent * math.log10(d)


NOISE_DBM = -101.0 + 7.0  # thermal noise in 20 MHz plus a 7 dB noise figure (ns-3 default)


def features(ctx):
    """Feature vector of a context dict (normalized for the learners)."""
    r1, r4 = ctx["rssi"]
    u = ctx["util"]  # [u1_L0, u1_L1, u4_L0, u4_L1]
    return np.array([(r1 + 70) / 20.0, (r4 + 70) / 20.0, *u, 1.0])


# A beacon below the preamble-detection level is never decoded, so that MAP is not a
# candidate (manuscript Sec. 4.1). The floor applies to every link the station sets up:
# under MLO the 6 GHz link loses ~1.2 dB more than the 5 GHz link, and an MLD whose 6 GHz
# link is at the floor stalls on both links (N5 gets ~0 Mbit/s at (70,165), (100,195),
# (70,285), (100,255) although SLO works there). None disables this.
CAND_FLOOR_DBM = -82.0

# In-band receive power is slightly below the path-loss estimate: ns-3.48 normalizes the
# transmit PSD, spectral-mask skirts included, to TxPower (WifiSpectrumValueHelper::
# NormalizeSpectrumMask), and the receiver integrates only the in-band subbands. The traced
# beacon power is 0.029 dB below rssi_dbm() at every traced position on both bands (data PPDUs:
# 0.024 dB; results/edge_trace). The candidate check applies this beacon offset. Setting the
# environment variable DAMA_CAND_RX_OFFSET_DB=0 gives the nominal check used before 2026-10-05
# (sensitivity case; it admits MAP 1 at (100, 195) m under MLO, where the 6 GHz link is dead).
CAND_RX_OFFSET_DB = float(os.environ.get("DAMA_CAND_RX_OFFSET_DB", "-0.029"))

# Centre frequencies of the access channels in dama-mlo-v2.cc: MAP 1 ch 36 / ch 1,
# MAP 4 ch 48 / ch 13 (5 GHz: 5000 + 5c MHz, 6 GHz: 5950 + 5c MHz).
LINK_FREQ_HZ = {0: (5.180e9, 5.955e9), 1: (5.240e9, 6.015e9)}


def weakest_link_rssi(ctx, ap):
    """Beacon RSSI of the weakest link the station would set up with this MAP."""
    x, y = ctx["pos"]
    return min(rssi_dbm(x, y, ap, freq_hz=f) for f in LINK_FREQ_HZ[ap][:ctx["nlinks"]]) \
        + CAND_RX_OFFSET_DB


def forced_action(ctx):
    """The only candidate above the floor, or None when both (or neither) are heard."""
    if CAND_FLOOR_DBM is None:
        return None
    ok = [weakest_link_rssi(ctx, ap) >= CAND_FLOOR_DBM for ap in (0, 1)]
    return ok.index(True) if sum(ok) == 1 else None


def feasible_actions(ctx):
    """Candidate set J of Sec. 4.1: the forced MAP, or both when both (or neither) pass."""
    a = forced_action(ctx)
    return [0, 1] if a is None else [a]


def with_floor(pol):
    """Restrict a policy to the candidates heard above CAND_FLOOR_DBM."""

    def wrapped(ctx):
        a = forced_action(ctx)
        return pol(ctx) if a is None else a

    return wrapped


# --------------------------------------------------------------- heuristics
def pol_rssi(ctx):
    r1, r4 = ctx["rssi"]
    return 0 if r1 >= r4 else 1


def pol_load(ctx):
    """Client-count load-aware rule: P_rx / (N + 1). Both MAPs host 2 stations."""
    r1, r4 = ctx["rssi"]
    n1, n4 = ctx.get("nclients", (2, 2))
    m1 = 10 ** (r1 / 10) / (n1 + 1)
    m4 = 10 ** (r4 / 10) / (n4 + 1)
    return 0 if m1 >= m4 else 1


def residual_airtime(ctx, ap):
    u = ctx["util"]
    links = ctx["nlinks"]
    vals = u[0:2] if ap == 0 else u[2:4]
    return sum(1.0 - vals[l] for l in range(links))


def pol_airtime(ctx):
    """Airtime-aware heuristic: residual airtime x Shannon rate proxy."""
    scores = []
    for ap in (0, 1):
        snr_db = ctx["rssi"][ap] - NOISE_DBM
        rate = math.log2(1 + 10 ** (max(snr_db, -10) / 10))
        scores.append(residual_airtime(ctx, ap) * rate)
    return 0 if scores[0] >= scores[1] else 1


def make_threshold(delta):
    """Airtime threshold rule: follow RSSI unless the stronger AP is busier by > delta."""

    def pol(ctx):
        best = pol_rssi(ctx)
        other = 1 - best
        n = ctx["nlinks"]
        busy_best = n - residual_airtime(ctx, best)
        busy_other = n - residual_airtime(ctx, other)
        return other if (busy_best - busy_other) / n > delta else best

    return pol


# ------------------------------------------------------------------ learners
class LinUCB:
    """Disjoint LinUCB (Li et al., WWW 2010)."""

    def __init__(self, dim, alpha=1.0, lam=1.0):
        self.A = [lam * np.eye(dim) for _ in range(2)]
        self.b = [np.zeros(dim) for _ in range(2)]
        self.alpha = alpha

    def act(self, x, explore=True):
        s = []
        for a in range(2):
            Ai = np.linalg.inv(self.A[a])
            th = Ai @ self.b[a]
            s.append(th @ x + (self.alpha * math.sqrt(x @ Ai @ x) if explore else 0.0))
        return int(np.argmax(s))

    def update(self, x, a, r):
        self.A[a] += np.outer(x, x)
        self.b[a] += r * x


class TabularUCB1:
    """UCB1 per discretized context (N4-load bin x stronger-AP x RSSI-gap bin)."""

    def __init__(self, c=2.0):
        self.n = {}
        self.s = {}
        self.t = 0
        self.c = c

    @staticmethod
    def cell(ctx):
        r1, r4 = ctx["rssi"]
        gap = r1 - r4
        gbin = int(np.digitize(gap, [-6, -2, 2, 6]))
        u4 = ctx["util"][2]
        ubin = int(np.digitize(u4, [0.3, 0.6]))
        return (gbin, ubin)

    def act(self, ctx, explore=True):
        k = self.cell(ctx)
        n = self.n.setdefault(k, [0, 0])
        s = self.s.setdefault(k, [0.0, 0.0])
        if explore:
            for a in range(2):
                if n[a] == 0:
                    return a
            tot = sum(n)
            vals = [s[a] / n[a] + math.sqrt(self.c * math.log(tot) / n[a]) for a in range(2)]
        else:
            vals = [s[a] / n[a] if n[a] else -1e9 for a in range(2)]
        return int(np.argmax(vals))

    def update(self, ctx, a, r):
        k = self.cell(ctx)
        self.n.setdefault(k, [0, 0])[a] += 1  # a forced action may reach a cell act() never saw
        self.s.setdefault(k, [0.0, 0.0])[a] += r


class NeuralBandit:
    """Neural contextual bandit: 2x64 ReLU MLP regressing the reward of each
    action, trained with epsilon-greedy replay (the revised form of the
    original DQN; gamma = 0 makes the target network unnecessary)."""

    def __init__(self, dim, hidden=64, lr=1e-3, seed=0):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, math.sqrt(2 / dim), (dim, hidden))
        self.b1 = np.zeros(hidden)
        self.W2 = rng.normal(0, math.sqrt(2 / hidden), (hidden, hidden))
        self.b2 = np.zeros(hidden)
        self.W3 = rng.normal(0, math.sqrt(2 / hidden), (hidden, 2))
        self.b3 = np.zeros(2)
        self.lr = lr
        self.rng = rng
        self.buf = []
        # Adam state
        self.params = ["W1", "b1", "W2", "b2", "W3", "b3"]
        self.m = {p: np.zeros_like(getattr(self, p)) for p in self.params}
        self.v = {p: np.zeros_like(getattr(self, p)) for p in self.params}
        self.t = 0
        self.rmean = 0.0
        self.rstd = 1.0

    def q(self, X):
        z1 = X @ self.W1 + self.b1
        a1 = np.maximum(z1, 0)
        z2 = a1 @ self.W2 + self.b2
        a2 = np.maximum(z2, 0)
        return a2 @ self.W3 + self.b3, (X, z1, a1, z2, a2)

    def act(self, x, eps=0.0):
        if self.rng.random() < eps:
            return int(self.rng.integers(2))
        out, _ = self.q(x[None, :])
        return int(np.argmax(out[0]))

    def update(self, x, a, r, batch=32):
        self.buf.append((x, a, r))
        rs = np.array([b[2] for b in self.buf])
        self.rmean, self.rstd = rs.mean(), rs.std() + 1e-6
        idx = self.rng.integers(len(self.buf), size=min(batch, len(self.buf)))
        X = np.array([self.buf[i][0] for i in idx])
        A = np.array([self.buf[i][1] for i in idx])
        R = (np.array([self.buf[i][2] for i in idx]) - self.rmean) / self.rstd
        out, (X, z1, a1, z2, a2) = self.q(X)
        d = np.zeros_like(out)
        d[np.arange(len(idx)), A] = (out[np.arange(len(idx)), A] - R) / len(idx)
        g = {}
        g["W3"] = a2.T @ d
        g["b3"] = d.sum(0)
        da2 = d @ self.W3.T * (z2 > 0)
        g["W2"] = a1.T @ da2
        g["b2"] = da2.sum(0)
        da1 = da2 @ self.W2.T * (z1 > 0)
        g["W1"] = X.T @ da1
        g["b1"] = da1.sum(0)
        self.t += 1
        for p in self.params:
            self.m[p] = 0.9 * self.m[p] + 0.1 * g[p]
            self.v[p] = 0.999 * self.v[p] + 0.001 * g[p] ** 2
            mh = self.m[p] / (1 - 0.9**self.t)
            vh = self.v[p] / (1 - 0.999**self.t)
            setattr(self, p, getattr(self, p) - self.lr * mh / (np.sqrt(vh) + 1e-8))


# ---------------------------------------------------------------- evaluation
def train_learner(kind, train, rounds, seed, constrained=True):
    """Replay training on training contexts.

    train: list of (ctx, rewards) where rewards[a] is a list of per-seed rewards.
    constrained: True (main result) = training actions are restricted to the candidate
        set, as at execution; False (sensitivity analysis only) = the learner may also
        try the MAP that fails the per-link floor and observe its offline outcome.
    Execution is restricted to the candidate set in both cases (with_floor).
    """
    rng = np.random.default_rng(seed)
    dim = len(features(train[0][0]))
    if kind == "linucb":
        L = LinUCB(dim, alpha=0.5)
    elif kind == "ucb1":
        L = TabularUCB1()
    elif kind == "neural":
        L = NeuralBandit(dim, seed=seed)
    else:
        raise ValueError(kind)
    for t in range(rounds):
        ctx, rew = train[rng.integers(len(train))]
        x = features(ctx)
        # training uses the same candidate set as execution (Sec. 4.1): where only one
        # MAP passes the per-link floor, that action is taken and its reward observed
        forced = forced_action(ctx) if constrained else None
        if forced is not None:
            a = forced
        elif kind == "linucb":
            a = L.act(x)
        elif kind == "ucb1":
            a = L.act(ctx)
        else:
            eps = max(0.05, 1.0 - t / (0.5 * rounds))
            a = L.act(x, eps)
        r = rew[a][rng.integers(len(rew[a]))]
        if kind == "ucb1":
            L.update(ctx, a, r)
        else:
            L.update(x, a, r)
    if kind == "linucb":
        return with_floor(lambda c: L.act(features(c), explore=False))
    if kind == "ucb1":
        return with_floor(lambda c: L.act(c, explore=False))
    return with_floor(lambda c: L.act(features(c), 0.0))
