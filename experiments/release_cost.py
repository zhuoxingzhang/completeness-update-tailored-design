"""What a maintenance window costs on each of the three designs, offline and at register scale.

An update is `UPDATE R SET a = v WHERE X = x`, as in the amplification proposition of the paper,
so the row-level diff of the two editions is first coalesced back into the updates that produced
it: for each changed attribute the minimal determinants of that attribute are tried, and the one
yielding the fewest statements is kept, where a determinant group whose changed tuples agree on
the new value and cover the whole group counts as one statement and every other event counts as
one of its own.  Each design then pays, per subschema holding the attribute, one statement per
update and the distinct stored rows that update rewrites: the determinant group where the
attribute sits away from a key, the tuple's own row otherwise.

The calibration is the one fitted on this server for the whole window, 0.13 ms per statement
inside a transaction and 6.8 microseconds per further row of a group rewrite.  The other
release_*.py scripts import the relation, the coalescing and the price from here.

Usage: python release_cost.py [<tag> ...]          default owid
Environment: REFONLY=1 keeps only the attributes whose changes all coalesce, which is the
             reference-correction part of a release; SLICE=refresh|completion|all (default
             refresh); SIGMA=<path> prices the window on a given constraint set instead of the
             shipped one; HEAT_FLOOR (default 1) is the least heat of a rule of the reduct, and 0
             reproduces the runs recorded before the heats were made positive.
Writes results/rq7_real_cost_<slice>.json
"""
import collections
import json
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import synthesis as B

B.HEAT = "all"
import real_workload as RW

ORDER = ["3NF", "SO", "HA"]
MODE_OF = {"3NF": "3nf", "SO": "so", "HA": "ha"}
KINDS = {"refresh": {"refresh"}, "completion": {"completion"},
         "all": {"refresh", "completion", "retraction"}}
SLICE = os.environ.get("SLICE", "refresh")
REFONLY = os.environ.get("REFONLY", "0") == "1"
# A relation built from several consecutive editions carries the events of each of them, and only
# the one that starts at the edition the relation holds may be priced on it: a design stores that
# state and the rules it stores have to hold there.
WINDOW = os.environ.get("WINDOW", "")
ALPHA = 0.13e-3
BETA = 6.8e-6
# Heats are positive: a rule the window does not refresh keeps the default heat 1, so a design
# cannot declare a rule away.  HEAT_FLOOR=0 reproduces the runs recorded before that convention,
# which gave such a rule heat 0.
HEAT_FLOOR = int(os.environ.get("HEAT_FLOOR", "1"))


def floor(theta):
    """The heat vector under the floor of the paper."""
    return {fd: max(HEAT_FLOOR, v) for fd, v in theta.items()}


def relpath(tag):
    """The relation release_build.py wrote."""
    return os.path.join(CFG.scratch_dir(), f"{tag}_relation.pkl")


def fdspath(tag):
    if os.environ.get("SIGMA"):
        return os.environ["SIGMA"]
    cand = os.path.join(CFG.REPO, "data", "release", f"{tag}_fds.json")
    if os.path.exists(cand):
        return cand
    raise SystemExit(f"no constraint set for {tag}: expected {cand}")


def ids(code, cols):
    """A dense group id per row for the projection on `cols`."""
    if not cols:
        return np.zeros(code.shape[1], dtype=np.int64)
    key = code[list(cols)]
    _, gid = np.unique(key, axis=1, return_inverse=True)
    return gid.astype(np.int64).ravel()


def distinct_per_group(gid, sid):
    """How many distinct `sid` values each `gid` group holds, as an array indexed by gid."""
    pair = np.unique(np.stack([gid, sid]), axis=1)
    return np.bincount(pair[0], minlength=int(gid.max()) + 1)


class Rel:
    def __init__(self, tag):
        path = relpath(tag)
        if not os.path.exists(path):
            raise SystemExit(f"{path} is missing: run release_build.py first")
        d = pickle.load(open(path, "rb"))
        attrs, data, events = d["attrs"], d["data"], d["events"]
        E = RW.choose_E(data, len(attrs))
        self.E = frozenset(E)
        pos, scope = {}, []
        for i, r in enumerate(data):
            if all(r[a] is not None for a in E):
                pos[i] = len(scope)
                scope.append(r)
        self.n, self.attrs, self.tag = len(scope), attrs, tag
        m = len(attrs)
        self.code = np.empty((m, self.n), dtype=np.int64)
        self.dec = []
        for c in range(m):
            vals = {}
            col = self.code[c]
            for i, r in enumerate(scope):
                v = r[c]
                col[i] = -1 if v is None else vals.setdefault(v, len(vals))
            self.dec.append(vals)
        aidx = {a: i for i, a in enumerate(attrs)}
        self.ev = [(aidx[e["attr"]], pos[e["i"]], e["new"])
                   for e in events if e["kind"] in KINDS[SLICE] and e["i"] in pos
                   and (not WINDOW or e.get("window") == WINDOW)]
        _, sigma, _ = B.load(fdspath(tag))
        self.reduct = [fd for fd in sigma if (fd[0] | fd[1]) <= self.E]
        self.keys = B.minimal_keys(self.E, self.reduct)
        self._gid, self._dist = {}, {}

    def gid(self, cols):
        cols = tuple(sorted(cols))
        if cols not in self._gid:
            self._gid[cols] = ids(self.code, cols)
        return self._gid[cols]

    def rows_per_group(self, S, X):
        """Distinct stored rows of subschema S inside each X-group, indexed by X-group id."""
        key = (tuple(sorted(S)), tuple(sorted(X)))
        if key not in self._dist:
            self._dist[key] = distinct_per_group(self.gid(X), self.gid(S))
        return self._dist[key]


def coalesce(R):
    """Per attribute: the determinant it coalesces on, the covered groups, and the leftovers."""
    dets = collections.defaultdict(list)
    for X, Y in R.reduct:
        a = next(iter(Y))
        if a not in X:
            dets[a].append(tuple(sorted(X)))
    by_attr = collections.defaultdict(list)
    for a, j, new in R.ev:
        by_attr[a].append((j, new))

    plan = {}
    for a, evs in by_attr.items():
        rows = np.array([j for j, _ in evs], dtype=np.int64)
        seen = dict(R.dec[a])
        codes = []
        for _, v in evs:
            if v not in seen:                # a value the stored state never held
                seen[v] = len(seen)
            codes.append(seen[v])
        newc = np.array(codes, dtype=np.int64)
        best = None
        for X in dets.get(a, []):
            gid = R.gid(X)
            size = np.bincount(gid, minlength=int(gid.max()) + 1)
            g = gid[rows]
            hit = np.bincount(np.unique(np.stack([g, rows]), axis=1)[0],
                              minlength=len(size))
            agree = distinct_per_group(g, newc)
            agree = np.pad(agree, (0, len(size) - len(agree)))
            whole = (hit > 0) & (hit == size) & (agree == 1)
            left = int((~whole[g]).sum())
            upd = int(whole.sum()) + left
            cand = (upd, len(X), X, whole, left)
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best is None:
            best = (len(evs), 0, (), None, len(evs))
        plan[a] = {"updates": best[0], "X": best[2], "whole": best[3],
                   "left_rows": rows[~best[3][R.gid(best[2])[rows]]] if best[3] is not None
                   else rows, "events": len(evs)}
    return plan


def run(tag):
    R = Rel(tag)
    print(f"\n=== {tag}: scope {R.n:,}, {len(R.attrs)} attrs, {len(R.reduct)} atomic FDs, "
          f"{len(R.keys)} minimal keys, {len(R.ev):,} {SLICE} events ===", flush=True)
    plan = coalesce(R)
    if REFONLY:
        keep = {a for a, p in plan.items() if len(p["left_rows"]) == 0 and p["X"]}
        print(f"  reference-only slice keeps {sorted(R.attrs[a] for a in keep)}", flush=True)
        plan = {a: p for a, p in plan.items() if a in keep}
    for a, p in sorted(plan.items(), key=lambda kv: -kv[1]["events"]):
        w = int(p["whole"].sum()) if p["whole"] is not None else 0
        print(f"  {R.attrs[a]:16s} {p['events']:10,} events -> {p['updates']:9,} updates "
              f"({p['events'] / max(p['updates'], 1):8.1f}x) via "
              f"{'{' + ','.join(R.attrs[c] for c in p['X']) + '}' if p['X'] else '-':38s}"
              f" {w:7,} whole groups, {len(p['left_rows']):8,} single", flush=True)

    nev = {}
    for a, j, _ in R.ev:
        nev.setdefault(a, np.zeros(R.n, dtype=np.int64))[j] += 1
    theta = floor({fd: (int(nev[next(iter(fd[1]))].sum()) if next(iter(fd[1])) in nev else 0)
                   for fd in R.reduct})
    prep = B.prepare(R.reduct)

    out = {}
    for k in ORDER:
        D = B.synthesize(R.E, R.reduct, R.keys, MODE_OF[k], hot=theta, prep=prep)
        out[k] = price(R, plan, D, theta)
        o = out[k]
        print(f"  {k:4s} |D|={o['subschemata']:4d} hmax={o['hmax']:10,} stmts {o['statements']:10,}  "
              f"rows {o['rows']:13,} (charged {o['charged_rows']:12,})  predicted {o['pred_s']:9.1f}s  "
              f"(statements {100 * o['stmt_share']:.0f}%)", flush=True)
    h = out["HA"]
    print(f"  ---> predicted time  3NF/HA {out['3NF']['pred_s'] / h['pred_s']:.3f}x  "
          f"SO/HA {out['SO']['pred_s'] / h['pred_s']:.3f}x   |   rows 3NF/HA "
          f"{out['3NF']['rows'] / h['rows']:.3f}x SO/HA {out['SO']['rows'] / h['rows']:.3f}x")
    if h["charged_rows"]:
        print(f"  ---> charged only    3NF/HA {out['3NF']['charged_rows'] / h['charged_rows']:.3f}x"
              f"  SO/HA {out['SO']['charged_rows'] / h['charged_rows']:.3f}x")
    return {"tag": tag, "slice": SLICE, "refonly": REFONLY, "scope": R.n,
            "events": len(R.ev), "reduct": len(R.reduct), "keys": len(R.keys),
            "designs": out}


def price(R, plan, D, theta):
    """What one design pays for the window: statements, rewritten rows, and of those the ones
    charged to a rule stored away from a key."""
    met = B.decomp_metrics(D, theta)
    stmts = rows = charged = 0
    p_stmts = p_rows = p_charged = 0
    for S, proj in D:
        nk = collections.defaultdict(list)
        for fd in B.nonkey_atomic(S, proj):
            nk[next(iter(fd[1]))].append(fd)
        for a in S & set(plan):
            p = plan[a]
            if a in nk:               # stored away from a key here: the group is rewritten
                g = max((R.rows_per_group(S, f[0])[R.gid(f[0])] for f in nk[a]),
                        key=lambda v: v.sum())
                ch = True
            else:
                g, ch = None, False
            if p["whole"] is not None and p["whole"].any():
                per = R.rows_per_group(S, p["X"])
                idx = np.flatnonzero(p["whole"])
                r = per[idx].astype(np.int64)
                if ch:                # the repair can reach past the update's own group
                    gg = R.gid(p["X"])
                    rep = np.zeros(len(per), dtype=np.int64)
                    rep[gg] = np.arange(R.n)
                    r = np.maximum(r, g[rep[idx]])
                stmts += len(idx)
                rows += int(r.sum())
                charged += int(r.sum()) if ch else 0
                if p["X"]:
                    p_stmts += len(idx)
                    p_rows += int(r.sum())
                    p_charged += int(r.sum()) if ch else 0
            lr = p["left_rows"]
            if len(lr):
                stmts += len(lr)
                v = int(g[lr].sum()) if ch else len(lr)
                rows += v
                charged += v if ch else 0
                if p["X"]:
                    p_stmts += len(lr)
                    p_rows += v
                    p_charged += v if ch else 0
    pred = ALPHA * stmts + BETA * rows
    return {"subschemata": len(D), "hmax": met["hmax"], "htot": met["htot"],
            "statements": stmts, "rows": rows, "charged_rows": charged,
            "priced_stmts": p_stmts, "priced_rows": p_rows, "priced_charged_rows": p_charged,
            "priced_pred_s": ALPHA * p_stmts + BETA * p_rows,
            "pred_s": pred, "stmt_share": ALPHA * stmts / pred if pred else 0}


if __name__ == "__main__":
    res = [run(t) for t in (sys.argv[1:] or ["owid"])]
    name = f"rq7_real_cost{'_refonly' if REFONLY else ''}_{SLICE}.json"
    json.dump(res, open(os.path.join(CFG.RESULTS, name), "w"), indent=1)
    print(f"\nwritten results/{name}")
