r"""The classes of designs each criterion may return on a real window, priced offline.

Each criterion fixes a design only up to the order in which the closure is eliminated, and each
leaves that order free wherever its own objective cannot tell two designs apart.  So a criterion
does not return a design, it returns a class.  This prices a real window over the whole class of
each criterion: is there a design ours may return that is strictly cooler than every design theirs
may return, and strictly cheaper for the window as well?

The classes are defined by the criteria themselves, so no design is counted against a baseline
that the baseline would not accept:
  SO   every admissible design attaining the least (largest, total) number of non-key FDs per
       subschema, which is what structure-optimal synthesis minimises;
  HA   every admissible design attaining the least (maximal, total) heat, which is what the
       objective of the paper minimises;
  3NF  every admissible design, since 3NF synthesis has no objective and takes the order it is
       handed.
Admissible means E-3NF (the classical guarantee does not survive embedded FDs) on top of
E-losslessness and E-dependency-preservation, which hold by construction.  release_classes.py
imports the pool of orders from here and searches the ties of the classes.

Usage: python release_pool.py [<tag> ...]          default owid
Environment: WINDOW, SLICE, REFONLY, SIGMA as in release_cost.py; SHUFFLES (default 40)
Writes results/rq7_real_pool.json
"""
import collections
import json
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import synthesis as B
import release_cost as W

B.HEAT = "all"
MODES = [("3NF", "3nf"), ("SO", "so"), ("HA", "ha")]
SHUFFLES = int(os.environ.get("SHUFFLES", "40"))


def order_pool(sigma, heat, cost, fcnt, hot_rhs):
    """Every elimination order the search covers, none of which any criterion forbids."""
    lex = sorted(sigma, key=lambda f: (sorted(f[0]), sorted(f[1])))
    out = {"cold": sorted(sigma, key=lambda f: heat[f]),
           "warm": sorted(sigma, key=lambda f: -heat[f]),
           "lex": lex, "lex_rev": lex[::-1],
           "level": sorted(lex, key=lambda f: len(f[0])),
           "level_rev": sorted(lex, key=lambda f: -len(f[0])),
           "wcost": sorted(sigma, key=lambda f: -cost[f]),
           "wcost_rev": sorted(sigma, key=lambda f: cost[f]),
           "fcnt": sorted(sigma, key=lambda f: -fcnt[f]),
           "fcnt_rev": sorted(sigma, key=lambda f: fcnt[f])}
    # heat first, the window cost of the schema left behind as the tie-break, and the reverse
    for hs in (1, -1):
        for cs in (1, -1):
            out[f"h{'+' if hs > 0 else '-'}c{'+' if cs > 0 else '-'}"] = sorted(
                sigma, key=lambda f: (hs * heat[f], cs * cost[f]))
    # designate one hot rule as the survivor, and the reverse: drop everything about one attribute
    warm = out["warm"]
    for i, f in enumerate(g for g in warm[:6] if heat[g] > 0):
        out[f"survivor{i}"] = [g for g in warm if g is not f] + [f]
    for i, a in enumerate(hot_rhs[:8]):
        about = [f for f in sigma if a in f[0] | f[1]]
        rest = [f for f in sigma if f not in set(about)]
        out[f"first{i}"] = about + rest
        out[f"last{i}"] = rest + about
        # keep every schema that would hold `a`: hand it the rules about `a` last, and inside
        # each block order by how much the window pays for the schema the rule leaves behind
        for j, (ks, kr) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
            out[f"keep{i}_{j}"] = (sorted(rest, key=lambda f: kr * cost[f])
                                   + sorted(about, key=lambda f: ks * cost[f]))
    for i, a in enumerate(hot_rhs[:4]):
        for k, b in enumerate(hot_rhs[:4]):
            if a == b:
                continue
            ab = [f for f in sigma if (a in f[0] | f[1]) or (b in f[0] | f[1])]
            rest = [f for f in sigma if f not in set(ab)]
            out[f"keep{i}{k}"] = rest + ab
    for s in range(SHUFFLES):
        o = list(sigma)
        random.Random(s).shuffle(o)
        out[f"rand{s}"] = o
    return out


def run(tag):
    R = W.Rel(tag)
    plan = W.coalesce(R)
    if W.REFONLY:
        keep = {a for a, p in plan.items() if len(p["left_rows"]) == 0 and p["X"]}
        plan = {a: p for a, p in plan.items() if a in keep}
    nev = {}
    for a, j, _ in R.ev:
        nev.setdefault(a, np.zeros(R.n, dtype=np.int64))[j] += 1
    ev = {a: int(v.sum()) for a, v in nev.items()}
    theta = W.floor({fd: ev.get(next(iter(fd[1])), 0) for fd in R.reduct})
    prep = B.prepare(R.reduct)
    proj, mkeys = prep["proj"], prep["mkeys"]
    crit, noncrit = set(prep["crit"]), set(prep["noncrit"])
    heat = {fd: sum(B.fd_hot(g, theta) for g in
                    B.nonkey_atomic(fd[0] | fd[1], proj[fd[0] | fd[1]])) for fd in R.reduct}
    fcnt = {fd: len(B.nonkey_atomic(fd[0] | fd[1], proj[fd[0] | fd[1]])) for fd in R.reduct}
    cost = {}
    for fd in R.reduct:
        XA = fd[0] | fd[1]
        stm = sum(ev.get(a, 0) for a in XA)
        grp = sum(ev.get(next(iter(f[1])), 0) for f in B.nonkey_atomic(XA, proj[XA]))
        cost[fd] = W.ALPHA * stm + W.BETA * grp * R.n / max(len(set(R.gid(tuple(fd[0])).tolist())), 1)
    hot_rhs = [a for a, _ in collections.Counter(
        {a: n for a, n in ev.items()}).most_common()]
    print(f"\n=== {tag}: scope {R.n:,}, {len(R.attrs)} attrs, reduct {len(R.reduct)}, "
          f"{len(R.keys)} minimal keys, {len(R.ev):,} {W.SLICE} events"
          f"{' (reference-only)' if W.REFONLY else ''} ===", flush=True)
    print("  window's busiest attributes: "
          + ", ".join(f"{R.attrs[a]} {ev[a]:,}" for a in hot_rhs[:5]), flush=True)

    primes = {}

    def e3nf(D):
        for XA, pr in D:
            if XA not in primes:
                ks = mkeys.get(XA) or B.minimal_keys(XA, pr)
                primes[XA] = set().union(*ks) if ks else set()
            if any(next(iter(f[1])) not in primes[XA] for f in B.nonkey_atomic(XA, pr)):
                return False
        return True

    pool = order_pool(R.reduct, heat, cost, fcnt, hot_rhs)
    out, picks = {}, {}
    for lab, mode in MODES:
        seen, recs = set(), []
        for name, order in pool.items():
            p = dict(prep)
            p["crit"] = [f for f in order if f in crit]
            p["noncrit"] = [f for f in order if f in noncrit]
            D = B.synthesize(R.E, order, R.keys, mode, hot=theta, prep=p)
            if not e3nf(D):
                continue
            key = tuple(sorted(tuple(sorted(XA)) for XA, _ in D))
            if key in seen:
                continue
            seen.add(key)
            c = W.price(R, plan, D, theta)
            f = [len(B.nonkey_atomic(XA, pr)) for XA, pr in D]
            c["so_obj"] = [max(f, default=0), sum(f)]
            c["order"] = name
            c["fds"] = [[sorted(f[0]), sorted(f[1])] for f in order]
            c["copies"] = {R.attrs[a]: sum(1 for XA, _ in D if a in XA) for a in hot_rhs[:5]}
            c["nonkey"] = {R.attrs[a]: sum(1 for XA, pr in D if any(
                next(iter(g[1])) == a for g in B.nonkey_atomic(XA, pr))) for a in hot_rhs[:5]}
            recs.append(c)
        if not recs:
            print(f"  {lab:4s} no admissible design", flush=True)
            continue
        if lab == "SO":
            best = min(tuple(c["so_obj"]) for c in recs)
            cls = [c for c in recs if tuple(c["so_obj"]) == best]
        elif lab == "HA":
            best = min((c["hmax"], c["htot"]) for c in recs)
            cls = [c for c in recs if (c["hmax"], c["htot"]) == best]
        else:
            cls = recs
        out[lab] = cls
        picks[lab] = {"cheapest": min(cls, key=lambda c: c["pred_s"]),
                      "dearest": max(cls, key=lambda c: c["pred_s"]),
                      "hot_dear": max([c for c in cls if c["htot"] == max(
                          d["htot"] for d in cls)], key=lambda c: c["pred_s"])}
        hs = sorted({c["htot"] for c in cls})
        ts = sorted(c["pred_s"] for c in cls)
        print(f"  {lab:4s} {len(cls)}/{len(recs)} designs in its class   "
              f"htot {hs[0]:,}..{hs[-1]:,}   time {ts[0]:.1f}..{ts[-1]:.1f}s", flush=True)
        for c in sorted(cls, key=lambda c: c["pred_s"])[:3] + sorted(
                cls, key=lambda c: -c["htot"])[:2]:
            print(f"       {c['order']:11s} |D| {c['subschemata']:3d} hmax {c['hmax']:>8,} "
                  f"htot {c['htot']:>9,} stmts {c['statements']:>10,} rows {c['rows']:>11,} "
                  f"charged {c['charged_rows']:>9,} {c['pred_s']:8.1f}s  "
                  f"cp {c['copies']}", flush=True)

    if "HA" in out and "SO" in out:
        ours = min(out["HA"], key=lambda c: c["pred_s"])
        # the bottom line: no design SO may return is both as cool and as cheap as ours
        cooler = [c for c in out["SO"] if c["htot"] <= ours["htot"]]
        cheaper = [c for c in out["SO"] if c["pred_s"] <= ours["pred_s"]]
        both = [c for c in out["SO"] if c["htot"] <= ours["htot"] and c["pred_s"] <= ours["pred_s"]]
        worst = max(out["SO"], key=lambda c: c["pred_s"])
        hottest = max(out["SO"], key=lambda c: c["htot"])
        print(f"\n  ours at its cheapest: htot {ours['htot']:,}, {ours['pred_s']:.1f}s", flush=True)
        print(f"  SO designs as cool: {len(cooler)}/{len(out['SO'])}   "
              f"as cheap: {len(cheaper)}/{len(out['SO'])}   both: {len(both)}", flush=True)
        print(f"  SO dearest {worst['pred_s']:.1f}s (htot {worst['htot']:,}) = "
              f"{worst['pred_s'] / ours['pred_s']:.3f}x   "
              f"SO hottest htot {hottest['htot']:,} = "
              f"{hottest['htot'] / max(ours['htot'], 1):.2f}x at {hottest['pred_s']:.1f}s "
              f"= {hottest['pred_s'] / ours['pred_s']:.3f}x", flush=True)
        print(f"  BOTTOM LINE: {'MET' if not both else 'not met'} -- "
              + ("no SO design is both as cool and as cheap" if not both else
                 f"{len(both)} SO designs match ours on both"), flush=True)
    if os.environ.get("DUMP"):
        path = os.path.join(CFG.RESULTS, "rq7_real_pool_orders.json")
        held = json.load(open(path)) if os.path.exists(path) else {}
        held[tag] = {lab: {v: {"order": c["order"], "htot": c["htot"], "hmax": c["hmax"],
                               "pred_s": c["pred_s"], "statements": c["statements"],
                               "rows": c["rows"], "charged_rows": c["charged_rows"],
                               "fds": c["fds"]}
                           for v, c in d.items()} for lab, d in picks.items()}
        json.dump(held, open(path, "w"), indent=1)
        print("  written results/rq7_real_pool_orders.json", flush=True)
    return {t: [{k: v for k, v in c.items() if k != "fds"} for c in cs]
            for t, cs in out.items()}


def main():
    tags = [a for a in sys.argv[1:] if not a.startswith("--")] or ["owid"]
    path = os.path.join(CFG.RESULTS, "rq7_real_pool.json")
    held = json.load(open(path)) if os.path.exists(path) else {}
    for t in tags:
        key = f"{t}:{W.SLICE}" + (":refonly" if W.REFONLY else "")
        held[key] = run(t)
        json.dump(held, open(path, "w"), indent=1)
    print("\nwritten results/rq7_real_pool.json", flush=True)


if __name__ == "__main__":
    main()
