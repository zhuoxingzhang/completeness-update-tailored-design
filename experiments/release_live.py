r"""The whole maintenance window of the real release, run live on each design the criteria return.

The window is run whole.  A uniform sample of the row-level diffs is not a sample of the window's
work: a release corrects a country-level column across every day of the file at once, so the
diff of two editions carries one row per country-day while the maintenance job carries one
statement per country, and it is the coalescing that the objective is about.

The statements are the ones the cost model prices.  An update is `UPDATE R SET a = v WHERE X = x`
as in the amplification proposition, so the diff is first coalesced back into the updates that
produced it (release_cost.coalesce) and each design then pays, per subschema holding the
attribute, one statement per update: keyed on the determinant when the attribute sits there away
from a key, so the whole group is repaired, and on the group itself otherwise.

The statements address the state they run against.  The release rewrites a whole block of
country-level columns, and the determinant a column coalesces on lies in that block, so a
statement built from the pre-window values would look for a group that has already moved and
match nothing.  Each design therefore carries its own mirror of the current state, every WHERE is
read off that mirror when the statement is issued, and a repair moves the determinant group as it
stands at that moment.  The mirrors diverge, because a repair reaches past the group the release
asked for, and that divergence is the cost of redundancy rather than an artefact.

Two accounts are kept: the rows each statement will match, derived from the mirror, and the rows
MySQL reports as matched, which have to agree.  release_cost.price is reported beside them as the
static prediction it is.  After each pass every constraint the design stores is checked to hold
and the values the window set are checked to be in place.  Every subschema is indexed on each of
its minimal keys and on the determinant of each non-key FD it stores; release_maps.py is the
variant the paper times, with keys alone and trigger tables.

Usage: python release_live.py [<tag>] [<rounds>] [<batch>] [--dry]
Environment: PICK (default results/rq7_real_picks.json) and PICKVAR (default
             3NF=priced_worst,SO=hottest,HA=priced_best) name which design of each class to run;
             SLICE, WINDOW, SIGMA as in release_cost.py; PROBE=<n> runs the first n statements of
             the design PROBEK (default 3NF) and reports the rows they match
Writes results/rq7_real_live.json; --dry builds and prices the streams and writes nothing
"""
import collections
import json
import os
import pickle
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import synthesis as B

B.HEAT = "all"
import release_cost as W

ARGS = [x for x in sys.argv[1:] if not x.startswith("--")]
TAG = ARGS[0] if ARGS else "owid"
REPS = int(ARGS[1]) if len(ARGS) > 1 else 3
BATCH = int(ARGS[2]) if len(ARGS) > 2 else 1000
DB = CFG.RELEASE_DB
OUT = os.path.join(CFG.RESULTS, "rq7_real_live.json")
ORDER = ["3NF", "SO", "HA"]
MODE_OF = {"3NF": "3nf", "SO": "so", "HA": "ha"}
SAMPLE_CHECK = 2000


# ---------- relation, declaration, designs -----------------------------------
d = pickle.load(open(W.relpath(TAG), "rb"))
ATTRS, data = d["attrs"], d["data"]
E = W.choose_E(data, len(ATTRS))
scope = [r for r in data if all(r[a] is not None for a in E)]
R = W.Rel(TAG)
assert R.n == len(scope), f"scope disagrees: {R.n} vs {len(scope)}"
M = len(ATTRS)
plan = W.coalesce(R)
nev = {}
for a, j, _ in R.ev:
    nev.setdefault(a, np.zeros(R.n, dtype=np.int64))[j] += 1
theta = W.floor({fd: (int(nev[next(iter(fd[1]))].sum()) if next(iter(fd[1])) in nev else 0)
                 for fd in R.reduct})
prep = B.prepare(R.reduct)
lens = W.col_lens(scope, len(ATTRS))

PICK = os.environ.get("PICK", os.path.join(CFG.RESULTS, "rq7_real_picks.json"))
if PICK.lower() in ("", "none", "plain"):
    PICK = ""
lab_var = dict(p.split("=") for p in os.environ.get(
    "PICKVAR", "3NF=priced_worst,SO=hottest,HA=priced_best").split(","))
Ds, picked = {}, {}
for k in ORDER:
    if PICK:
        rec = json.load(open(PICK))[TAG][k][lab_var[k]]
        order = [(frozenset(l), frozenset(r)) for l, r in rec["fds"]]
        assert set(order) == set(R.reduct), f"{k}: the dumped order is not this reduct"
        p2 = dict(prep)
        p2["crit"] = [f for f in order if f in set(prep["crit"])]
        p2["noncrit"] = [f for f in order if f in set(prep["noncrit"])]
        Ds[k] = B.synthesize(R.E, order, R.keys, MODE_OF[k], hot=theta, prep=p2)
        picked[k] = {"variant": lab_var[k], "order": rec["order"]}
    else:
        Ds[k] = B.synthesize(R.E, R.reduct, R.keys, MODE_OF[k], hot=theta, prep=prep)
        picked[k] = {"variant": "plain", "order": "reduct"}

print(f"{TAG}: scope {R.n:,}, {M} attrs, reduct {len(R.reduct)}, {len(R.keys)} minimal keys, "
      f"{len(R.ev):,} {W.SLICE} events in the whole window", flush=True)
for a, p in sorted(plan.items(), key=lambda kv: -kv[1]["events"])[:8]:
    print(f"  {R.attrs[a]:32s} {p['events']:9,} events -> {p['updates']:8,} updates "
          f"({p['events'] / max(p['updates'], 1):7.1f}x) via "
          f"{'{' + ','.join(R.attrs[c] for c in p['X']) + '}' if p['X'] else '-'}", flush=True)


# ---------- the coalesced workload, in the log's own order --------------------
GROUP_ROWS = {}


def rows_of(a, g):
    """The base rows of one whole group of the coalescing determinant, as the plan fixed it."""
    if a not in GROUP_ROWS:
        gid = R.gid(plan[a]["X"])
        order = np.argsort(gid, kind="stable")
        bounds = np.searchsorted(gid[order], np.arange(gid.max() + 2))
        GROUP_ROWS[a] = (order, bounds)
    order, bounds = GROUP_ROWS[a]
    return order[bounds[g]:bounds[g + 1]]


def workload():
    """The updates the diff coalesces into: one per whole group, one per leftover event."""
    seen, out = set(), []
    gids = {a: (R.gid(plan[a]["X"]) if plan[a]["X"] else None) for a in plan}
    for a, j, v in R.ev:
        p = plan.get(a)
        if p is None:
            continue
        g = gids[a]
        if p["whole"] is not None and g is not None and p["whole"][g[j]]:
            key = (a, int(g[j]))
            if key in seen:
                continue
            seen.add(key)
            out.append((a, int(g[j]), None, v))
        else:
            out.append((a, None, int(j), v))
    return out


WL = workload()
want = sum(p["updates"] for p in plan.values())
assert len(WL) == want, f"{len(WL)} updates derived, {want} expected from the plan"
NG = sum(1 for u in WL if u[1] is not None)
print(f"workload: {len(WL):,} updates = {NG:,} whole-group rewrites + {len(WL) - NG:,} single "
      f"rows, from {len(R.ev):,} row-level events ({len(R.ev) / max(len(WL), 1):.1f}x coalescing)",
      flush=True)


# ---------- one design's pass, generated against its own moving state ---------
class Mirror:
    """The current value of every attribute of every base row, as one design holds it.

    A design's state is the join of its subschemata, so an update this design must propagate
    past the group the release named shows up here too.  Group lookups are rebuilt lazily and
    only for the attribute sets some statement addresses, and only after one of those attributes
    has moved.
    """

    def __init__(self):
        self.col = [list(c) for c in zip(*scope)]
        self.ver = [0] * M
        self.idx = {}

    def vals(self, cols, rws):
        """The distinct value tuples the rows currently carry on `cols`, order preserved."""
        seen, out = set(), []
        for t in rws:
            k = tuple(self.col[c][t] for c in cols)
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def group(self, cols):
        """Value tuple -> base rows, for one attribute set, rebuilt only when it has moved."""
        v = tuple(self.ver[c] for c in cols)
        held = self.idx.get(cols)
        if held is None or held[0] != v:
            g = collections.defaultdict(list)
            for t in range(R.n):
                g[tuple(self.col[c][t] for c in cols)].append(t)
            held = self.idx[cols] = (v, g)
        return held[1]

    def stored(self, cols, rws):
        """How many distinct rows a subschema on `cols` currently holds over those base rows."""
        return len({tuple(self.col[c][t] for c in cols) for t in rws})

    def set(self, a, rws, v):
        for t in rws:
            self.col[a][t] = v
        self.ver[a] += 1


def hosts_of(D):
    """Per attribute, the subschemata that store it and how a statement addresses it there."""
    out = collections.defaultdict(list)
    for i, (S, proj) in enumerate(D):
        touched = S & set(plan)
        if not touched:
            continue
        mkeys = B.minimal_keys(S, proj)
        nk = collections.defaultdict(list)
        for fd in B.nonkey_atomic(S, proj):
            nk[next(iter(fd[1]))].append(fd)
        for a in touched:
            if a in nk:      # away from a key here: the statement repairs the determinant group
                fd = max(nk[a], key=lambda f: R.rows_per_group(S, f[0]).sum())
                where, charged = tuple(sorted(fd[0])), True
            else:            # on a key here: the statement reaches the group's own stored rows
                cand = [kk for kk in mkeys if a not in kk] or list(mkeys)
                where = tuple(sorted(min(cand, key=lambda kk: (len(kk), sorted(kk)))))
                charged = False
            out[a].append({"i": i, "cols": tuple(sorted(S)), "where": where, "charged": charged,
                           "inS": set(plan[a]["X"]) <= S and bool(plan[a]["X"])})
    return out


def stream(k, D):
    """What one design issues for the whole window, and the rows each statement will match.

    A stored row is a distinct projection of the scope, carried by however many base rows agree
    on it.  A release that moves only some of those rows splits the projection: the old row keeps
    the support that stayed behind and the new one has to be added.  So one attribute update costs
    each subschema holding the attribute an UPDATE of the projections whose whole support moves,
    an INSERT of the images of the ones that split, and a DELETE of the ones whose image the table
    already holds, which is where the release makes two projections coincide.  The amplification
    proposition governs the first of the three: a subschema storing the attribute away from a key
    has to move the whole group of the determinant it sits under, so the support of every row of
    that group moves at once and no row of it splits.
    """
    hs = hosts_of(D)
    mir = Mirror()
    live = sorted({h["i"] for a in hs for h in hs[a]})
    proj = {}
    for i in live:
        cs = tuple(sorted(D[i][0]))
        c = collections.Counter()
        for t in range(R.n):
            c[tuple(mir.col[x][t] for x in cs)] += 1
        proj[i] = c
    sql, stmts = {}, []
    acct = {"statements": 0, "rows": 0, "charged_rows": 0, "charged_stmts": 0,
            "priced_stmts": 0, "priced_rows": 0,
            "updated": 0, "inserted": 0, "deleted": 0}
    for a, g, j, v in WL:
        rws = [j] if g is None else [int(t) for t in rows_of(a, g)]
        reach = set(rws)
        for h in hs[a]:
            if h["charged"]:
                grp = mir.group(h["where"])
                for val in mir.vals(h["where"], rws):
                    reach.update(grp[val])
        reach = sorted(reach)
        for h in hs[a]:
            i, cs = h["i"], h["cols"]
            pos = cs.index(a)
            aff = collections.Counter()
            for t in reach:
                aff[tuple(mir.col[x][t] for x in cs)] += 1
            pj = proj[i]
            mv, de, ins = [], [], []
            for ot, c in aff.items():
                if ot[pos] == v:
                    continue
                assert pj[ot] >= c, f"{k} s{i}: a projection is stored {pj[ot]} times, {c} move"
                nt = ot[:pos] + (v,) + ot[pos + 1:]
                if c == pj[ot]:
                    del pj[ot]
                    (de if nt in pj else mv).append(ot)
                else:
                    pj[ot] -= c
                    if nt not in pj:
                        ins.append(nt)
                pj[nt] += c
            for kind, lst in (("u", mv), ("d", de), ("i", ins)):
                if not lst:
                    continue
                key = (kind, i, a, len(lst))
                q = sql.get(key)
                if q is None:
                    tbl = f"d{k.lower()}_s{i}"
                    one = "(" + ",".join(["%s"] * len(cs)) + ")"
                    if kind == "i":
                        q = (f"INSERT INTO {tbl} (" + ",".join(f"c{c2}" for c2 in cs)
                             + ") VALUES " + ",".join([one] * len(lst)))
                    else:
                        head = f"UPDATE {tbl} SET c{a}=%s WHERE " if kind == "u" \
                            else f"DELETE FROM {tbl} WHERE "
                        if len(lst) == 1:
                            q = head + " AND ".join(f"c{c2}=%s" for c2 in cs)
                        else:
                            q = (head + "(" + ",".join(f"c{c2}" for c2 in cs) + ") IN ("
                                 + ",".join([one] * len(lst)) + ")")
                    sql[key] = q
                flat = [x for t in lst for x in t]
                priced = bool(plan[a]["X"])     # an attribute some determinant of the reduct reaches
                stmts.append((q, ((v, *flat) if kind == "u" else tuple(flat)),
                              i, h["charged"], len(lst), priced))
                acct["statements"] += 1
                acct["rows"] += len(lst)
                acct["charged_rows"] += len(lst) if h["charged"] else 0
                acct["charged_stmts"] += 1 if h["charged"] else 0
                acct["priced_stmts"] += 1 if priced else 0
                acct["priced_rows"] += len(lst) if priced else 0
            acct["updated"] += len(mv)
            acct["deleted"] += len(de)
            acct["inserted"] += len(ins)
        mir.set(a, reach, v)
    return stmts, acct, mir


def materialize(tag, D):
    meta = []
    for i, (XA, proj) in enumerate(D):
        cols = sorted(XA)
        tbl = f"{tag}_s{i}"
        mkeys = B.minimal_keys(XA, proj)
        F = B.schema_nonkey(XA, proj, mkeys, theta)
        ok = lambda ats: all(lens[a] <= 190 for a in ats)
        defs = [f"c{a} VARCHAR({min(2000, lens[a] + 8)}) NOT NULL" for a in cols]
        for jj, kk in enumerate(sorted((kk for kk in mkeys if kk and ok(kk)), key=sorted)):
            defs.append(f"KEY u{jj}({','.join('c%d' % c for c in sorted(kk))})")
        for jj, X in enumerate(sorted({tuple(sorted(f[0])) for f in F if f[0] and ok(f[0])})):
            defs.append(f"KEY d{jj}({','.join('c%d' % c for c in X)})")
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
        cur.execute(f"CREATE TABLE {tbl}({', '.join(defs)}) ENGINE=InnoDB")
        rows = list({tuple(r[c] for c in cols) for r in scope})
        ph = "(" + ",".join(["%s"] * len(cols)) + ")"
        for b in range(0, len(rows), 5000):
            cur.executemany(f"INSERT INTO {tbl} VALUES {ph}", rows[b:b + 5000])
        meta.append({"tbl": tbl, "cols": cols, "nrows": len(rows)})
    return meta


EXPECT = {}


def expected(k, D, mir):
    """Per stored non-key rule, the groups the state the release left behind leaves violated.

    A release edits determinants, so two groups of a rule can merge and then disagree on its
    right-hand side.  No repair mends that, and the algorithm never claimed one: what the design
    owes is the group rewrite of the amplification proposition, which it performs.  So the rule
    is not the test.  The test is that MySQL holds what the mirror holds, and the mirror is
    scanned once per design.
    """
    if k in EXPECT:
        return EXPECT[k]
    out = {}
    for i, (S, proj) in enumerate(D):
        for fd in B.nonkey_atomic(S, proj):
            a, X = next(iter(fd[1])), tuple(sorted(fd[0]))
            g = collections.defaultdict(set)
            for t in range(R.n):
                g[tuple(mir.col[c][t] for c in X)].add(mir.col[a][t])
            out[(i, X, a)] = sum(1 for v in g.values() if len(v) > 1)
    EXPECT[k] = out
    return out


def verify(k, D, mir, seed):
    """The state MySQL holds is the mirror's, rule by rule, row by row and value by value."""
    bad = []
    want = expected(k, D, mir)
    broken = 0
    for i, (S, proj) in enumerate(D):
        tbl = f"d{k.lower()}_s{i}"
        for fd in B.nonkey_atomic(S, proj):
            a, X = next(iter(fd[1])), sorted(fd[0])
            cols = ",".join(f"c{c}" for c in X)
            cur.execute(f"SELECT COUNT(*) FROM (SELECT {cols} FROM {tbl} GROUP BY {cols} "
                        f"HAVING COUNT(DISTINCT c{a})>1) x")
            n_ = cur.fetchone()[0]
            w = want[(i, tuple(X), a)]
            broken += w > 0
            if n_ != w:
                bad.append(f"{tbl}: {n_} groups violate {X}->{a}, the mirror has {w}")
    rr = random.Random(seed)
    for i, (S, _proj) in enumerate(D):
        cols = sorted(S)
        touched = [a for a in cols if a in plan]
        if not touched:
            continue
        tbl = f"d{k.lower()}_s{i}"
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        got = cur.fetchone()[0]
        held = mir.stored(tuple(cols), range(R.n))
        if got != held:
            bad.append(f"{tbl}: {got} rows stored, the mirror holds {held}")
        for a in touched:                       # the value histogram of every updated attribute
            cur.execute(f"SELECT c{a}, COUNT(*) FROM {tbl} GROUP BY c{a}")
            sql_h = dict(cur.fetchall())
            mine = collections.Counter(
                t[cols.index(a)] for t in {tuple(mir.col[c][x] for c in cols)
                                           for x in range(R.n)})
            if sql_h != dict(mine):
                diff = {vv: (sql_h.get(vv), mine.get(vv)) for vv in set(sql_h) | set(mine)
                        if sql_h.get(vv) != mine.get(vv)}
                bad.append(f"{tbl}.{R.attrs[a]}: {len(diff)} values disagree, "
                           f"first {list(diff.items())[:2]}")
                break
    return bad, broken


KEY = TAG + ("" if not PICK else ":" + ",".join(f"{k}={lab_var[k]}" for k in ORDER))
res = {"dataset": TAG, "slice": W.SLICE, "scope": R.n, "events": len(R.ev),
       "updates": len(WL), "groups": NG, "reps": REPS, "batch": BATCH, "picked": picked,
       "priced_updates": sum(p["updates"] for p in plan.values() if p["X"]),
       "designs": {}}
res["priced_attrs"] = {R.attrs[a]: {"events": int(p["events"]), "updates": int(p["updates"]),
                                    "via": [R.attrs[c] for c in sorted(p["X"])]}
                       for a, p in plan.items() if p["X"]}
res["priced_events"] = sum(v["events"] for v in res["priced_attrs"].values())
res["plan_events"] = int(sum(p["events"] for p in plan.values()))
res["relation"] = {"tuples": len(data), "attrs": M, "E": len(E), "reduct": len(R.reduct),
                   "keys": len(R.keys)}
allres = json.load(open(OUT)) if os.path.exists(OUT) else {}
streams, mirrors = {}, {}
for k in ORDER:
    t0 = time.time()
    stmts, acct, mir = stream(k, Ds[k])
    pred = W.price(R, plan, Ds[k], theta)
    met = B.decomp_metrics(Ds[k], theta)
    streams[k], mirrors[k] = stmts, mir
    res["designs"][k] = {"size": len(Ds[k]), "hmax": met["hmax"], "htot": met["htot"],
                         "issued": acct,
                         "static": {kk: pred[kk] for kk in ("statements", "rows",
                                                            "charged_rows", "pred_s")},
                         "rounds_s": [], "repair_s": [], "repair_rows": [], "matched_rows": [],
                         "violations": []}
    print(f"  {k:4s} ({picked[k]['variant']:8s}) |D|={len(Ds[k]):3d} hmax={met['hmax']:>8,} "
          f"htot={met['htot']:>8,}   issues {acct['statements']:>9,} stmts, matching "
          f"{acct['rows']:>10,} rows ({acct['charged_rows']:,} charged)   "
          f"static model {pred['statements']:>9,} / {pred['rows']:>10,} / "
          f"{pred['charged_rows']:,}, {pred['pred_s']:.1f}s   [{time.time() - t0:.0f}s]",
          flush=True)
if "--dry" in sys.argv:
    print("\n--dry: the streams are built and priced, nothing was run and nothing written", flush=True)
    raise SystemExit
json.dump({**allres, KEY: res}, open(OUT, "w"), indent=1)

# ---------- MySQL ------------------------------------------------------------
import pymysql
from pymysql.constants import CLIENT

admin = CFG.connect(autocommit=True)
admin.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {DB}")
admin.close()
conn = CFG.connect(database=DB, autocommit=True, client_flag=CLIENT.FOUND_ROWS)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (DB,))
for (t,) in list(cur.fetchall()):
    cur.execute(f"DROP TABLE IF EXISTS `{t}`")


def drop(k):
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name LIKE %s", (DB, "d" + k.lower() + "\\_%"))
    for (t,) in list(cur.fetchall()):
        cur.execute(f"DROP TABLE IF EXISTS `{t}`")


# The designs are visited round-robin, each round rebuilding the design it is about to time and
# dropping it again afterwards.  Timing every pass of one design in a row does not work here: a
# pass leaves the redo log far ahead of the checkpoint, and the second pass over the same
# statements, matching the same rows, ran 7.6 times slower than the first.
PROBE = int(os.environ.get("PROBE", "0"))
if PROBE:
    k = os.environ.get("PROBEK", "3NF")
    print(f"\n--- probe: the first {PROBE:,} statements of {k} ---", flush=True)
    drop(k)
    materialize(f"d{k.lower()}", Ds[k])
    bad = 0
    for c, (q, pr, i, ch, n_, _g) in enumerate(streams[k][:PROBE]):
        cur.execute(q, pr)
        got = cur.rowcount
        if got != n_:
            bad += 1
            if bad <= 6:
                print(f"  #{c} s{i} charged={ch}: account {n_}, matched {got}\n"
                      f"      {q[:130]}\n"
                      f"      subschema {[R.attrs[x] for x in sorted(Ds[k][i][0])]}\n"
                      f"      first values {pr[:6]}", flush=True)
    print(f"  {bad:,} of {min(PROBE, len(streams[k])):,} statements disagree", flush=True)
    drop(k)
    raise SystemExit


def drain():
    """Leave InnoDB with a clean buffer pool, so a pass does not inherit the last one's work."""
    cur.execute("SET GLOBAL innodb_max_dirty_pages_pct = 0")
    W.settle(cur, limit=100, timeout=900)
    cur.execute("SET GLOBAL innodb_max_dirty_pages_pct = 90")


for rnd in range(REPS):
    visit = ORDER[rnd % len(ORDER):] + ORDER[:rnd % len(ORDER)]
    print(f"\n--- round {rnd + 1} of {REPS}, visiting {' '.join(visit)} ---", flush=True)
    for k in visit:
        drop(k)
        t0 = time.time()
        meta = materialize(f"d{k.lower()}", Ds[k])
        for m in meta:
            cur.execute(f"ANALYZE TABLE {m['tbl']}")
        build = time.time() - t0
        drain()
        got = crows = cstm = grows = gstm = 0
        ct = gt = 0.0
        per = collections.defaultdict(lambda: [0.0, 0, 0])
        clock = time.perf_counter
        if BATCH > 1:
            conn.autocommit(False)
        t0 = clock()
        for c, (q, pr, i, ch, _n, gw) in enumerate(streams[k]):
            s0 = clock()
            cur.execute(q, pr)
            el = clock() - s0
            n_ = cur.rowcount
            got += n_
            u = per[i]
            u[0] += el
            u[1] += 1
            u[2] += n_
            if ch:
                ct += el
                crows += n_
                cstm += 1
            if gw:
                gt += el
                grows += n_
                gstm += 1
            if BATCH > 1 and (c + 1) % BATCH == 0:
                conn.commit()
        if BATCH > 1:
            conn.commit()
        dt = clock() - t0
        conn.autocommit(True)
        bad, broken = verify(k, Ds[k], mirrors[k], rnd)
        r = res["designs"][k]
        r["release_broke"] = broken
        r["position"] = r.get("position", []) + [visit.index(k) + 1]
        r["rounds_s"].append(round(dt, 1))
        r["repair_s"].append(round(ct, 3))
        r["repair_rows"].append(crows)
        for f, x in (("repair_stmts", cstm), ("priced_s", round(gt, 3)),
                     ("priced_rows", grows), ("priced_stmts", gstm)):
            r.setdefault(f, []).append(x)
        r["matched_rows"].append(got)
        r["violations"].append(bad)
        iss = r["issued"]
        r["slowest"] = sorted(([round(v[0], 1), v[1], v[2], i] for i, v in per.items()),
                              reverse=True)[:6]
        print(f"   {k:4s} pos {visit.index(k) + 1}  build {build:5.0f}s  pass {dt:9.1f}s  "
              f"{got:,} rows matched "
              f"(issued {iss['rows']:,}, {100 * (got / max(iss['rows'], 1) - 1):+.3f}%); "
              f"repairs {ct:7.3f}s ({100 * ct / dt:4.1f}%) over {crows:,} rows "
              f"in {cstm:,} statements (issued {iss['charged_rows']:,}); "
              f"the priced updates {gt:7.3f}s over {grows:,} rows in {gstm:,} statements; "
              f"{broken} stored rules the release broke; "
              + ("CORRECT" if not bad else "FAILED: " + "; ".join(bad[:3])), flush=True)
        json.dump({**allres, KEY: res}, open(OUT, "w"), indent=1)
        drop(k)

print("\n=== the whole window, run live ===", flush=True)
for k in ORDER:
    r = res["designs"][k]
    med = sorted(r["rounds_s"])[len(r["rounds_s"]) // 2]
    print(f"  {k:4s} pos {r.get('position', [])}  hmax {r['hmax']:>8,}  "
          f"htot {r['htot']:>8,}  "
          f"{r['issued']['statements']:>9,} stmts  {r['matched_rows'][0]:>10,} rows  "
          f"repair rows {r['repair_rows'][0]:>9,}  median {med:8.1f}s  "
          f"rounds {r['rounds_s']}", flush=True)
h = res["designs"]["HA"]
for k in ("3NF", "SO"):
    b = res["designs"][k]
    for rn in range(len(b["rounds_s"])):
        print(f"  round {rn + 1}: {k}/HA whole {b['rounds_s'][rn] / h['rounds_s'][rn]:.3f}x  "
              f"repairs {b['repair_s'][rn] / max(h['repair_s'][rn], 0.001):.1f}x  "
              f"priced {b['priced_s'][rn] / max(h['priced_s'][rn], 0.001):.2f}x", flush=True)
print("  htot: " + "  ".join(
    f"{k}/HA {res['designs'][k]['htot'] / max(h['htot'], 1):.2f}x" for k in ("3NF", "SO")),
      flush=True)
json.dump({**allres, KEY: res}, open(OUT, "w"), indent=1)
print(f"\nwritten {OUT}", flush=True)
