"""Main operational study: run an update workload on REAL incomplete
relations, materialized under all three syntheses (3NF / SO / HA).

Per (dataset, semantics) run:
  1.  Load + calibrate the relation as in redundancy_study (mined FDs must
      hold on the data), compute the per-FD redundancy ranking.
  2.  Expert selection: the top-K atomic FDs by caused redundancy form the
      declared set Sigma_x (the data-steward protocol of the completeness-
      tailored line); keys and the data-derived heat map live on Sigma_x.
  3.  Synthesize the three designs on (R, Sigma_x); materialize each in
      MySQL: scope = fully complete rows, projected and deduplicated per
      subschema; every minimal key a UNIQUE index, every procedurally
      maintained determinant a secondary index; rows with NULLs remain
      pending outside the designs.
  4.  One workload, executed identically on every design:
        refresh     every rule of Sigma_x fires on theta(sigma) distinct
                    largest X-groups (heat = declared frequency); each firing
                    rewrites the group's RHS value wherever the rule's
                    attributes are materialized; inverse-restored, medians
                    over repetitions.  Only rules that EVERY design embeds are
                    fired, so the statement is routed the same way everywhere.
                    Each firing carries its own fresh RHS value, so a group
                    rewrite cannot collide with a hosting key and no group is
                    excluded; `wl_key_collision` counts the groups the earlier
                    blanket filter would have dropped, which were exactly the
                    groups some design stores in a single row.
        completion  pending rows total on some rule's LHS and NULL on its
                    RHS realize newcomer-wins repairs of their receiving
                    groups; timed once (state-changing, runs last).
        queries     fixed-answer reconstruction: reassemble the scope from
                    ALL subschemata (lossless by the synthesis theorems);
                    cardinality + order-independent checksum asserted equal
                    across designs; designs beyond MySQL's 61-table join cap
                    run as an iterative join through scratch tables.
                    Plus hot-rule lookups.
Per-repetition raw timings are recorded next to every median.
Results -> real_workload.json (incremental).
Usage: python real_workload.py [--only ds:sem] [--topk K]
"""
import sys, os, json, time, argparse, random
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as B
import redundancy_study as rs
import pymysql

OUT = os.path.join(HERE, "real_workload.json")
DB = "real_workload"
# (dataset:semantics, heat channel): data = redundancy-derived declaration,
# graded = the RQ2 skewed declaration (p=0.5, seed 0) as a second workload shape,
# skew = a single hot rule (sweep the ten experts, declare the first rule on
# which the objectives disagree; fall back to the reddest if none separates)
RUNS = [("hospital:nulluc", "data"), ("routes:nulluc", "data"),
        ("ncvoter:nulluc", "data"), ("ncvoter:nulluc", "graded"),
        ("ncvoter:nulluc", "skew")]
TOPK = 10
FULL_CAP = 1500                      # declare the whole closure below this size
T_C, T_Q, REPS, Q1R = 200, 1000, 15, 3
MODES = ["3nf", "so", "ha"]


def connect(db=DB):
    return config.connect(db, autocommit=True)


def settle(cur, limit=100, timeout=300):
    """Drain InnoDB dirty pages so every timed batch starts from the same
    quiesced state, instead of inheriting the checkpoint pressure of the
    preceding build or batch."""
    end = time.time() + timeout
    while time.time() < end:
        cur.execute("SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_dirty'")
        if int(cur.fetchone()[1]) <= limit:
            break
        time.sleep(5)


# ---------- expert selection -------------------------------------------------
CACHE = os.path.join(HERE, "expert_cache.json")


def choose_E(data, m, frac=1 / 3, min_cols=3):
    """Completeness requirement: add columns by ascending NULL rate while the
    E-complete share of the data stays above `frac`."""
    nulls = [sum(1 for r in data if r[c] is None) for c in range(m)]
    order = sorted(range(m), key=lambda c: nulls[c])
    E, mask = [], [True] * len(data)
    for c in order:
        nm = [ok and data[i][c] is not None for i, ok in enumerate(mask)]
        if len(E) >= min_cols and sum(nm) < frac * len(data):
            continue
        E.append(c)
        mask = nm
    return sorted(E)


def expert_sigma(json_path, data, sem, topk, E, sample=100_000, tag=None):
    R, sigma, _ = B.load(json_path)
    Eset = frozenset(E)
    sigma = [fd for fd in sigma if (fd[0] | fd[1]) <= Eset]     # the reduct's closure
    atomic = [(tuple(sorted(l)), next(iter(r))) for l, r in sigma]
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    ckey = f"{tag}|E={','.join(map(str, E))}"
    if tag and ckey in cache:
        fd_red = {(tuple(json.loads(k)[0]), json.loads(k)[1]): v
                  for k, v in cache[ckey].items()}
    else:
        base = data if len(data) <= sample else random.Random(5).sample(data, sample)
        _, _, fd_red = rs.count_redundancy(base, atomic, sem)
        if tag:
            cache[ckey] = {json.dumps([list(k[0]), k[1]]): v for k, v in fd_red.items()}
            json.dump(cache, open(CACHE, "w"))
    key = lambda fd: (tuple(sorted(fd[0])), next(iter(fd[1])))
    ranked = sorted(sigma, key=lambda fd: -fd_red[key(fd)])
    # expert selection only where the reduct is too large to declare whole
    sx = sigma if len(sigma) <= FULL_CAP else ranked[:topk]
    red = {fd: fd_red[key(fd)] for fd in sx}
    rmax = max(red.values()) or 1
    theta = {fd: max(1, -(-10 * r // rmax)) for fd, r in red.items()}
    keys = B.minimal_keys(Eset, sx)
    return Eset, sx, keys, theta, red


# ---------- materialization --------------------------------------------------
def col_lens(data, m):
    L = [1] * m
    for r in data:
        for c, v in enumerate(r):
            if v is not None and len(v) > L[c]:
                L[c] = len(v)
    return L


def materialize(cur, tag, D, hot, scope, lens):
    meta = []
    for i, (XA, proj) in enumerate(D):
        cols = sorted(XA)
        tbl = f"{tag}_s{i}"
        mkeys = B.minimal_keys(XA, proj)
        F = B.schema_nonkey(XA, proj, mkeys, hot)
        defs = [f"c{a} VARCHAR({min(2000, lens[a] + 8)}) NOT NULL" for a in cols]
        idx_ok = lambda ats: all(lens[a] <= 190 for a in ats)   # InnoDB key-length cap
        for j, k in enumerate(sorted((k for k in mkeys if k and idx_ok(k)), key=sorted)):
            defs.append(f"UNIQUE KEY u{j}({','.join('c%d' % a for a in sorted(k))})")
        for j, X in enumerate(sorted({tuple(sorted(f[0])) for f in F if f[0] and idx_ok(f[0])})):
            defs.append(f"KEY d{j}({','.join('c%d' % a for a in X)})")
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
        cur.execute(f"CREATE TABLE {tbl}({', '.join(defs)}) ENGINE=InnoDB")
        rows = list({tuple(r[c] for c in cols) for r in scope})
        ph = "(" + ",".join(["%s"] * len(cols)) + ")"
        for b in range(0, len(rows), 5000):
            cur.executemany(f"INSERT INTO {tbl} VALUES {ph}", rows[b:b + 5000])
        meta.append({"tbl": tbl, "cols": cols, "keys": mkeys, "F": F, "nrows": len(rows)})
    return meta


def hosts_of(meta, fd):
    X, A = set(fd[0]), next(iter(fd[1]))
    out = []
    for m in meta:
        if X <= set(m["cols"]) and A in m["cols"]:
            nonkey = any(set(f[0]) == X and next(iter(f[1])) == A for f in m["F"])
            out.append((m, nonkey))
    return out


# ---------- workload ---------------------------------------------------------
def refresh_batch(cur, meta, wl, reps=None):
    reps = REPS if reps is None else reps
    stmts, inv = [], []
    for fd, xv, old, nv in wl:
        X, A = sorted(fd[0]), next(iter(fd[1]))
        cond = " AND ".join(f"c{a}=%s" for a in X)
        for m, _ in hosts_of(meta, fd):
            stmts.append((f"UPDATE {m['tbl']} SET c{A}=%s WHERE {cond}", (nv, *xv)))
            inv.append((f"UPDATE {m['tbl']} SET c{A}=%s WHERE {cond}", (old, *xv)))
    times = []
    for rep in range(reps + 1 if reps > 1 else 1):
        t0 = time.perf_counter()
        for q, p in stmts:
            cur.execute(q, p)
        dt = time.perf_counter() - t0
        for q, p in inv:
            cur.execute(q, p)
        if rep or reps == 1:
            times.append(dt)
    return round(1000 * st.median(times), 1), [round(1000 * t, 1) for t in times]


def completion_batch(cur, meta, pend):
    """One event completes one pending row: newcomer-wins repairs on every
    receiving group that already exists in the scope, then the scope-entry
    insert of the completed row into every subschema."""
    t0 = time.perf_counter()
    for rules, nv, full in pend:
        for fd, xv, joins in rules:
            if not joins:
                continue
            X, A = sorted(fd[0]), next(iter(fd[1]))
            cond = " AND ".join(f"c{a}=%s" for a in X)
            for m, _ in hosts_of(meta, fd):
                cur.execute(f"UPDATE {m['tbl']} SET c{A}=%s WHERE {cond}", (nv, *xv))
        for m in meta:
            vals = tuple(full[c] for c in m["cols"])
            ph = ",".join(["%s"] * len(vals))
            cur.execute(f"INSERT IGNORE INTO {m['tbl']} VALUES ({ph})", vals)
    return round(1000 * (time.perf_counter() - t0), 1)


def join_order(meta, start_tbl=None):
    """Connectivity-greedy order over ALL subschemata (max shared attributes
    with the already-placed set).  A subschema sharing no attribute joins as
    a Cartesian product, admissible only when it stores a single tuple (a
    constant projection, from an empty-LHS rule), which keeps the
    reconstruction exact; otherwise the design is not join-connected."""
    idx0 = next((i for i, m in enumerate(meta) if m["tbl"] == start_tbl), 0)
    order, T = [idx0], set(meta[idx0]["cols"])
    left = set(range(len(meta))) - {idx0}
    while left:
        nxt = max(left, key=lambda i: (len(set(meta[i]["cols"]) & T), -i))
        if not set(meta[nxt]["cols"]) & T and meta[nxt]["nrows"] != 1:
            return None, None
        order.append(nxt)
        left.remove(nxt)
        T |= set(meta[nxt]["cols"])
    return order, T


def query_pass(cur, meta, ecols, nscope, start_tbl=None):
    """Fixed-answer reconstruction query: reassemble the scope from ALL
    subschemata (the synthesis guarantees the full join is lossless), and
    return its cardinality plus an order-independent checksum over the E
    columns; both are design-independent and asserted equal across designs.
    Designs within MySQL's 61-table join cap run as one SELECT; larger ones
    run as an iterative join through scratch tables, with a growth guard
    against runaway intermediates."""
    order, T = join_order(meta, start_tbl)
    if order is None:
        print("      q1 dnf: design not join-connected", flush=True)
        return None, None, len(meta), []
    seq = [meta[i] for i in order]
    crc = ("BIT_XOR(CRC32(CONCAT_WS(CHAR(31),{})))", ecols)

    def run_single():
        frm = [f"{seq[0]['tbl']} t0"]
        for i, m in enumerate(seq[1:], 1):
            conds = []
            for j in range(i):
                shared = set(seq[j]["cols"]) & set(m["cols"])
                conds += [f"t{i}.c{a}=t{j}.c{a}" for a in sorted(shared)]
            frm.append(f"JOIN {m['tbl']} t{i} ON " + " AND ".join(conds)
                       if conds else f"CROSS JOIN {m['tbl']} t{i}")
        src = {a: next(i for i, m in enumerate(seq) if a in m["cols"]) for a in ecols}
        cs = crc[0].format(", ".join(f"t{src[a]}.c{a}" for a in ecols))
        q = f"SELECT COUNT(*), {cs} FROM " + " ".join(frm)
        cur.execute(q)
        return cur.fetchone()

    def run_iterative():
        cur.execute("DROP TABLE IF EXISTS q1w_a, q1w_b")
        cols0 = seq[0]["cols"]
        cur.execute(f"CREATE TABLE q1w_a AS SELECT {', '.join('c%d' % a for a in cols0)}"
                    f" FROM {seq[0]['tbl']}")
        acc, have = "q1w_a", set(cols0)
        for m in seq[1:]:
            shared = sorted(have & set(m["cols"]))
            new = [a for a in m["cols"] if a not in have]
            nxt = "q1w_b" if acc == "q1w_a" else "q1w_a"
            sel = [f"t.c{a}" for a in sorted(have)] + [f"s.c{a} AS c{a}" for a in new]
            jn = (f"JOIN {m['tbl']} s ON " +
                  " AND ".join(f"t.c{a}=s.c{a}" for a in shared)
                  if shared else f"CROSS JOIN {m['tbl']} s")
            cur.execute(f"DROP TABLE IF EXISTS {nxt}")
            cur.execute(f"CREATE TABLE {nxt} AS SELECT {', '.join(sel)}"
                        f" FROM {acc} t {jn}")
            cur.execute(f"DROP TABLE {acc}")
            acc, have = nxt, have | set(new)
            cur.execute(f"SELECT COUNT(*) FROM {acc}")
            if cur.fetchone()[0] > max(5 * max(nscope, 1), 100_000):
                cur.execute(f"DROP TABLE IF EXISTS {acc}")
                raise RuntimeError("intermediate blow-up")
        cs = crc[0].format(", ".join(f"c{a}" for a in ecols))
        cur.execute(f"SELECT COUNT(*), {cs} FROM {acc}")
        row = cur.fetchone()
        cur.execute(f"DROP TABLE IF EXISTS {acc}")
        return row

    runner = run_single if len(seq) <= 55 else run_iterative
    anchors, times = set(), []
    try:
        for rep in range(Q1R + 1):
            t0 = time.perf_counter()
            n, ck = runner()
            anchors.add((n, int(ck or 0)))
            if rep:
                times.append(time.perf_counter() - t0)
    except (pymysql.err.MySQLError, RuntimeError) as e:
        print(f"      q1 dnf: {e.args[0] if e.args else e}", flush=True)
        return None, None, len(seq), []
    assert len(anchors) == 1
    n, ck = anchors.pop()
    return [n, ck], round(st.median(times), 3), len(seq), [round(t, 3) for t in times]


def hot_lookups(cur, meta, fd, probes):
    X, A = sorted(fd[0]), next(iter(fd[1]))
    host = hosts_of(meta, fd)[0][0]
    cond = " AND ".join(f"c{a}=%s" for a in X)
    q = f"SELECT c{A} FROM {host['tbl']} WHERE {cond} LIMIT 1"
    times = []
    for rep in range(REPS + 1):
        t0 = time.perf_counter()
        for p in probes:
            cur.execute(q, p)
            cur.fetchall()
        if rep:
            times.append(time.perf_counter() - t0)
    per = [round(1000 * t / len(probes), 4) for t in times]
    return round(1000 * st.median(times) / len(probes), 4), per


# ---------- per-run driver ---------------------------------------------------
def run_one(ds, sem, json_path, topk, channel="data"):
    rnd = random.Random(11)
    with open(json_path, encoding="utf-8") as fh:
        dj = json.load(fh)
    names = rs.mysql_variant(rs.TABLES[ds])
    want = f"{rs.TABLES[ds]}({sem})"
    tbl = want if want in names else rs.TABLES[ds]
    rows, _ = rs.load_mysql(tbl)
    mapping, _ = rs.calibrate(rows, dj["R"], dj["fds"], sem)
    if mapping is None:
        return {"skip": "no calibration"}
    data = [tuple(r[c] for c in mapping) for r in rows]
    m = dj["R"]

    E = choose_E(data, m)
    R, sx, keys, theta, red = expert_sigma(json_path, data, sem, topk, E, tag=f"{ds}:{sem}")
    prep = B.prepare(sx)
    skew_rule = None
    if channel == "graded":
        theta = B.levels(sx, 0.5, 0)
    elif channel == "skew":
        ranked = sorted(sx, key=lambda fd: -red[fd])
        for fd0 in ranked[:topk]:
            th = {fd: (10 if fd is fd0 else 1) for fd in sx}
            hs = {md: B.decomp_metrics(B.synthesize(R, sx, keys, md, hot=th, prep=prep),
                                       th)["hmax"] for md in ("so", "ha")}
            if hs["ha"] < hs["so"]:
                skew_rule = fd0
                break
        skew_rule = skew_rule or ranked[0]
        theta = {fd: (10 if fd is skew_rule else 1) for fd in sx}
        print(f"   skew hot rule: {sorted(skew_rule[0])}->{next(iter(skew_rule[1]))}", flush=True)
    designs = {mode: B.synthesize(R, sx, keys, mode, hot=theta, prep=prep) for mode in MODES}

    # rules safe for group rewrites: RHS in no key of any hosting subschema of any design
    def hosted_everywhere(fd):
        X, A = set(fd[0]), next(iter(fd[1]))
        return all(any(X <= XA and A in XA for XA, _ in D) for D in designs.values())
    safe = [fd for fd in sx if fd[0] and hosted_everywhere(fd)]

    # keys that contain a rule's RHS, per hosting subschema, for the group check
    akeys = {}
    for fd in safe:
        X, A = set(fd[0]), next(iter(fd[1]))
        ks = []
        for D in designs.values():
            for XA, proj in D:
                if X <= XA and A in XA:
                    ks += [sorted(k - {A}) for k in B.minimal_keys(XA, proj) if A in k]
        akeys[fd] = ks

    def group_safe(fd, rows_g):
        """A group rewrite to one value collides iff two group rows agree on
        some hosting key minus the RHS; keep only collision-free groups."""
        for Krest in akeys[fd]:
            seen = set()
            for r in rows_g:
                t = tuple(r[c] for c in Krest)
                if t in seen:
                    return False
                seen.add(t)
        return True

    scope = [r for r in data if all(r[a] is not None for a in R)]
    grp, wl, pend = {}, [], []
    n_unsafe = 0
    for fd in safe:
        X, A = sorted(fd[0]), next(iter(fd[1]))
        g = defaultdict(list)
        for r in scope:
            g[tuple(r[a] for a in X)].append(r)
        grp[fd] = g
        big = sorted(g.items(), key=lambda kv: -len(kv[1]))
        took = 0
        for xv, rows_g in big:
            if took >= theta[fd]:
                break
            # A refresh carries a fresh RHS value of its own, so rewriting a
            # whole group can never collide with a hosting key: the group's rows
            # already agree on the RHS (X->A holds on the scope), so two of them
            # that agree on a key minus the RHS are one stored row, and rows
            # outside the group keep an RHS value distinct from the fresh one.
            # group_safe is needed only on the completion path below, where all
            # rules of one completing row share that row's single new value.
            # Applying it here dropped exactly the groups some design stores in
            # one row, i.e. the groups on which the designs differ.
            n_unsafe += not group_safe(fd, rows_g)
            wl.append((fd, xv, rows_g[0][A], f"z{len(wl)}"))
            took += 1
    # completion events: every pending row one value short of E-completeness;
    # rules whose receiving group already exists in the scope add a
    # newcomer-wins repair, the rest is the plain scope-entry insert
    rhs_rules = defaultdict(list)
    for fd in safe:
        rhs_rules[next(iter(fd[1]))].append(fd)
    for r in data:
        gap = [a for a in R if r[a] is None]
        if len(gap) != 1:
            continue
        A = gap[0]
        rules, ok = [], True
        for fd in rhs_rules[A]:
            xv = tuple(r[a] for a in sorted(fd[0]))
            joins = xv in grp[fd]
            if joins and not group_safe(fd, grp[fd][xv]):
                ok = False                 # the rewrite would collide with a key
                break
            rules.append((fd, xv, joins))
        if not ok:
            continue
        nv = "zc%d" % len(pend)
        full = tuple(nv if c == A else r[c] for c in range(m))
        pend.append((rules, nv, full))
    n_join = sum(1 for rules, _, _ in pend if any(j for _, _, j in rules))
    print(f"   E={len(R)}c scope={len(scope)} safe={len(safe)} wl={len(wl)} "
          f"(of which {n_unsafe} the old key-collision filter would have dropped) "
          f"completions={len(pend)} (joining an existing group: {n_join})", flush=True)
    rnd.shuffle(wl)
    rnd.shuffle(pend)
    pend = pend[:T_C]
    n_join = sum(1 for rules, _, _ in pend if any(j for _, _, j in rules))
    hotq = max(safe, key=lambda fd: (theta[fd], red[fd])) if safe else None
    probes = [rnd.choice(list(grp[hotq]))
              for _ in range(min(T_Q, len(grp[hotq])))] if hotq else []

    lens = col_lens(data, m)
    admin = config.connect(autocommit=True)
    admin.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {DB}")
    admin.close()
    conn = connect()
    cur = conn.cursor()

    res = {"n": len(data), "E_cols": len(R), "scope": len(scope), "sigma_x": len(sx),
           "safe_rules": len(safe), "wl_ops": len(wl), "wl_key_collision": n_unsafe,
           "completions": len(pend), "compl_join": n_join, "keys": len(keys),
           "hot_fd": f"{sorted(hotq[0])}->{next(iter(hotq[1]))}" if hotq else None,
           "skew_rule": f"{sorted(skew_rule[0])}->{next(iter(skew_rule[1]))}" if skew_rule else None,
           "designs": {}}
    metas = {}
    for mode in MODES:
        tag = f"{ds[:6]}_{sem[-2:]}_{channel[:2]}_{mode[:4]}"
        D = designs[mode]
        met = B.decomp_metrics(D, theta)
        t0 = time.perf_counter()
        meta = materialize(cur, tag, D, theta, scope, lens)
        metas[mode] = meta
        t_build = time.perf_counter() - t0
        nk = sum(1 for fd in safe for _, nonkey in hosts_of(meta, fd) if nonkey)
        settle(cur)
        r_ms, r_reps = refresh_batch(cur, meta, wl)
        start = hosts_of(meta, hotq)[0][0]["tbl"] if hotq and hosts_of(meta, hotq) else None
        anchor, q1, q1n, q1_reps = query_pass(cur, meta, sorted(R), len(scope),
                                              start_tbl=start)
        q2, q2_reps = hot_lookups(cur, meta, hotq, probes) if hotq and probes else (None, [])
        settle(cur)
        c_ms = completion_batch(cur, meta, pend)
        cur.execute("SELECT SUM(data_length+index_length) FROM information_schema.tables"
                    " WHERE table_schema=%s AND table_name LIKE %s", (DB, tag + "%"))
        mb = round(float(cur.fetchone()[0] or 0) / 2**20, 1)
        res["designs"][mode] = {
            "size": len(D), "hmax": met["hmax"], "nonkey_hosts": nk,
            "build_s": round(t_build, 1), "refresh_ms": r_ms, "refresh_reps": r_reps,
            "completion_ms": c_ms, "q1_rows": anchor, "q1_s": q1, "q1_tables": q1n,
            "q1_reps": q1_reps, "q2_ms": q2, "q2_reps": q2_reps, "storage_mb": mb}
        print(f"   {mode:9s} size={len(D):3d} hmax={met['hmax']:5.1f} nk={nk:2d} "
              f"refresh={r_ms:9.1f}ms compl={c_ms:9.1f}ms "
              f"q1={q1 if q1 is not None else 'dnf'}({q1n}t) "
              f"q2={q2 if q2 is not None else -1:7.4f}ms rows={anchor} {mb}MB", flush=True)
    # Interleaved refresh pass: the per-mode loop above builds and times the
    # designs in a fixed order, which on routes -- where all three synthesizers
    # emit the SAME design -- still separates them by several percent.  That is
    # a build-position artifact, so we re-time the refresh channel round-robin
    # over the already-materialized designs, one pass per design per round, with
    # the order rotated.  Same statements, same state; only the schedule changes.
    settle(cur)
    inter = {m: [] for m in MODES}
    for rnd_i in range(REPS + 1):
        order = MODES[rnd_i % len(MODES):] + MODES[:rnd_i % len(MODES)]
        for mode in order:
            ms, _ = refresh_batch(cur, metas[mode], wl, reps=1)
            if rnd_i:
                inter[mode].append(ms)
    for mode in MODES:
        v = inter[mode]
        res["designs"][mode]["refresh_il_ms"] = round(st.median(v), 1)
        res["designs"][mode]["refresh_il_reps"] = v
    print("   interleaved refresh: " + "  ".join(
        f"{m[:4]}={st.median(inter[m]):.1f}ms" for m in MODES), flush=True)

    anchors = {m: d.get("q1_rows") for m, d in res["designs"].items()}
    vals = {tuple(v) for v in anchors.values() if v is not None}
    res["q1_match"] = len(vals) <= 1
    if not res["q1_match"]:
        print(f"   !! q1 anchor MISMATCH across designs: {anchors}", flush=True)
    conn.close()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--topk", type=int, default=TOPK)
    args = ap.parse_args()
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for tag, channel in RUNS:
        jkey = tag if channel == "data" else f"{tag}@{channel}"
        if args.only and args.only != jkey:
            continue
        if jkey in out and "skip" not in out[jkey]:
            print("done already:", jkey, flush=True)
            continue
        ds, sem = tag.rsplit(":", 1)
        path = os.path.join(rs.FD_BASE, rs.SEMS[sem], "FD", ds + ".json")
        print(f"== {jkey}", flush=True)
        t0 = time.perf_counter()
        try:
            res = run_one(ds, sem, path, args.topk, channel)
        except Exception as e:
            import traceback; traceback.print_exc()
            res = {"skip": f"error: {e}"}
        out[jkey] = res
        json.dump(out, open(OUT, "w"), indent=1, default=float)
        print(f"   ({time.perf_counter()-t0:.1f}s)", flush=True)
    print("wrote real_workload.json", flush=True)


if __name__ == "__main__":
    main()
