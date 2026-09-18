r"""The design each criterion may return that the priced updates cost the most, and the least.

A criterion fixes a design only up to the order in which the closure is eliminated.  Structure-
optimal synthesis sorts the critical FDs by the number of non-key FDs their schema carries and the
rest by key count, keeping the input order among equals, and classical synthesis keeps the input
order throughout; neither reads the heat.  So every order is one the algorithm may be handed, and
every design it then returns is its output.  release_pool.py enumerates a pool of orders; this
prices each member of each class on the updates the heat accounts for, and then searches SO's
ties for its worst member and, with HA_SWAPS, HA's ties for its best one.  Heat-aware synthesis
sorts the critical FDs by the heat of their schema and the rest by key count, keeping the input
order among equals, so its ties are those.

The priced updates are the ones refreshing an attribute some determinant of the reduct reaches.
Their statements cost more than the rows they match: a statement rewrites a column, and every
index containing that column has its entry rewritten too.  release_live.materialize() indexes
each minimal key and each determinant of a non-key FD, so an attribute moved onto a key is an
indexed attribute.  The full price here is therefore the rows and the index entries of the priced
statements, weighted by seconds per row and per entry fitted on the live run.  The rows follow
release_cost.price exactly; the index entries follow materialize() exactly.

Of those statements the charged ones, which rewrite a group under a rule stored away from a key,
are what the heat of a design prices and predicts.  TARGET decides what "worst" means for the
search and for the picks named hottest: `charged` (default) ranks by total heat, then charged
rows, then the full price; `priced` ranks by the full price.  HA's class is also reported by its
charged rows, since a class that does not agree on them leaves a choice the live run must not
make in HA's favour: the pick charged_worst is its member with the most charged rows.

Membership is release_pool.py's: E-3NF, and for SO the least (maximal, total) count of non-key FDs
per subschema, for HA the least (maximal, total) heat, for 3NF every admissible design.  A search
step is kept only if the design it reaches is still in SO's class, and a design with a smaller SO
objective than the class optimum would be reported, since it would redefine the class.

The paper's designs come from this search with POOL=250 SWAPS=300 HA_SWAPS=300 TARGET=priced:
3NF at its priced_worst (order keep7_3), SO at its hottest (h+c+), HA at its priced_best.  The
run recorded before the heats were made positive (HEAT_FLOOR=0) returned the order haswap164 for
HA, which is the design the paper times; under the floor of 1 the search returns haswap239, whose
priced statements and rows are the same to within 0.2 per cent and whose heat is the same.  The
shipped results/rq7_real_picks.json holds the three orders the paper runs.

Usage: python release_classes.py [<tag>]          default owid
Environment: SLICE as in release_cost.py, SHUFFLES (random orders added to the named ones, as in
             release_pool.py) or POOL (the pool size, the named orders filled up with random
             ones), SWAPS (search steps, default 300), HA_SWAPS (search steps on HA's ties,
             default 0), TARGET (charged or priced), A_ROW and B_ENTRY (seconds per row and per
             index entry), OUTDIR (another directory for the two files, named after the tag)
Writes results/rq7_real_classes.json and results/rq7_real_orders.json (in the format
       release_live.py reads with PICK)
"""
import collections
import json
import os
import pickle
import random
import sys
import time

import numpy as np

try:                                   # a long run on Windows: below normal priority
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
except (ImportError, AttributeError, OSError):
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import synthesis as B

B.HEAT = "all"
import real_workload as RW
import release_cost as W
import release_pool as WB

TAG = sys.argv[1] if len(sys.argv) > 1 else "owid"
SWAPS = int(os.environ.get("SWAPS", "300"))
TARGET = os.environ.get("TARGET", "charged")
assert TARGET in ("charged", "priced"), TARGET
A_ROW = float(os.environ.get("A_ROW", "7.74e-5"))
B_ENTRY = float(os.environ.get("B_ENTRY", "2.706e-5"))
MODES = [("3NF", "3nf"), ("SO", "so"), ("HA", "ha")]
OUT = os.path.join(CFG.RESULTS, "rq7_real_classes.json")
ORD = os.path.join(CFG.RESULTS, "rq7_real_orders.json")
if os.environ.get("OUTDIR"):             # one file per window, so that windows can run in parallel
    OUT = os.path.join(os.environ["OUTDIR"], f"so_worst_{TAG}.json")
    ORD = os.path.join(os.environ["OUTDIR"], f"so_worst_orders_{TAG}.json")
t00 = time.time()

# ---------- the window, as release_live.py and release_pool.py read it ---------
raw = pickle.load(open(W.relpath(TAG), "rb"))
E = RW.choose_E(raw["data"], len(raw["attrs"]))
scope = [r for r in raw["data"] if all(r[a] is not None for a in E)]
lens = RW.col_lens(scope, len(raw["attrs"]))
del raw
R = W.Rel(TAG)
assert R.n == len(scope), f"scope disagrees: {R.n} vs {len(scope)}"
del scope
plan = W.coalesce(R)
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
hot_rhs = [a for a, _ in collections.Counter(ev).most_common()]
priced_attrs = sorted(a for a, p in plan.items() if p["X"])
print(f"{TAG}: scope {R.n:,}, reduct {len(R.reduct)}, {len(R.ev):,} {W.SLICE} events; priced "
      f"attributes " + ", ".join(R.attrs[a] for a in priced_attrs)
      + f"   [{time.time() - t00:.0f}s]", flush=True)

# ---------- membership, as release_pool.py decides it -----------------------------
primes, mk_of, ix_of = {}, {}, {}


def keys_of(S, pr):
    if S not in mk_of:
        mk_of[S] = mkeys.get(S) or B.minimal_keys(S, pr)
    return mk_of[S]


def e3nf(D):
    for XA, pr in D:
        if XA not in primes:
            ks = keys_of(XA, pr)
            primes[XA] = set().union(*ks) if ks else set()
        if any(next(iter(f[1])) not in primes[XA] for f in B.nonkey_atomic(XA, pr)):
            return False
    return True


def synth(order, mode):
    p = dict(prep)
    p["crit"] = [f for f in order if f in crit]
    p["noncrit"] = [f for f in order if f in noncrit]
    return B.synthesize(R.E, order, R.keys, mode, hot=theta, prep=p)


def so_obj(D):
    f = [len(B.nonkey_atomic(XA, pr)) for XA, pr in D]
    return (max(f, default=0), sum(f))


def dkey(D):
    return tuple(sorted(tuple(sorted(XA)) for XA, _ in D))


# ---------- the price of the priced updates ------------------------------------
def indexes(S, pr):
    """The index column sets materialize() creates on a subschema, duplicates included."""
    if S not in ix_of:
        mk = B.minimal_keys(S, pr)
        F = B.schema_nonkey(S, pr, mk, theta)
        ok = lambda ats: all(lens[a] <= 190 for a in ats)
        ix = [frozenset(k) for k in mk if k and ok(k)]
        ix += [frozenset(X) for X in {tuple(sorted(f[0])) for f in F if f[0] and ok(f[0])}]
        ix_of[S] = ix
    return ix_of[S]


def priced(D):
    st = rows = ent = chr_ = 0
    for S, pr in D:
        nk = collections.defaultdict(list)
        for fd in B.nonkey_atomic(S, pr):
            nk[next(iter(fd[1]))].append(fd)
        ix = indexes(S, pr)
        for a in S & set(priced_attrs):
            p = plan[a]
            nidx = sum(1 for x in ix if a in x)
            if a in nk:                   # away from a key here: the group is rewritten
                g = max((R.rows_per_group(S, f[0])[R.gid(f[0])] for f in nk[a]),
                        key=lambda v: v.sum())
                ch = True
            else:
                g, ch = None, False
            if p["whole"] is not None and p["whole"].any():
                per = R.rows_per_group(S, p["X"])
                idx = np.flatnonzero(p["whole"])
                r = per[idx].astype(np.int64)
                if ch:
                    gg = R.gid(p["X"])
                    rep = np.zeros(len(per), dtype=np.int64)
                    rep[gg] = np.arange(R.n)
                    r = np.maximum(r, g[rep[idx]])
                n = int(r.sum())
                st, rows, ent = st + len(idx), rows + n, ent + n * nidx
                chr_ += n if ch else 0
            lr = p["left_rows"]
            if len(lr):
                v = int(g[lr].sum()) if ch else len(lr)
                st, rows, ent = st + len(lr), rows + v, ent + v * nidx
                chr_ += v if ch else 0
    return {"priced_stmts": st, "priced_rows": rows, "priced_entries": ent,
            "priced_charged_rows": chr_, "priced_pred_s": A_ROW * rows + B_ENTRY * ent}


def record(D, name, order):
    met = B.decomp_metrics(D, theta)
    c = {"order": name, "subschemata": len(D), "hmax": met["hmax"], "htot": met["htot"],
         "so_obj": list(so_obj(D))}
    c.update(priced(D))
    c["copies"] = {R.attrs[a]: sum(1 for XA, _ in D if a in XA) for a in priced_attrs}
    c["fds"] = [[sorted(f[0]), sorted(f[1])] for f in order]
    c["_key"] = dkey(D)
    return c


def hot_key(c):
    return (c["htot"], c["priced_charged_rows"], c["priced_pred_s"])


def price_key(c):
    return (c["priced_pred_s"], c["htot"])


def charged_key(c):
    return (c["priced_charged_rows"], c["priced_pred_s"])


score = hot_key if TARGET == "charged" else price_key


def line(c):
    return (f"{c['order']:11s} |D| {c['subschemata']:3d} htot {c['htot']:>9,} "
            f"stmts {c['priced_stmts']:>7,} rows {c['priced_rows']:>10,} "
            f"entries {c['priced_entries']:>10,} charged {c['priced_charged_rows']:>8,} "
            f"{c['priced_pred_s']:8.2f}s")


# ---------- every member of every class over the pool ---------------------------
POOL = int(os.environ.get("POOL", "0"))
if POOL:                                  # fill the named orders up with shuffles to POOL orders
    WB.SHUFFLES = 0
    WB.SHUFFLES = max(POOL - len(WB.order_pool(R.reduct, heat, cost, fcnt, hot_rhs)), 0)
pool = WB.order_pool(R.reduct, heat, cost, fcnt, hot_rhs)
print(f"\npool of {len(pool)} orders   [{time.time() - t00:.0f}s]", flush=True)
classes, lowest_so = {}, None
for lab, mode in MODES:
    seen, recs, t1 = set(), [], time.time()
    for n, (name, order) in enumerate(pool.items()):
        D = synth(order, mode)
        if not e3nf(D):
            continue
        k = dkey(D)
        if k in seen:
            continue
        seen.add(k)
        recs.append(record(D, name, order))
        if n % 40 == 0:
            print(f"    {lab} {n}/{len(pool)} orders, {len(recs)} designs "
                  f"[{time.time() - t1:.0f}s]", flush=True)
    if not recs:
        print(f"  {lab:4s} no admissible design", flush=True)
        continue
    if lab == "SO":
        best = min(tuple(c["so_obj"]) for c in recs)
        cls = [c for c in recs if tuple(c["so_obj"]) == best]
        lowest_so = best
    elif lab == "HA":
        best = min((c["hmax"], c["htot"]) for c in recs)
        cls = [c for c in recs if (c["hmax"], c["htot"]) == best]
    else:
        cls = recs
    classes[lab] = cls
    ps = sorted(c["priced_pred_s"] for c in cls)
    hs = sorted({c["htot"] for c in cls})
    cs = sorted({c["priced_charged_rows"] for c in cls})
    print(f"  {lab:4s} {len(cls)}/{len(recs)} designs in its class   htot {hs[0]:,}..{hs[-1]:,}   "
          f"charged rows {cs[0]:,}..{cs[-1]:,}   priced {ps[0]:.2f}..{ps[-1]:.2f}s", flush=True)
    for c in sorted(cls, key=score, reverse=True)[:3]:
        print("       " + line(c), flush=True)

# ---------- SO's ties, searched for its worst member ---------------------------
found_lower, kept = None, 0
if "SO" in classes:
    so_cls = classes["SO"]
    memo = {c["_key"]: score(c) for c in so_cls}
    by_key = {c["_key"]: c for c in so_cls}
    start = max(so_cls, key=score)
    cur = [(frozenset(l), frozenset(r)) for l, r in start["fds"]]
    cur_val = score(start)
    fc = {fd: len(prep["nonkey"][fd[0] | fd[1]]) for fd in R.reduct}
    kc = {fd: len(mkeys[fd[0] | fd[1]]) for fd in R.reduct}
    ties = collections.defaultdict(list)
    for fd in R.reduct:
        ties[("c", fc[fd]) if fd in crit else ("n", kc[fd])].append(fd)
    movable = [g for g in ties.values() if len(g) > 1]
    weights = [len(g) for g in movable]
    rng = random.Random(0)
    t2 = time.time()
    print(f"\nsearching SO's ties by {TARGET} from " + line(start)
          + f": {len(movable)} tie groups, {SWAPS if movable else 0} steps", flush=True)
    for step in range(SWAPS if movable else 0):
        grp = rng.choices(movable, weights=weights)[0]
        f, g = rng.sample(grp, 2)
        pos = {x: i for i, x in enumerate(cur)}
        new = list(cur)
        new[pos[f]], new[pos[g]] = g, f
        D = synth(new, "so")
        if not e3nf(D):
            continue
        so = so_obj(D)
        if so < lowest_so:
            found_lower = {"so_obj": list(so), "step": step}
            print(f"    step {step}: a design with SO objective {so} below the class optimum "
                  f"{lowest_so}", flush=True)
            continue
        if so != lowest_so:
            continue
        k = dkey(D)
        if k not in memo:
            c = record(D, f"swap{step}", new)
            memo[k], by_key[k] = score(c), c
            so_cls.append(c)
        if memo[k] > cur_val:
            cur, cur_val, kept = new, memo[k], kept + 1
            print(f"    step {step}: " + line(by_key[k]) + f"   [{time.time() - t2:.0f}s]",
                  flush=True)
        elif step % 50 == 0:
            print(f"    step {step}   [{time.time() - t2:.0f}s]", flush=True)

# ---------- HA's ties, searched for its best member ----------------------------
HA_SWAPS = int(os.environ.get("HA_SWAPS", "0"))
ha_lower, ha_kept = None, 0
if "HA" in classes and HA_SWAPS:
    ha_cls = classes["HA"]
    ha_opt = min((c["hmax"], c["htot"]) for c in ha_cls)
    best_key = price_key if TARGET == "priced" else charged_key
    hmemo = {c["_key"]: best_key(c) for c in ha_cls}
    hby = {c["_key"]: c for c in ha_cls}
    start = min(ha_cls, key=best_key)
    cur = [(frozenset(l), frozenset(r)) for l, r in start["fds"]]
    cur_val = best_key(start)
    hk = {fd: sum(B.fd_hot(g, theta) for g in B.schema_nonkey(fd[0] | fd[1], proj[fd[0] | fd[1]],
                                                            mkeys[fd[0] | fd[1]], theta))
          for fd in crit}
    kc = {fd: len(mkeys[fd[0] | fd[1]]) for fd in R.reduct}
    ties = collections.defaultdict(list)
    for fd in R.reduct:
        ties[("c", hk[fd]) if fd in crit else ("n", kc[fd])].append(fd)
    movable = [g for g in ties.values() if len(g) > 1]
    weights = [len(g) for g in movable]
    rng = random.Random(1)
    t3 = time.time()
    print(f"\nsearching HA's ties by {TARGET} from " + line(start)
          + f": {len(movable)} tie groups, {HA_SWAPS if movable else 0} steps", flush=True)
    for step in range(HA_SWAPS if movable else 0):
        grp = rng.choices(movable, weights=weights)[0]
        f, g = rng.sample(grp, 2)
        pos = {x: i for i, x in enumerate(cur)}
        new = list(cur)
        new[pos[f]], new[pos[g]] = g, f
        D = synth(new, "ha")
        if not e3nf(D):
            continue
        met = B.decomp_metrics(D, theta)
        obj = (met["hmax"], met["htot"])
        if obj < ha_opt:
            ha_lower = {"hmax_htot": list(obj), "step": step}
            print(f"    step {step}: a design with HA objective {obj} below the class optimum "
                  f"{ha_opt}", flush=True)
            continue
        if obj != ha_opt:
            continue
        k = dkey(D)
        if k not in hmemo:
            c = record(D, f"haswap{step}", new)
            hmemo[k], hby[k] = best_key(c), c
            ha_cls.append(c)
        if hmemo[k] < cur_val:
            cur, cur_val, ha_kept = new, hmemo[k], ha_kept + 1
            print(f"    step {step}: " + line(hby[k]) + f"   [{time.time() - t3:.0f}s]", flush=True)
        elif step % 50 == 0:
            print(f"    step {step}   [{time.time() - t3:.0f}s]", flush=True)

# ---------- records ------------------------------------------------------------
picks = {}
if "SO" in classes:
    picks["SO"] = {"hottest": max(classes["SO"], key=hot_key),
                   "priced_worst": max(classes["SO"], key=price_key)}
if "HA" in classes:
    ha = classes["HA"]
    picks["HA"] = {"charged_worst": max(ha, key=charged_key),
                   "charged_best": min(ha, key=charged_key),
                   "priced_best": min(ha, key=price_key),
                   "priced_worst": max(ha, key=price_key)}
if "3NF" in classes:
    picks["3NF"] = {"hottest": max(classes["3NF"], key=hot_key),
                    "priced_worst": max(classes["3NF"], key=price_key)}
ha_charged = sorted({c["priced_charged_rows"] for c in classes.get("HA", [])})
print(f"\nHA's class agrees on its charged rows: {len(ha_charged) <= 1} {ha_charged[:8]}", flush=True)
print("picks:", flush=True)
for lab, d in picks.items():
    for v, c in d.items():
        print(f"  {lab:4s} {v:13s} " + line(c), flush=True)


def clean(c):
    return {k: v for k, v in c.items() if k != "_key"}


held = json.load(open(OUT)) if os.path.exists(OUT) else {}
held[TAG] = {"slice": W.SLICE, "target": TARGET, "a_row": A_ROW, "b_entry": B_ENTRY,
             "pool": len(pool), "swaps": SWAPS, "kept_steps": kept,
             "so_optimum": list(lowest_so) if lowest_so else None, "below_optimum": found_lower,
             "ha_swaps": HA_SWAPS, "ha_kept_steps": ha_kept, "ha_below_optimum": ha_lower,
             "ha_charged_rows": ha_charged,
             "classes": {lab: [{k: v for k, v in c.items() if k not in ("fds", "_key")}
                               for c in cs] for lab, cs in classes.items()}}
json.dump(held, open(OUT, "w"), indent=1)
ords = json.load(open(ORD)) if os.path.exists(ORD) else {}
ords[TAG] = {lab: {v: clean(c) for v, c in d.items()} for lab, d in picks.items()}
json.dump(ords, open(ORD, "w"), indent=1)
print(f"\nwritten {OUT} and {ORD}   [{time.time() - t00:.0f}s]", flush=True)
