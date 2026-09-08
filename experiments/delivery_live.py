# -*- coding: utf-8 -*-
"""One maintenance window on the delivery schema, issued against MySQL on each design.

The window is drawn once, from `delivery_schema.events`, and both designs then carry the same
logical updates, so what is timed is the design and nothing else.  Statements are derived
from the state the window has actually reached rather than from the state it started in: a
window that renames a courier twice has to locate the second rename by the name the first one
left behind, and a design that is issued statements written against the initial state stops
agreeing with the other one part way through.  The simulator that tracks that state also
gives the exact row counts, which `--dry` compares against the static model.

Protocol, as in the earlier window study: the buffer pool is raised for the run and restored
afterwards, designs are timed round-robin within each repetition rather than one after the
other, and each design is rebuilt and analysed inside its own turn.

Usage: python delivery_live.py --dry              row counts only, no server
       python delivery_live.py --verify           both designs, reconstructed and compared
       python delivery_live.py --reads            the read side of each design
       python delivery_live.py --ops              one update of each kind, over group depths
       python delivery_live.py --mixed            refreshes with a growing share of completions
       python delivery_live.py [--tiny]           the timed run
"""
import itertools
import json
import os
import subprocess
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import delivery_schema as S
import delivery_curves as C

MYSQL = CFG.MYSQL_CLIENT
DB = CFG.DELIVERY_DB
SCRATCH = CFG.scratch_dir()
os.makedirs(SCRATCH, exist_ok=True)

POOL_BIG = 8 * 1024 ** 3
POOL_SMALL = 128 * 1024 ** 2
REST = "rest"


def result(name):
    """Where a result file goes, which the artifact keeps in one directory."""
    return os.path.join(CFG.RESULTS, name)


# ---- MySQL ------------------------------------------------------------------
def sh(sql, db=DB):
    args = [MYSQL, "--local-infile=1", "-h", CFG.MYSQL_HOST,
            "-P", str(CFG.MYSQL_PORT), "-u", CFG.MYSQL_USER, "-N", "-B"]
    if CFG.MYSQL_PASSWORD:
        args.append("-p" + CFG.MYSQL_PASSWORD)
    if db:
        args.append(db)
    r = subprocess.run(args, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"SQL ERR: {r.stderr}\nSQL: {sql[:600]}\n")
        raise SystemExit(1)
    return r.stdout.strip()


def _resize_idle():
    s = sh("SHOW STATUS LIKE 'Innodb_buffer_pool_resize_status';", db=None)
    payload = s.split("\t", 1)[1] if "\t" in s else ""
    return payload == "" or "Completed" in payload


def set_pool(size, timeout=600):
    for _ in range(timeout):
        if _resize_idle():
            break
        time.sleep(1)
    if int(sh("SELECT @@innodb_buffer_pool_size;", db=None)) == size:
        return
    sh(f"SET GLOBAL innodb_buffer_pool_size = {size};", db=None)
    for _ in range(timeout):
        if int(sh("SELECT @@innodb_buffer_pool_size;", db=None)) == size and _resize_idle():
            return
        time.sleep(1)
    raise SystemExit(f"buffer pool resize to {size} did not complete")


def quiesce(limit=4000, timeout=300):
    q = ("SELECT VARIABLE_VALUE FROM performance_schema.global_status "
         "WHERE VARIABLE_NAME='Innodb_buffer_pool_pages_dirty';")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if int(sh(q, db=None) or 0) <= limit:
            return
        time.sleep(0.5)


# ---- the design as tables ---------------------------------------------------
def tables_of(D):
    """Each subschema as a table: its columns, its keys, and the index on each key."""
    out = {}
    for XA, keys, _ in D:
        cols = S.nm(XA)
        ks = [S.nm(k) for k in sorted(keys, key=lambda k: (len(k), sorted(k)))]
        out[cols] = ks
    return out


def build(inst, D, rel):
    """Materialise one design from the current relation, with every key enforced.

    The schema is emptied first rather than only the tables this design needs.  Two designs
    share four subschemata and part on two, so dropping by name alone leaves the other
    design's two tables behind, and what the server reports as occupied then covers both.
    """
    tabs = tables_of(D)
    sh(f"CREATE DATABASE IF NOT EXISTS {DB};", db=None)
    old = sh("SELECT table_name FROM information_schema.tables "
             f"WHERE table_schema='{DB}';").split()
    stmts = [f"DROP TABLE IF EXISTS {t};"
             for t in sorted(set(old) | set(tabs) | {REST})]
    for t, ks in tabs.items():
        defs = [f"{a} BIGINT NOT NULL" for a in t]
        defs.append("PRIMARY KEY(" + ",".join(ks[0]) + ")")
        defs += [f"UNIQUE KEY u{i}({','.join(k)})" for i, k in enumerate(ks[1:])]
        stmts.append(f"CREATE TABLE {t}({', '.join(defs)}) ENGINE=InnoDB;")
    stmts.append(f"CREATE TABLE {REST}(" + ", ".join(f"{a} BIGINT" for a in S.ATTRS)
                 + ", PRIMARY KEY(" + ",".join(sorted("bcd")) + ")) ENGINE=InnoDB;")
    sh("\n".join(stmts))
    for t in tabs:
        idx = [S.AID[c] for c in t]
        seen, path = set(), os.path.join(SCRATCH, f"b_{t}.csv")
        with open(path, "w", newline="") as fh:
            for tup in rel:
                v = tuple(tup[i] for i in idx)
                if v not in seen:
                    seen.add(v)
                    fh.write(",".join(map(str, v)) + "\n")
        sh(f"LOAD DATA LOCAL INFILE '{path.replace(chr(92), '/')}' INTO TABLE {t} "
           f"FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' ({','.join(t)});")
        os.remove(path)
    sh("ANALYZE TABLE " + ", ".join(tabs) + ";")
    return {t: int(sh(f"SELECT COUNT(*) FROM {t};")) for t in tabs}


# ---- the window against the state it has reached ----------------------------
def where(cols, vals):
    if len(cols) == 1:
        return f"{cols} IN ({','.join(str(v[0]) for v in vals)})"
    inner = ",".join("(" + ",".join(map(str, v)) + ")" for v in vals)
    return f"({','.join(cols)}) IN ({inner})"


class Live:
    """The statements one window turns into on each design.

    The relation and the projections each design holds are the simulator `delivery_schema` prices
    windows with, so the statements and the row counts come from one account of the state.
    Each event is planned against that state, written out, and only then committed, since a
    statement has to name the rows as the design holds them at the moment it is issued.
    """

    def __init__(self, inst, named, rel=None):
        self.run = S.Run(inst, named, rel)
        self.named = named

    def apply(self, ev):
        payload, cost = self.run.plan(ev)
        out = {k: [] for k in self.named}
        if payload is not None:
            if ev[1] == "set":
                unit = [self.run.rel[n] for n in payload]
                for k in self.named:
                    out[k] = self._set(k, S.AID[ev[2]], unit, ev[4])
            elif ev[1] == "enter":
                for k in self.named:
                    out[k] = self._enter(k, payload, ev[3], ev[4])
            else:
                for k in self.named:
                    out[k] = [(f"INSERT IGNORE INTO {REST}({','.join(S.ATTRS)}) VALUES "
                               + "(" + ",".join(map(str, payload)) + ");", 1)]
        self.run.commit(ev, payload)
        return out, cost

    def _set(self, k, i, unit, v):
        """One rewrite of attribute `i` over `unit`, as statements on design `k`.

        A subschema holding a determinant of the attribute is rewritten through it, so the
        statement names the group and the server finds its rows.  One holding only affected
        attributes is rewritten only where the update owns every tuple behind a row, and
        gains a row for each value the rewrite creates that nothing else already carries.
        """
        x, dets, out = S.INV[i], S.dets_of(i), []
        for XA, keys, _ in self.named[k]:
            if i not in XA:
                continue
            cols, idx = S.nm(XA), sorted(XA)
            sup = self.run.sup[k][XA]
            inside = [X for X in dets if X <= XA]
            if inside:
                X = min(inside, key=len)
                xc, xi = S.nm(X), sorted(X)
                vals = sorted({tuple(t[j] for j in xi) for t in unit})
                pos, want = [idx.index(j) for j in xi], set(vals)
                hit = sum(1 for r in sup if tuple(r[q] for q in pos) in want)
                out.append((f"UPDATE {cols} SET {x}={v} WHERE {where(xc, vals)};", hit))
                continue
            before = Counter(tuple(t[j] for j in idx) for t in unit)
            excl = sorted(r for r, c in before.items() if sup.get(r, 0) == c)
            made = {tuple(v if j == i else w for j, w in zip(idx, r)) for r in excl}
            after = {tuple(v if j == i else t[j] for j in idx) for t in unit}
            if excl:
                out.append((f"UPDATE {cols} SET {x}={v} WHERE {where(cols, excl)};",
                            len(excl)))
            new = sorted(r for r in after if r not in sup and r not in made)
            if new:
                vals = ",".join("(" + ",".join(map(str, r)) + ")" for r in new)
                out.append((f"INSERT IGNORE INTO {cols}({','.join(cols)}) VALUES {vals};",
                            len(new)))
        return out

    def _enter(self, k, t, sign, rem):
        out = []
        for XA, _, _ in self.named[k]:
            cols, idx = S.nm(XA), sorted(XA)
            row = tuple(t[j] for j in idx)
            have = self.run.sup[k][XA].get(row, 0)
            if sign > 0 and have == 0:
                out.append((f"INSERT IGNORE INTO {cols}({','.join(cols)}) VALUES "
                            + "(" + ",".join(map(str, row)) + ");", 1))
            elif sign < 0 and have == 1:
                out.append((f"DELETE FROM {cols} WHERE {where(cols, [row])};", 1))
        if rem:
            key = [tuple(t[S.AID[c]] for c in "bcd")]
            if sign > 0:
                out.append((f"DELETE FROM {REST} WHERE {where('bcd', key)};", 1))
            else:
                out.append((f"INSERT IGNORE INTO {REST}({','.join(S.ATTRS)}) VALUES "
                            + "(" + ",".join(map(str, t)) + ");", 1))
        return out


# ---- driving ----------------------------------------------------------------
def stream(inst, named, mix, reps, seed=0):
    """The whole window rendered for each design, with the rows each statement writes."""
    live = Live(inst, named)
    out = {k: [] for k in named}
    by = {k: {op: [0, 0, 0] for op in S.OPS} for k in named}
    for ev in S.events(inst, mix, reps, seed):
        sts, cost = live.apply(ev)
        for k in named:
            out[k] += sts[k]
            by[k][ev[0]][0] += len(sts[k])
            by[k][ev[0]][1] += sum(n for _, n in sts[k])
            by[k][ev[0]][2] += cost[k]["rows"]
    return out, by, live


def main_dry(depth=192, mix="desk", reps=1000):
    """Row counts from the simulator against the static model, with no server."""
    inst = C.inst_of(depth)
    named = C.two_designs()
    sts, by, live = stream(inst, named, S.MIXES[mix], reps)
    print(f"  {mix} window, group {inst.depth}, {inst.n:,} tuples, {reps} updates")
    print(f"    {'design':<14}{'statements':>12}{'rows':>12}{'model rows':>12}   drift")
    for k in named:
        n = sum(n for _, n in sts[k])
        m = sum(by[k][op][2] for op in S.OPS)
        print(f"    {k:<14}{len(sts[k]):>12,}{n:>12,}{m:>12,}   {n / m - 1:+7.2%}")
    print(f"\n    {'operation':<22}" + "".join(f"{k[:20]:>28}" for k in named))
    for op in S.OPS:
        print(f"    {op:<22}"
              + "".join(f"{f'{by[k][op][0]:,} stmts {by[k][op][1]:,} rows':>28}"
                        for k in named))
    return sts, by, live


def reconstruct(D):
    """The relation joined back out of one design, for comparing designs against each other."""
    return ("SELECT " + ",".join(S.ATTRS) + " FROM "
            + " NATURAL JOIN ".join(S.nm(XA) for XA, _, _ in D))


def checksums(D):
    q = reconstruct(D)
    n = int(sh(f"SELECT COUNT(*) FROM ({q}) x;"))
    c = sh("SELECT COALESCE(SUM(CRC32(CONCAT_WS(',',"
           + ",".join(S.ATTRS) + f"))),0) FROM ({q}) x;")
    return n, c


def reads(inst, D, rel, floor=0.05, cap=512):
    """What a design costs to read from, which is the side the objective does not govern.

    Four queries: the whole relation joined back, one delivery found by a key, one courier's
    history, and what the design occupies on disk.  A design that keeps an attribute under a
    key writes less when it changes and holds it in more places, so the read side is where
    that is paid for and it has to be reported next to the write side.

    Each query is timed by the difference between a batch of $2n$ executions and a batch of
    $n$, both inside one client session, with $n$ doubled until that difference is large
    enough to read.  Starting the client costs about 56 ms, more than a point lookup takes,
    so a query timed one client call at a time reports the harness rather than the design,
    and the difference of two batches cancels whatever the call itself costs.
    """
    t = rel[len(rel) // 2]
    key = " AND ".join(f"{c}={t[S.AID[c]]}" for c in "bdz")
    q = reconstruct(D)
    out = {}

    def batch(sql, n):
        t0 = time.time()
        last = sh("\n".join([sql] * n)).split()[-1]
        return time.time() - t0, last

    for name, sql in (("rebuild", f"SELECT COUNT(*) FROM ({q}) x;"),
                      ("lookup", f"SELECT COUNT(*) FROM ({q}) x WHERE {key};"),
                      ("history",
                       f"SELECT COUNT(*) FROM ({q}) x WHERE c={t[S.AID['c']]};")):
        sh(sql)
        n, gaps, last = 1, [], "0"
        while True:
            for _ in range(3):
                t1, last = batch(sql, n)
                t2, _ = batch(sql, 2 * n)
                gaps.append(t2 - t1)
            if max(gaps) >= floor or n >= cap:
                break
            n, gaps = n * 2, []
        out[name] = {"secs": sorted(gaps)[len(gaps) // 2] / n,
                     "rows": int(last), "reps": n}
    out["bytes"] = int(sh(
        "SELECT COALESCE(SUM(data_length+index_length),0) FROM information_schema.tables "
        f"WHERE table_schema='{DB}' AND table_name<>'{REST}';") or 0)
    return out


def main_reads(depth=83334):
    """The read side of each design, on the instance as built."""
    inst, named = C.inst_of(depth), C.two_designs()
    rel = list(inst.rows())
    out = {}
    set_pool(POOL_BIG)
    try:
        for k, D in named.items():
            build(inst, D, rel)
            quiesce()
            out[k] = reads(inst, D, rel)
    finally:
        set_pool(POOL_SMALL)
    print(f"  reads, group {inst.depth}, {inst.n:,} tuples")
    ks = list(out)
    print(f"    {'query':<10}" + "".join(f"{k[:22]:>22}" for k in ks) + "    ratio")
    for name in ("rebuild", "lookup", "history"):
        v = [out[k][name]["secs"] for k in ks]
        cells = [f"{out[k][name]['secs'] * 1000:,.2f} ms / {out[k][name]['rows']:,}"
                 for k in ks]
        print(f"    {name:<10}" + "".join(f"{c:>22}" for c in cells)
              + f"   {max(v) / min(v):6.2f}x")
    v = [out[k]["bytes"] for k in ks]
    print(f"    {'storage':<10}" + "".join(f"{out[k]['bytes'] / 1024:>19,.0f} KB"
                                           for k in ks)
          + f"   {max(v) / min(v):6.2f}x")
    json.dump(out, open(result("rq3_reads.json"), "w"), indent=1)
    return out


def issue(stmts, chunk=2000):
    """Send the window one chunk at a time, and return the seconds it took."""
    t0 = time.time()
    for i in range(0, len(stmts), chunk):
        sh("\n".join(s for s, _ in stmts[i:i + chunk]))
    return time.time() - t0


def main_verify(depth=24, mix="desk", reps=300):
    """Both designs carry the same window, then are joined back and compared."""
    inst = C.inst_of(depth)
    named = C.two_designs()
    sts, by, live = stream(inst, named, S.MIXES[mix], reps)
    final = [t for t in live.run.rel if t is not None]
    bad = {S.fdnm(fd): sum(1 for _ in ()) for fd in ()}
    for X, A in S.SIGMA:
        a, seen, n = next(iter(A)), {}, 0
        for t in final:
            key = tuple(t[i] for i in sorted(X))
            if seen.setdefault(key, t[a]) != t[a]:
                n += 1
        if n:
            bad[S.nm(X) + "->" + S.INV[a]] = n
    print(f"  the window leaves {len(final):,} tuples, violations "
          f"{bad or 'none'}")
    got = {}
    for k, D in named.items():
        build(inst, D, list(inst.rows()))
        issue(sts[k])
        got[k] = checksums(D)
        print(f"    {k:<14} {len(sts[k]):>6,} statements -> "
              f"{got[k][0]:>7,} tuples, checksum {got[k][1]}")
    ks = list(named)
    same = got[ks[0]] == got[ks[1]]
    print(f"  {mix} window, group {inst.depth}, {reps} updates: designs agree {same}")
    print(f"  simulator holds {len(final):,} tuples "
          f"({'matches' if len(final) == got[ks[0]][0] else 'DIFFERS from'} the server)")
    return same


def run(inst, named, mix, reps=3, ops=1000, seed=0):
    """The window timed on each design, round-robin, each design rebuilt in its own turn."""
    sts, by, live = stream(inst, named, S.MIXES[mix], ops, seed)
    out = {k: [] for k in named}
    base = list(inst.rows())
    for rep in range(reps):
        for k, D in named.items():
            counts = build(inst, D, base)
            quiesce()
            t = issue(sts[k])
            out[k].append(t)
            print(f"    rep {rep} {k:<14} {t:8.2f} s  "
                  f"{sum(counts.values()):>8,} rows built", flush=True)
    return {k: {"secs": v, "stmts": len(sts[k]),
                "rows": sum(n for _, n in sts[k]),
                "by_op": {op: by[k][op] for op in S.OPS}} for k, v in out.items()}


def one_kind(inst, named, op, reps, seed=0):
    """A window of `reps` updates of a single kind, rendered for each design."""
    return stream(inst, named, {op: 1.0}, reps, seed)


def main_ops(depths=(3, 30, 300, 3000, 30000), reps=3,
             out=result("rq1_operations.json")):
    """What one update of each kind costs on each design, as the group it ranges over grows.

    The window studies price everything a maintenance period writes.  This one isolates a
    single update instead, which is what Prop. amplification bounds, and grows the group the
    hot rule ranges over while the number of groups stays fixed.  Designs are rebuilt and
    timed round-robin inside each repetition, as everywhere else here.
    """
    kinds = ("reassign", "swap", "completion_conflict", "completion_clean", "insert_total")
    res = []
    set_pool(POOL_BIG)
    try:
        for depth in depths:
            inst, named = C.inst_of(depth), C.two_designs()
            base = list(inst.rows())
            n = 200 if inst.depth <= 30 else 20
            drawn = {op: one_kind(inst, named, op, n)[0] for op in kinds}
            print(f"  group {inst.depth}, {inst.n:,} tuples, {n} updates of each kind",
                  flush=True)
            secs = {op: {k: [] for k in named} for op in kinds}
            for rep in range(reps):
                for k, D in named.items():
                    for op in kinds:
                        build(inst, D, base)
                        quiesce()
                        secs[op][k].append(issue(drawn[op][k]) / n)
                    print(f"    rep {rep} {k:<14} "
                          + "  ".join(f"{op[:6]} {secs[op][k][-1] * 1000:7.2f} ms"
                                      for op in kinds), flush=True)
            for op in kinds:
                r = {k: sorted(v)[len(v) // 2] for k, v in secs[op].items()}
                res.append({"depth": inst.depth, "n": inst.n, "op": op,
                            "rows": {k: sum(x for _, x in drawn[op][k]) / n
                                     for k in named},
                            "secs": r,
                            "all": {k: v for k, v in secs[op].items()}})
            json.dump(res, open(out, "w"), indent=1)
    finally:
        set_pool(POOL_SMALL)
    print(f"\n  written {out}: {len(res)} rows\n")
    ks = sorted({k for x in res for k in x["secs"]})
    print(f"  {'group':>6}  {'operation':<20}"
          + "".join(f"{k[:22]:>26}" for k in ks) + "    ratio")
    for x in res:
        v = [x["secs"][k] for k in ks]
        cells = [f"{x['secs'][k] * 1000:,.2f} ms / {x['rows'][k]:,.0f} rows" for k in ks]
        print(f"  {x['depth']:>6}  {x['op']:<20}"
              + "".join(f"{c:>26}" for c in cells)
              + f"   {max(v) / min(v):6.2f}x")
    return res


def main_mixed(depth=3000, ops=200, reps=3, gammas=(0.0, 0.10, 0.25, 0.50),
               out=result("rq3_mixed.json")):
    """A window of refreshes into which completions are mixed at a growing share.

    The per-operation study issues one kind at a time.  This one interleaves the hot refresh
    with scope entries, which every design pays alike, and asks how much of the separation
    survives as the entries take over the window.  The two channels draw the entering tuple
    from an all-clean or an all-conflicting pool.
    """
    inst, named = C.inst_of(depth), C.two_designs()
    base = list(inst.rows())
    res = []
    set_pool(POOL_BIG)
    try:
        for channel in ("completion_clean", "completion_conflict"):
            for g in gammas:
                mix = {"reassign": 1 - g, channel: g}
                sts, by, _ = stream(inst, named, mix, ops)
                secs = {k: [] for k in named}
                for rep in range(reps):
                    for k, D in named.items():
                        build(inst, D, base)
                        quiesce()
                        secs[k].append(issue(sts[k]))
                r = {k: sorted(v)[len(v) // 2] for k, v in secs.items()}
                res.append({"depth": inst.depth, "n": inst.n, "channel": channel,
                            "gamma": g, "secs": r,
                            "rows": {k: sum(x for _, x in sts[k]) for k in named},
                            "stmts": {k: len(sts[k]) for k in named}, "all": secs})
                print(f"  {channel:<20} gamma {g:4.0%}  "
                      + "  ".join(f"{k} {r[k]:6.2f} s / {res[-1]['rows'][k]:,} rows"
                                  for k in named), flush=True)
                json.dump(res, open(out, "w"), indent=1)
    finally:
        set_pool(POOL_SMALL)
    print(f"\n  written {out}: {len(res)} rows")
    return res


def main(tiny=False, out=result("rq7_window.json")):
    depths = (192,) if tiny else (192, 768, 3072)
    res = []
    set_pool(POOL_BIG)
    try:
        for depth in depths:
            inst = C.inst_of(depth)
            named = C.two_designs()
            for mix in S.MIXES:
                print(f"  group {inst.depth}, {inst.n:,} tuples, {mix}", flush=True)
                r = run(inst, named, mix, reps=1 if tiny else 3)
                for k, v in r.items():
                    res.append({"depth": inst.depth, "n": inst.n, "mix": mix,
                                "design": k, **v})
                json.dump(res, open(out, "w"), indent=1)
    finally:
        set_pool(POOL_SMALL)
    print(f"\n  written {out}: {len(res)} rows\n")
    ks = sorted({x["design"] for x in res})
    print(f"  {'group':>6}  {'mix':<8}" + "".join(f"{k[:22]:>24}" for k in ks) + "    ratio")
    for depth in depths:
        d = C.inst_of(depth).depth
        for mix in S.MIXES:
            r = {x["design"]: x for x in res if x["depth"] == d and x["mix"] == mix}
            if len(r) < 2:
                continue
            med = {k: sorted(r[k]["secs"])[len(r[k]["secs"]) // 2] for k in ks}
            print(f"  {d:>6}  {mix:<8}"
                  + "".join(f"{f'{med[k]:.2f} s / {r[k]['rows']:,} rows':>24}" for k in ks)
                  + f"   {max(med.values()) / min(med.values()):6.2f}x")


if __name__ == "__main__":
    if "--dry" in sys.argv:
        main_dry()
    elif "--verify" in sys.argv:
        main_verify()
    elif "--reads" in sys.argv:
        main_reads()
    elif "--ops" in sys.argv:
        main_ops()
    elif "--mixed" in sys.argv:
        main_mixed()
    else:
        main(tiny="--tiny" in sys.argv)
