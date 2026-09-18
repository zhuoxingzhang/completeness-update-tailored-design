r"""The real release run live under monotone maps of its levels, the runs Table 8 and Figure 8 report.

Constraints.  release_live.py indexes every minimal key and the determinant of every non-key FD,
and issues each group rewrite as statements naming the stored rows by all their columns.  Here
every subschema carries an index on each of its minimal keys and nothing else, and a group whose
attribute the subschema stores away from a key is refreshed through a table G(X, A) keyed on X,
whose AFTER UPDATE trigger rewrites the group in the subschema; with no index on X that trigger
reads the subschema.  The admission G needs is issued just before, and charged to, the update it
serves.  A rule whose refresh would split or merge stored rows, or reach a group only in part,
cannot move through G; it keeps release_live.py's statements, and the record lists it.

Maps.  An attribute some determinant of the reduct reaches is graded 1 + min(9, floor(9 n / top))
by the refreshes n it receives in the scope, and a map phi issues each of its updates
1 + 2 floor(g / 2) times, g = phi(l) / (l phi(1)): the update, then round trips back to the value
the earlier edition holds and forward again, so the window still ends in the released state.  The
designs are the ones release_live.py runs.

Round trips.  A round trip issues the reverse update and the update again against the design's
moving state.  The first can differ from the rest, since a repair reaches past the group the
release names; the generator builds a second and a third and asserts that the third repeats the
second before issuing the second again.

The paper's runs: the observed levels three times, each of the maps once, with the buffer pool at
8 GiB, the closed binary logs purged and the server idle 600 s before every timed pass; the
visiting orders of the single passes are in results/rq7_real_visit.json.

Usage: python release_maps.py <tag> <obs|sq|exp2|cube> [<rounds>] [<batch>] [--dry] [--check-plain]
Environment: PICK, PICKVAR, SLICE as for release_live.py; ROT (the design a round starts from,
             0..2); POOL (buffer pool while timing, e.g. 8589934592; restored to 134217728
             afterwards); QUIET_HISTORY, QUIET_PAUSE (undo history to wait for, seconds idle
             before a timed pass); PURGE_BINLOGS (1, the default, purges the closed binary logs
             before each timed pass); MULTI (statements per packet for the untimed part, 0 =
             one by one)
Writes results/rq7_real_maps.json and never results/rq7_real_live.json
"""
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config as CFG

ARGS = [x for x in sys.argv[1:] if not x.startswith("--")]
TAG, MAP = ARGS[0], ARGS[1]
REPS = int(ARGS[2]) if len(ARGS) > 2 else 3
BATCH = int(ARGS[3]) if len(ARGS) > 3 else 1000
DRY = "--dry" in sys.argv
OUT = os.path.join(CFG.RESULTS, "rq7_real_maps.json")
ROT = int(os.environ.get("ROT", "0"))
POOL = int(os.environ.get("POOL", "0"))
MULTI = int(os.environ.get("MULTI", "0"))
DEFAULT_POOL = 134217728
# An explicit visiting order per round, when results/rq7_real_visit.json names one for this map.  A
# map run once per design cannot balance positions within itself, and under a map 3NF writes several
# times the rows of the others, so the orders run 3NF last and let SO and HA take turns in front of
# each other.
_vf = os.path.join(CFG.RESULTS, "rq7_real_visit.json")
VISIT_PLAN = json.load(open(_vf)).get(MAP, []) if os.path.exists(_vf) else []
# Quiescing before a timed pass: besides flushing the dirty pages, wait until purge has worked the undo
# history down to QUIET_HISTORY and keep the server idle QUIET_PAUSE seconds, so that the writes of the
# pass before and of this design's build are off the storage device when the clock starts.
QUIET_HISTORY = int(os.environ.get("QUIET_HISTORY", "1000"))
QUIET_PAUSE = int(os.environ.get("QUIET_PAUSE", "600"))
# The binary log grows by gigabytes per pass, so with PURGE_BINLOGS each quiescing first purges the
# closed binary logs: every design starts from the same free space.
PURGE_BINLOGS = os.environ.get("PURGE_BINLOGS", "1") == "1"
# A driver between two maps stands down when <scratch>/release_maps.stop exists: the run exits with
# code 3 before it touches the server.
STOP = os.path.join(CFG.scratch_dir(), "release_maps.stop")
if os.path.exists(STOP) and not DRY:
    print(f"{STOP} is present: not running {MAP}", flush=True)
    raise SystemExit(3)

# The relation, the designs, the workload and the statement generator are release_live.py's: its
# source up to the record it writes is run here, so that the two scripts cannot drift apart.
_live = os.path.join(HERE, "release_live.py")
src = open(_live, encoding="utf-8").read()
prefix = src[:src.index("\nKEY = TAG")]
assert "json.dump" not in prefix and ".write(" not in prefix, "the prefix of release_live.py would write"
_argv = sys.argv
sys.argv = [_live, TAG]
E2E = {"__name__": "release_live_prefix", "__file__": _live}
exec(compile(prefix, "release_live.py (prefix)", "exec"), E2E)
sys.argv = _argv
R, plan, Ds, WL, B = E2E["R"], E2E["plan"], E2E["Ds"], E2E["WL"], E2E["B"]
scope, lens, ORDER, picked, lab_var = E2E["scope"], E2E["lens"], E2E["ORDER"], E2E["picked"], E2E["lab_var"]
Mirror, hosts_of, rows_of, RW = E2E["Mirror"], E2E["hosts_of"], E2E["rows_of"], E2E["RW"]

# ---------- levels and the map -------------------------------------------------
MAPS = {"obs": lambda l: l, "sq": lambda l: l ** 2, "exp2": lambda l: 2 ** l, "cube": lambda l: l ** 3}
assert MAP in MAPS, MAP
PRICED = sorted(a for a, p in plan.items() if p["X"])
NREF = {a: int(plan[a]["events"]) for a in PRICED}
TOP = max(NREF.values())
LEVEL = {a: (1 + min(9, int(9 * n / TOP))) if n else 1 for a, n in NREF.items()}


def issues(m, l):
    g = MAPS[m](l) / (l * MAPS[m](1))
    return 1 + 2 * int(g // 2)


REP = {a: issues(MAP, LEVEL[a]) for a in PRICED}
print(f"\nmap {MAP}: " + ", ".join(f"{R.attrs[a]} l{LEVEL[a]} x{REP[a]}" for a in PRICED), flush=True)


def before(a, g, j):
    """The value the earlier edition holds on the rows one update names."""
    rws = [j] if g is None else [int(t) for t in rows_of(a, g)]
    vals = {scope[t][a] for t in rws}
    assert len(vals) == 1, f"{R.attrs[a]}: the rows one update names disagree before it"
    return next(iter(vals))


def g_ok(X, a):
    """Whether G(X, a) can be keyed on X at all."""
    return all(lens[c] <= 190 for c in X) and 4 * sum(min(2000, lens[c] + 8) for c in X) <= 3072


# ---------- one design's statements, generated against its own moving state -------
class Design:
    """release_live.stream, with groups of declared rules refreshed through G and with round trips.

    Each statement is (sql, params, subschema, charged, rows, priced, attribute, kind, server rows):
    kind u, d, i as in release_live.py, ga an admission to G, gu a refresh of G; the rows are the
    stored rows the statement writes in the subschema, the server rows what MySQL reports as
    matched.
    """

    def __init__(self, k, D, gdecl, strict):
        self.k, self.D, self.gdecl, self.strict = k, D, gdecl, strict
        self.hs = hosts_of(D)
        self.mir = Mirror()
        live = sorted({h["i"] for a in self.hs for h in self.hs[a]})
        self.proj = {}
        for i in live:
            cs = tuple(sorted(D[i][0]))
            c = collections.Counter()
            for t in range(R.n):
                c[tuple(self.mir.col[x][t] for x in cs)] += 1
            self.proj[i] = c
        self.sql, self.g, self.fail = {}, {}, collections.Counter()
        for (i, a), X in gdecl.items():
            cs = tuple(sorted(D[i][0]))
            xs, pos, held = [cs.index(c) for c in X], cs.index(a), {}
            for t in self.proj[i]:
                x = tuple(t[p] for p in xs)
                if held.setdefault(x, t[pos]) != t[pos]:
                    self.fail[(i, a)] += 1
            self.g[(i, a)] = held

    def one(self, a, g, j, v):
        mir, out = self.mir, []
        rws = [j] if g is None else [int(t) for t in rows_of(a, g)]
        reach = set(rws)
        for h in self.hs[a]:
            if h["charged"]:
                grp = mir.group(h["where"])
                for val in mir.vals(h["where"], rws):
                    reach.update(grp[val])
        rset = reach
        reach = sorted(reach)
        priced = bool(plan[a]["X"])
        for h in self.hs[a]:
            i, cs = h["i"], h["cols"]
            pos = cs.index(a)
            aff = collections.Counter()
            for t in reach:
                aff[tuple(mir.col[x][t] for x in cs)] += 1
            pj = self.proj[i]
            mv, de, ins = [], [], []
            for ot, c in aff.items():
                if ot[pos] == v:
                    continue
                assert pj[ot] >= c, f"{self.k} s{i}: a projection is stored {pj[ot]} times, {c} move"
                nt = ot[:pos] + (v,) + ot[pos + 1:]
                if c == pj[ot]:
                    del pj[ot]
                    (de if nt in pj else mv).append(ot)
                else:
                    pj[ot] -= c
                    if nt not in pj:
                        ins.append(nt)
                pj[nt] += c
            key = (i, a)
            if h["charged"] and key in self.gdecl:
                X = self.gdecl[key]
                xs = [cs.index(c) for c in X]
                groups = collections.OrderedDict()
                ok = not de and not ins
                for ot in mv:
                    x = tuple(ot[p] for p in xs)
                    if groups.setdefault(x, [ot[pos], 0])[0] != ot[pos]:
                        ok = False
                    groups[x][1] += 1
                if ok:
                    grp = mir.group(X) if tuple(X) != tuple(h["where"]) else mir.group(h["where"])
                    ok = all(set(grp[x]) <= rset for x in groups)
                if not ok:
                    assert not self.strict, f"{self.k} s{i}: {R.attrs[a]} cannot move through G here"
                    self.fail[key] += 1
                else:
                    gt, gd = f"d{self.k.lower()}_s{i}_g{a}", self.g[key]
                    for x, (old, n_) in groups.items():
                        if gd.get(x) != old:
                            # an admission: an upsert would fire the update trigger and read the
                            # subschema for a group that does not move
                            if x in gd:
                                q = self.sql.get(("gd", i, a))
                                if q is None:
                                    q = self.sql[("gd", i, a)] = (f"DELETE FROM {gt} WHERE "
                                                                 + " AND ".join(f"c{c}=%s" for c in X))
                                out.append((q, x, i, True, 0, priced, a, "gd", 1))
                            q = self.sql.get(("ga", i, a))
                            if q is None:
                                q = self.sql[("ga", i, a)] = (
                                    f"INSERT INTO {gt} (" + ",".join(f"c{c}" for c in X) + f",c{a}) VALUES ("
                                    + ",".join(["%s"] * (len(X) + 1)) + ")")
                            out.append((q, (*x, old), i, True, 0, priced, a, "ga", 1))
                            gd[x] = old
                        q = self.sql.get(("gu", i, a))
                        if q is None:
                            q = self.sql[("gu", i, a)] = (f"UPDATE {gt} SET c{a}=%s WHERE "
                                                         + " AND ".join(f"c{c}=%s" for c in X))
                        out.append((q, (v, *x), i, True, n_, priced, a, "gu", 1))
                        gd[x] = v
                    continue
            for kind, lst in (("u", mv), ("d", de), ("i", ins)):
                if not lst:
                    continue
                skey = (kind, i, a, len(lst))
                q = self.sql.get(skey)
                if q is None:
                    tbl = f"d{self.k.lower()}_s{i}"
                    one_ = "(" + ",".join(["%s"] * len(cs)) + ")"
                    if kind == "i":
                        q = (f"INSERT INTO {tbl} (" + ",".join(f"c{c2}" for c2 in cs)
                             + ") VALUES " + ",".join([one_] * len(lst)))
                    else:
                        head = f"UPDATE {tbl} SET c{a}=%s WHERE " if kind == "u" \
                            else f"DELETE FROM {tbl} WHERE "
                        if len(lst) == 1:
                            q = head + " AND ".join(f"c{c2}=%s" for c2 in cs)
                        else:
                            q = (head + "(" + ",".join(f"c{c2}" for c2 in cs) + ") IN ("
                                 + ",".join([one_] * len(lst)) + ")")
                    self.sql[skey] = q
                flat = [x for t in lst for x in t]
                out.append((q, ((v, *flat) if kind == "u" else tuple(flat)), i, h["charged"],
                            len(lst), priced, a, kind, len(lst)))
        mir.set(a, reach, v)
        return out

    def window(self, rep):
        for a, g, j, v in WL:
            r = rep.get(a, 1)
            if r == 1:
                yield from self.one(a, g, j, v)
                continue
            old = before(a, g, j)
            yield from self.one(a, g, j, v)
            back = self.one(a, g, j, old)
            yield from back
            fwd = self.one(a, g, j, v)
            yield from fwd
            t = (r - 1) // 2
            if t >= 2:
                back2, fwd2 = self.one(a, g, j, old), self.one(a, g, j, v)
                yield from back2
                yield from fwd2
                if t >= 3:
                    back3, fwd3 = self.one(a, g, j, old), self.one(a, g, j, v)
                    assert back3 == back2 and fwd3 == fwd2, \
                        f"{self.k} {R.attrs[a]}: the third round trip does not repeat the second"
                    for _ in range(t - 2):
                        yield from back2
                        yield from fwd2


def tally(acct, st):
    _q, _pr, _i, ch, n, gw, _a, kind, _srv = st
    acct["statements"] += 1
    acct["rows"] += n
    acct["kind_" + kind] += 1
    if ch:
        acct["charged_stmts"] += 1
        acct["charged_rows"] += n
    if gw:
        acct["priced_stmts"] += 1
        acct["priced_rows"] += n
        acct["priced_" + kind] += 1


def declare(k, D):
    """The rules a design can refresh through G over the whole window under this map."""
    cand = {}
    for a, hl in hosts_of(D).items():
        for h in hl:
            if h["charged"] and g_ok(h["where"], a):
                cand[(h["i"], a)] = tuple(h["where"])
    probe = Design(k, D, cand, strict=False)
    for _ in probe.window(REP):
        pass
    return {key: X for key, X in cand.items() if not probe.fail[key]}, \
        {f"s{i} {R.attrs[a]} via {[R.attrs[c] for c in cand[(i, a)]]}": n for (i, a), n in probe.fail.items() if n}


t00 = time.time()
DECL, plans = {}, {}
for k in ORDER:
    t0 = time.time()
    DECL[k], failed = declare(k, Ds[k])
    acct = collections.Counter()
    d = Design(k, Ds[k], DECL[k], strict=True)
    for st in d.window(REP):
        tally(acct, st)
    plans[k] = {"acct": dict(acct), "g_rules": [f"s{i} {R.attrs[a]} via {[R.attrs[c] for c in X]}"
                                                for (i, a), X in sorted(DECL[k].items())],
                "g_failed": failed,
                "keyless_subschemata": sum(1 for S, pr in Ds[k]
                                           if not any(kk and all(lens[x] <= 190 for x in kk)
                                                      for kk in B.minimal_keys(S, pr)))}
    print(f"  {k:4s} |D| {len(Ds[k])}, G rules {len(DECL[k])} (plain {len(failed)}: {failed}), "
          f"subschemata with no indexable key {plans[k]['keyless_subschemata']}   [{time.time() - t0:.0f}s]",
          flush=True)
    print(f"       {acct['statements']:,} stmts, {acct['rows']:,} rows; priced {acct['priced_stmts']:,} stmts "
          f"({acct['priced_gu']:,} G refreshes, {acct['priced_ga']:,} admissions), {acct['priced_rows']:,} rows, "
          f"charged {acct['charged_rows']:,}", flush=True)
    if "--check-plain" in sys.argv and MAP == "obs":
        mine = [st[:6] for st in Design(k, Ds[k], {}, strict=True).window(REP)]
        theirs = E2E["stream"](k, Ds[k])[0]
        assert len(mine) == len(theirs) and all(x == y for x, y in zip(mine, theirs)), \
            f"{k}: the plain statements differ from release_live.py's"
        print(f"       plain statements identical to release_live.py's ({len(mine):,})", flush=True)
        del mine, theirs

KEY = f"{TAG}:{MAP}:" + ",".join(f"{k}={lab_var[k]}" for k in ORDER) + ":keys+G"
res = {"dataset": TAG, "map": MAP, "slice": E2E["W"].SLICE, "reps": REPS, "batch": BATCH, "picked": picked,
       "rot": ROT, "visit_plan": VISIT_PLAN, "multi": MULTI, "quiet_history": QUIET_HISTORY,
       "quiet_pause": QUIET_PAUSE, "purge_binlogs": PURGE_BINLOGS,
       "levels": {R.attrs[a]: {"refreshes": NREF[a], "level": LEVEL[a], "issues": REP[a],
                               "updates": int(plan[a]["updates"])} for a in PRICED},
       "priced_updates": sum(int(plan[a]["updates"]) * REP[a] for a in PRICED),
       "designs": {k: {"size": len(Ds[k]), **plans[k], "rounds_s": [], "priced_s": [], "repair_s": [],
                       "position": [], "violations": [], "mismatch": [], "build_s": []} for k in ORDER}}
if DRY:
    print(f"\n--dry: {res['priced_updates']:,} priced updates under {MAP}; nothing was run   "
          f"[{time.time() - t00:.0f}s]", flush=True)
    raise SystemExit


def save():
    held = json.load(open(OUT)) if os.path.exists(OUT) else {}
    held[KEY] = res
    json.dump(held, open(OUT, "w"), indent=1)


# ---------- MySQL -----------------------------------------------------------------
import pymysql
from pymysql.constants import CLIENT

DB = CFG.RELEASE_DB
admin = CFG.connect(autocommit=True)
acur = admin.cursor()
for _try in range(10):          # a monitoring poll may be mid-query for a millisecond; a run is not
    acur.execute("SELECT COUNT(*) FROM information_schema.processlist "
                 "WHERE command NOT IN ('Sleep','Daemon') AND id <> CONNECTION_ID()")
    if acur.fetchone()[0] == 0:
        break
    time.sleep(1)
else:
    raise AssertionError("other statements are running on the server")
acur.execute(f"CREATE DATABASE IF NOT EXISTS {DB}")


def pool(size):
    seen = 0
    for _ in range(600):
        acur.execute("SELECT @@innodb_buffer_pool_size")
        now = int(acur.fetchone()[0])
        acur.execute("SHOW STATUS LIKE 'Innodb_buffer_pool_resize_status'")
        row = acur.fetchone()
        status = row[1] if row else ""
        idle = not status or "Completed" in status or "did not change" in status
        if idle and now == size:
            seen += 1
            if seen == 2:
                print(f"== buffer pool {size} {time.strftime('%H:%M:%S')}", flush=True)
                return
        else:
            seen = 0
            if idle:
                acur.execute(f"SET GLOBAL innodb_buffer_pool_size = {size}")
        time.sleep(2)
    raise RuntimeError(f"buffer pool did not reach {size}: {status}")


conn = CFG.connect(database=DB, autocommit=True,
                   client_flag=CLIENT.FOUND_ROWS | (CLIENT.MULTI_STATEMENTS if MULTI else 0))
cur = conn.cursor()
E2E["cur"] = cur


def drop_all():
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (DB,))
    for (t,) in list(cur.fetchall()):
        cur.execute(f"DROP TABLE IF EXISTS `{t}`")


def materialize(k, D, gdecl):
    tag = f"d{k.lower()}"
    for i, (XA, proj) in enumerate(D):
        cols = sorted(XA)
        tbl = f"{tag}_s{i}"
        mkeys = B.minimal_keys(XA, proj)
        ok = lambda ats: all(lens[x] <= 190 for x in ats)
        defs = [f"c{x} VARCHAR({min(2000, lens[x] + 8)}) NOT NULL" for x in cols]
        for jj, kk in enumerate(sorted((kk for kk in mkeys if kk and ok(kk)), key=sorted)):
            defs.append(f"KEY u{jj}({','.join('c%d' % c for c in sorted(kk))})")
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
        cur.execute(f"CREATE TABLE {tbl}({', '.join(defs)}) ENGINE=InnoDB")
        rows = list({tuple(r[c] for c in cols) for r in scope})
        ph = "(" + ",".join(["%s"] * len(cols)) + ")"
        for b in range(0, len(rows), 5000):
            cur.executemany(f"INSERT INTO {tbl} VALUES {ph}", rows[b:b + 5000])
        cur.execute(f"ANALYZE TABLE {tbl}")
    for (i, a), X in sorted(gdecl.items()):
        tbl, gt = f"{tag}_s{i}", f"{tag}_s{i}_g{a}"
        xc = [f"c{c}" for c in X]
        defs = [f"c{c} VARCHAR({min(2000, lens[c] + 8)}) NOT NULL" for c in list(X) + [a]]
        cur.execute(f"CREATE TABLE {gt}({', '.join(defs)}, PRIMARY KEY({','.join(xc)})) ENGINE=InnoDB")
        cur.execute(f"INSERT INTO {gt} SELECT DISTINCT {','.join(xc)}, c{a} FROM {tbl}")
        cur.execute(f"CREATE TRIGGER {gt}_au AFTER UPDATE ON {gt} FOR EACH ROW BEGIN "
                    f"IF NOT (NEW.c{a} <=> OLD.c{a}) THEN UPDATE {tbl} SET c{a}=NEW.c{a} WHERE "
                    + " AND ".join(f"{c}=NEW.{c}" for c in xc) + "; END IF; END")
        cur.execute(f"ANALYZE TABLE {gt}")


def drain():
    held = kept = 0
    if PURGE_BINLOGS:
        acur.execute("SHOW BINARY LOGS")
        held = sum(int(r[1]) for r in acur.fetchall())
        acur.execute("PURGE BINARY LOGS BEFORE NOW()")
        acur.execute("SHOW BINARY LOGS")
        kept = sum(int(r[1]) for r in acur.fetchall())
    t0 = time.time()
    cur.execute("SET GLOBAL innodb_max_dirty_pages_pct = 0")
    W.settle(cur, limit=100, timeout=900)
    t1 = time.time()
    hist = -1
    while True:
        cur.execute("SELECT count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len'")
        hist = int(cur.fetchone()[0])
        if hist <= QUIET_HISTORY or time.time() > t1 + 900:
            break
        time.sleep(5)
    t2 = time.time()
    time.sleep(QUIET_PAUSE)
    W.settle(cur, limit=100, timeout=900)
    cur.execute("SET GLOBAL innodb_max_dirty_pages_pct = 90")
    print(f"        {time.strftime('%H:%M:%S')} quiet: binary logs {held / 2**30:.1f} -> {kept / 2**30:.1f} GiB, "
          f"dirty pages flushed in {t1 - t0:.0f}s, undo history {hist} after {t2 - t1:.0f}s, "
          f"then idle {QUIET_PAUSE}s", flush=True)


save()
if POOL:
    pool(POOL)
try:
    drop_all()
    for rnd in range(REPS):
        s = (ROT + rnd) % len(ORDER)
        visit = ORDER[s:] + ORDER[:s]
        if rnd < len(VISIT_PLAN):
            visit = type(ORDER)(VISIT_PLAN[rnd])
            assert sorted(visit) == sorted(ORDER), f"not a visiting order: {visit}"
        print(f"\n--- {MAP} round {rnd + 1} of {REPS}, visiting {' '.join(visit)} ---", flush=True)
        for k in visit:
            drop_all()
            t0 = time.time()
            materialize(k, Ds[k], DECL[k])
            build = time.time() - t0
            drain()
            d = Design(k, Ds[k], DECL[k], strict=True)
            acct = collections.Counter()
            mism = [0, []]
            ct = gt_ = 0.0
            clock = time.perf_counter
            buf = []

            def check(srv, got, st):
                if srv is not None and got != srv:
                    mism[0] += 1
                    if len(mism[1]) < 4:
                        mism[1].append(f"s{st[2]} {st[7]} {R.attrs[st[6]]}: expected {srv}, matched {got}")

            def flush():
                """The untimed statements gathered so far, sent as one packet; every result is checked."""
                if not buf:
                    return
                cur.execute(";".join(s for s, _ in buf))
                j = 0
                while True:
                    check(buf[j][1][8], cur.rowcount, buf[j][1])
                    j += 1
                    if not cur.nextset():
                        break
                assert j == len(buf), f"{j} results for {len(buf)} statements"
                buf.clear()

            conn.autocommit(False)
            c = 0
            t0 = clock()
            for st in d.window(REP):
                q, pr, i, ch, n, gw, a, kind, srv = st
                tally(acct, st)
                if MULTI and not gw:
                    buf.append((cur.mogrify(q, pr), st))
                    if len(buf) >= MULTI:
                        flush()
                else:
                    flush()
                    s0 = clock()
                    cur.execute(q, pr)
                    el = clock() - s0
                    check(srv, cur.rowcount, st)
                    if ch:
                        ct += el
                    if gw:
                        gt_ += el
                c += 1
                if c % BATCH == 0:
                    flush()
                    conn.commit()
            flush()
            conn.commit()
            bad_rows, first_bad = mism
            dt = clock() - t0
            conn.autocommit(True)
            bad, broken = E2E["verify"](k, Ds[k], d.mir, rnd)
            r = res["designs"][k]
            assert dict(acct) == r["acct"], f"{k}: the live statements differ from the dry count"
            r["position"].append(visit.index(k) + 1)
            r["build_s"].append(round(build, 1))
            r["rounds_s"].append(round(dt, 1))
            r["priced_s"].append(round(gt_, 3))
            r["repair_s"].append(round(ct, 3))
            r["violations"].append(bad)
            r["mismatch"].append([bad_rows, first_bad])
            r["release_broke"] = broken
            print(f"   {k:4s} pos {visit.index(k) + 1}  build {build:5.0f}s  pass {dt:8.1f}s  "
                  f"priced {gt_:9.3f}s over {acct['priced_rows']:,} rows in {acct['priced_stmts']:,} stmts "
                  f"({acct['priced_gu']:,} through G)  repairs {ct:8.3f}s  "
                  f"rowcount mismatches {bad_rows}  ended {time.strftime('%H:%M:%S')}  "
                  + ("CORRECT" if not bad and not bad_rows else "FAILED: " + "; ".join((bad + first_bad)[:3])),
                  flush=True)
            save()
            assert not bad and not bad_rows, f"{k}: the pass disagrees with the mirror, stopping"
            drop_all()
finally:
    try:
        conn.autocommit(True)
        drop_all()
    finally:
        if POOL:
            pool(DEFAULT_POOL)

print(f"\n=== {MAP}: the priced updates, live ===", flush=True)
h = res["designs"]["HA"]
for k in ORDER:
    r = res["designs"][k]
    print(f"  {k:4s} pos {r['position']}  priced {r['priced_s']}  mean {sum(r['priced_s']) / len(r['priced_s']):.1f}s"
          + ("" if k == "HA" else f"  /HA {sum(r['priced_s']) / max(sum(h['priced_s']), 1e-9):.2f}x"), flush=True)
save()
print(f"\nwritten {OUT}", flush=True)
