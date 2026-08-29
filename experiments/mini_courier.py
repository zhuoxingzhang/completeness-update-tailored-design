"""Courier mini-study: refresh AND completion costs on the two E-3NF designs.

Schema R = {o,c,s,z,t,p} (order, courier, status, zone, timeslot, phone).
Input eFDs reduce (design scope E = R) to the 12-FD atomic closure verified in
courier_example.py.  The two lossless, dependency-preserving E-3NF designs:

  D_IC (structure-optimal) = oszt, oct,  ocsz, op    hot sz->c NON-KEY in ocsz (k rows/group)
  D_US (hotness-optimal)   = oszt, csz,  ocst, op    hot sz->c the KEY of csz  (1 row/group)

Both designs additionally carry the shared remainder table `rest` (full width,
p nullable) hosting the tuples outside the scope r^E (here: p IS NULL).

MEASUREMENTS (occurrence accounting: every operation runs on
its home subschemata only, no cross-subschema propagation):
  M1 refresh   the hot mode sz->c at Low/Med/High condition coverage, on ocsz
               (non-key, rewrites every redundant copy) vs csz (key, 1 row);
               plus all cold modes once at 1% for whole-workload totals.
  M2 completion  a batch of m pending tuples (p IS NULL, one per (s,z) group)
               gets p filled: the tuple ENTERS the scope = insert its projections
               into the design's subschemata + delete from rest, maintaining the
               hot eFD on entry.  Two pools:
                 clean     entering c agrees with the group's courier: pure
                           scope-entry cost (expected ~parity across designs);
                 conflict  entering c disagrees; newcomer-wins repair (the
                           TODS'21 Maggie pattern): D_IC updates all k
                           redundant copies, D_US updates one key row.
Timing: in-server NOW(6) around the forward statements, untimed exact inverse
restores state; quiesce dirty pages before each rep; median over reps.
Data: Armstrong relation for the courier sigma (core rows + bulk with G=100
(s,z)-groups fixed, so hot redundancy k = N/G grows with N).

Run:  python mini_courier.py --check    # Armstrong + modes, no MySQL
      python mini_courier.py --tiny     # N=20k smoke test, keeps DB
      python mini_courier.py            # N in {100k, 1M} -> mini_courier.json
"""
import subprocess, os, sys, json, time, random, itertools
import statistics as st

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import synthesis as bl

DB = "mini_courier"
SCRATCH = os.environ.get("MINI_SCRATCH") or os.path.join(
    config.scratch_dir(), "mini_courier")
os.makedirs(SCRATCH, exist_ok=True)

ATTRS = "ocsztp"
AID = {a: i for i, a in enumerate(ATTRS)}
INV = {i: a for a, i in AID.items()}
SIGMA_S = [("osz", "t"), ("ost", "z"), ("ocs", "z"), ("sz", "c"),
           ("ocs", "t"), ("ct", "o"), ("ot", "c"), ("o", "p")]
SCHEMA = {"oszt": "oszt", "oct": "oct", "ocsz": "ocsz", "op": "op",
          "csz": "csz", "ocst": "ocst"}
D_IC = ("oszt", "oct", "ocsz", "op")
D_US = ("oszt", "csz", "ocst", "op")
COMPL = {"d_ic": ("ocsz", "oct"), "d_us": ("csz", "ocst")}   # design-specific subschemata
HOT = ("sz", "c")

N_STATUS, N_ZONE, N_COURIER = 10, 10, 20
G = N_STATUS * N_ZONE
BASE = 10 ** 8
STEP = 10 ** 12
SCALES = [100_000, 1_000_000]
HOT_FREQ = [("Low", 0.1), ("Med", 0.5), ("High", 1.0)]
COLD_FRAC = 0.01
M_PEND = 50                                      # completions per pool (1 per group)
POOL_BIG = 8 * 1024 ** 3
POOL_SMALL = 128 * 1024 ** 2


def _S(s):
    return frozenset(AID[c] for c in s)


def _name(X, a):
    return "".join(sorted((INV[i] for i in X), key=ATTRS.index)) + "->" + INV[a]


def atomic_closure():
    sigma = [(_S(l), _S(r)) for l, r in SIGMA_S]
    atoms = set()
    alla = sorted(AID.values())
    for r in range(1, len(alla)):
        for L in itertools.combinations(alla, r):
            Lf = frozenset(L)
            cl = bl.closure(Lf, sigma)
            for a in cl - Lf:
                if not any(a in bl.closure(frozenset(sub), sigma)
                           for sub in itertools.combinations(L, r - 1)):
                    atoms.add((Lf, frozenset({a})))
    return list(atoms)


ATOM = atomic_closure()


def schema_modes(tbl):
    XA = _S(SCHEMA[tbl])
    proj = bl.projection(ATOM, XA)
    keys = bl.minimal_keys(XA, proj)
    nonkey = bl.mixed_nonkey_fds(XA, proj, keys)
    modes = {}
    for K in keys:
        for a in XA - K:
            modes.setdefault((K, a), True)
    for X, rhs in nonkey:
        modes[(X, next(iter(rhs)))] = False
    return keys, [(X, a, modes[(X, a)]) for (X, a) in modes]


def is_hot(X, a):
    return X == _S(HOT[0]) and a == AID[HOT[1]]


def order_cols(cols):
    return sorted(cols, key=lambda i: (INV[i] not in "sz", INV[i]))


def schema_indexes(tbl):
    keys, modes = schema_modes(tbl)
    key_idx = [order_cols(K) for K in keys]
    # PK: prefer a key containing the whole hot condition {s,z}, else s/z-leading, else first
    hotset = _S(HOT[0])
    pk = next((k for k in key_idx if hotset <= set(k)),
              next((k for k in key_idx if INV[k[0]] in "sz"), key_idx[0]))
    uniques = [k for k in key_idx if k != pk]
    secondary = []
    for X, a, isk in modes:
        if isk:
            continue
        xo = order_cols(X)
        if not any(idx[:len(xo)] == xo for idx in key_idx + secondary):
            secondary.append(xo)
    return pk, uniques, secondary


# ---- data -------------------------------------------------------------------
def attr_val(a, e, j):
    return {"o": e, "c": j % N_COURIER, "s": j // N_ZONE, "z": j % N_ZONE,
            "t": e * G + j, "p": 700_000 + e}[a]


def bulk_rows(n):
    k = n // G
    for e in range(k):
        for j in range(G):
            yield tuple(attr_val(a, e, j) for a in ATTRS)


def maximal_sets():
    sigma = [(_S(l), _S(r)) for l, r in SIGMA_S]
    gen = set()
    for a in AID.values():
        rest = [x for x in AID.values() if x != a]
        cands = [frozenset(c) for r in range(len(rest) + 1)
                 for c in itertools.combinations(rest, r)
                 if a not in bl.closure(frozenset(c), sigma)]
        gen.update(X for X in cands if not any(X < Y for Y in cands))
    return sorted(gen, key=lambda x: (-len(x), sorted(x)))


def core_rows():
    fresh = itertools.count(BASE + 1)
    rows = [{i: BASE for i in AID.values()}]
    for X in maximal_sets():
        rows.append({i: (BASE if i in X else next(fresh)) for i in AID.values()})
    return [tuple(r[AID[a]] for a in ATTRS) for r in rows]


def pending_rows(n):
    """2*M_PEND pending tuples (p NULL): conflict pool on groups 0..M-1 (c disagrees),
    clean pool on groups M..2M-1 (c agrees).  Fresh o and t, one tuple per group."""
    k = n // G
    out = []
    for idx in range(2 * M_PEND):
        j = idx                                   # distinct group per pending tuple
        o = k + 1000 + idx
        conflict = idx < M_PEND
        c = 900_000 + idx if conflict else attr_val("c", 0, j)
        row = {"o": o, "c": c, "s": j // N_ZONE, "z": j % N_ZONE,
               "t": o * G + j, "p_new": 800_000 + o,
               "c_old": attr_val("c", 0, j), "pool": "conflict" if conflict else "clean"}
        out.append(row)
    return out


def _violated(rows, X, a):
    seen = {}
    for tup in rows:
        kx = tuple(tup[i] for i in sorted(X))
        if seen.setdefault(kx, tup[a]) != tup[a]:
            return True
    return False


def _selfcheck():
    sigma = [(_S(l), _S(r)) for l, r in SIGMA_S]
    rows = core_rows() + list(bulk_rows(20 * G))
    for l, r in SIGMA_S:
        assert not _violated(rows, _S(l), AID[r]), f"instance breaks {l}->{r}"
    nh = nb = 0
    for r in range(1, len(ATTRS)):
        for L in itertools.combinations(AID.values(), r):
            for a in AID.values():
                if a in L:
                    continue
                if a in bl.closure(frozenset(L), sigma):
                    assert not _violated(rows, frozenset(L), a), _name(frozenset(L), a)
                    nh += 1
                else:
                    assert _violated(rows, frozenset(L), a), _name(frozenset(L), a)
                    nb += 1
    print(f"Armstrong OK: {nh} implied FDs hold, {nb} unimplied violated; |atomic closure|={len(ATOM)}")
    for t in SCHEMA:
        pk, uq, sec = schema_indexes(t)
        keys, modes = schema_modes(t)
        hot = [_name(X, a) for X, a, k in modes if is_hot(X, a)]
        key = [_name(X, a) for X, a, k in modes if k and not is_hot(X, a)]
        nk = [_name(X, a) for X, a, k in modes if not k and not is_hot(X, a)]
        idx = f"PK({''.join(INV[i] for i in pk)})"
        idx += "".join(f" UQ({''.join(INV[i] for i in u)})" for u in uq)
        idx += "".join(f" IX({''.join(INV[i] for i in s)})" for s in sec)
        print(f"  {t:5}({SCHEMA[t]}): {idx}")
        print(f"        hot={hot or '-'}  key(cold)={len(key)} modes  nonkey(cold)={nk or '-'}")


# ---- MySQL ------------------------------------------------------------------
def sh(sql, db=DB):
    args = config.client_args(extra=["--local-infile=1", "-N", "-B"])
    if db:
        args.append(db)
    r = subprocess.run(args, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"SQL ERR: {r.stderr}\nSQL: {sql[:500]}\n")
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


def build(n):
    sh(f"CREATE DATABASE IF NOT EXISTS {DB};", db=None)
    paths = {t: os.path.join(SCRATCH, f"mc_{t}.csv") for t in SCHEMA}
    fh = {t: open(p, "w", newline="") for t, p in paths.items()}
    seen = {t: set() for t in SCHEMA}
    dedup_always = {"csz", "op"}                  # few distinct rows: always dedup
    try:
        for row in itertools.chain(bulk_rows(n), core_rows()):
            for t, cols in SCHEMA.items():
                v = tuple(row[AID[a]] for a in cols)
                if t in dedup_always or row[0] >= BASE:
                    if v in seen[t]:
                        continue
                    seen[t].add(v)
                fh[t].write(",".join(map(str, v)) + "\n")
    finally:
        for f in fh.values():
            f.close()
    stmts = ["DROP TABLE IF EXISTS rest;"] + ["DROP TABLE IF EXISTS " + t + ";" for t in SCHEMA]
    for t, cols in SCHEMA.items():
        pk, uq, sec = schema_indexes(t)
        defs = [f"{a} BIGINT NOT NULL" for a in cols]
        defs.append(f"PRIMARY KEY({','.join(INV[i] for i in pk)})")
        defs += [f"UNIQUE KEY u{i}({','.join(INV[c] for c in u)})" for i, u in enumerate(uq)]
        defs += [f"KEY s{i}({','.join(INV[c] for c in s)})" for i, s in enumerate(sec)]
        stmts.append(f"CREATE TABLE {t}({', '.join(defs)}) ENGINE=InnoDB;")
    stmts.append("CREATE TABLE rest(o BIGINT NOT NULL, c BIGINT, s BIGINT, z BIGINT,"
                 " t BIGINT, p BIGINT, PRIMARY KEY(o), KEY rsz(s,z)) ENGINE=InnoDB;")
    sh("\n".join(stmts))
    for t, cols in SCHEMA.items():
        sh(f"LOAD DATA LOCAL INFILE '{paths[t].replace(chr(92), '/')}' INTO TABLE {t} "
           f"FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' ({','.join(cols)});")
        os.remove(paths[t])
    pend = pending_rows(n)
    vals = ",".join(f"({r['o']},{r['c']},{r['s']},{r['z']},{r['t']},NULL)" for r in pend)
    sh(f"INSERT INTO rest(o,c,s,z,t,p) VALUES {vals};")
    counts = {t: int(sh(f"SELECT COUNT(*) FROM {t};")) for t in list(SCHEMA) + ["rest"]}
    return counts, pend


# ---- M1: refresh ------------------------------------------------------------
def sample_conditions(X, frac, n, seed):
    xs = order_cols(X)
    k = n // G
    rnd = random.Random(seed)
    if X == _S(HOT[0]):
        js = rnd.sample(range(G), max(1, round(frac * G)))
        return xs, [tuple(attr_val(INV[i], 0, j) for i in xs) for j in js]
    total = k * G
    m = max(1, round(frac * total))
    seen, out = set(), []
    while len(out) < m and len(seen) < total:
        e, j = rnd.randrange(k), rnd.randrange(G)
        if (e, j) in seen:
            continue
        seen.add((e, j))
        out.append(tuple(attr_val(INV[i], e, j) for i in xs))
    return xs, out


def load_worklist_cond(xs, combos):
    p = os.path.join(SCRATCH, "mc_wl.csv")
    with open(p, "w", newline="") as f:
        for c in combos:
            f.write(",".join(map(str, c)) + "\n")
    cols = ",".join(INV[i] for i in xs)
    defs = ",".join(f"{INV[i]} BIGINT NOT NULL" for i in xs)
    sh(f"DROP TABLE IF EXISTS wl; CREATE TABLE wl({defs}) ENGINE=InnoDB;"
       f"LOAD DATA LOCAL INFILE '{p.replace(chr(92), '/')}' INTO TABLE wl "
       f"FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' ({cols});")
    os.remove(p)


def time_mode(t, xs, a, reps):
    on = " AND ".join(f"{t}.{INV[i]}=wl.{INV[i]}" for i in xs)
    fwd = f"UPDATE {t} JOIN wl ON {on} SET {t}.{INV[a]}={t}.{INV[a]}+@step;"
    inv = f"UPDATE {t} JOIN wl ON {on} SET {t}.{INV[a]}={t}.{INV[a]}-@step;"
    sql = (f"SET @step={STEP};\nSET @t=NOW(6);\n{fwd}\n"
           f"SET @e=NOW(6), @rc=ROW_COUNT();\n{inv}\n"
           f"SELECT TIMESTAMPDIFF(MICROSECOND,@t,@e), @rc;\n")
    ts, rows = [], 0
    for _ in range(reps):
        quiesce()
        out = sh(sql).split()
        if len(out) < 2:
            time.sleep(2)
            out = sh(sql).split()
        ts.append(int(out[0]) / 1e6)
        rows = int(out[1])
    return st.median(ts), rows


# ---- M2: completion ---------------------------------------------------------
def load_worklist_compl(pend, pool):
    rows = [r for r in pend if r["pool"] == pool]
    p = os.path.join(SCRATCH, "mc_wlc.csv")
    with open(p, "w", newline="") as f:
        for r in rows:
            f.write(f"{r['o']},{r['c']},{r['s']},{r['z']},{r['t']},{r['p_new']},{r['c_old']}\n")
    sh("DROP TABLE IF EXISTS wlc; CREATE TABLE wlc(o BIGINT, c BIGINT, s BIGINT,"
       " z BIGINT, t BIGINT, p_new BIGINT, c_old BIGINT, PRIMARY KEY(o), KEY wsz(s,z)) ENGINE=InnoDB;"
       f"LOAD DATA LOCAL INFILE '{p.replace(chr(92), '/')}' INTO TABLE wlc "
       "FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' (o,c,s,z,t,p_new,c_old);")
    os.remove(p)
    return len(rows)


def completion_sql(design, repair):
    """Forward+inverse statement pairs for one completion batch on one design."""
    if design == "d_ic":
        rep_f = "UPDATE ocsz JOIN wlc ON ocsz.s=wlc.s AND ocsz.z=wlc.z SET ocsz.c=wlc.c;"
        rep_i = "UPDATE ocsz JOIN wlc ON ocsz.s=wlc.s AND ocsz.z=wlc.z SET ocsz.c=wlc.c_old;"
        ins = ["INSERT INTO ocsz SELECT wlc.o, wlc.c, wlc.s, wlc.z FROM wlc;",
               "INSERT INTO oszt SELECT wlc.o, wlc.s, wlc.z, wlc.t FROM wlc;",
               "INSERT INTO oct  SELECT wlc.o, wlc.c, wlc.t FROM wlc;",
               "INSERT INTO op   SELECT wlc.o, wlc.p_new FROM wlc;"]
        dele = ["DELETE ocsz FROM ocsz JOIN wlc ON ocsz.o=wlc.o AND ocsz.s=wlc.s AND ocsz.z=wlc.z;",
                "DELETE oszt FROM oszt JOIN wlc ON oszt.o=wlc.o AND oszt.s=wlc.s AND oszt.z=wlc.z;",
                "DELETE oct  FROM oct  JOIN wlc ON oct.o=wlc.o AND oct.t=wlc.t;",
                "DELETE op   FROM op   JOIN wlc ON op.o=wlc.o;"]
    else:
        rep_f = "UPDATE csz JOIN wlc ON csz.s=wlc.s AND csz.z=wlc.z SET csz.c=wlc.c;"
        rep_i = "UPDATE csz JOIN wlc ON csz.s=wlc.s AND csz.z=wlc.z SET csz.c=wlc.c_old;"
        ins = ["INSERT IGNORE INTO csz SELECT wlc.c, wlc.s, wlc.z FROM wlc;",
               "INSERT INTO oszt SELECT wlc.o, wlc.s, wlc.z, wlc.t FROM wlc;",
               "INSERT INTO ocst SELECT wlc.o, wlc.c, wlc.s, wlc.t FROM wlc;",
               "INSERT INTO op   SELECT wlc.o, wlc.p_new FROM wlc;"]
        dele = ["DELETE oszt FROM oszt JOIN wlc ON oszt.o=wlc.o AND oszt.s=wlc.s AND oszt.z=wlc.z;",
                "DELETE ocst FROM ocst JOIN wlc ON ocst.o=wlc.o AND ocst.t=wlc.t;",
                "DELETE op   FROM op   JOIN wlc ON op.o=wlc.o;"]
    fwd = ([rep_f] if repair else []) + ins + \
          ["DELETE rest FROM rest JOIN wlc ON rest.o=wlc.o;"]
    inv = dele + ([rep_i] if repair else []) + \
          ["INSERT INTO rest(o,c,s,z,t,p) SELECT wlc.o, wlc.c, wlc.s, wlc.z, wlc.t, NULL FROM wlc;"]
    return fwd, inv


def time_completion(design, pend, pool, reps):
    m = load_worklist_compl(pend, pool)
    repair = pool == "conflict"
    fwd, inv = completion_sql(design, repair)
    fwd_sql = "\n".join(fwd)
    inv_sql = "\n".join(inv)
    sql = (f"SET @t=NOW(6);\n{fwd_sql}\nSET @e=NOW(6);\n{inv_sql}\n"
           f"SELECT TIMESTAMPDIFF(MICROSECOND,@t,@e);\n")
    ts = []
    for _ in range(reps):
        quiesce()
        out = sh(sql).split()
        if not out:
            time.sleep(2)
            out = sh(sql).split()
        ts.append(int(out[0]) / 1e6)
    return st.median(ts), m


def table_counts():
    return {t: int(sh(f"SELECT COUNT(*) FROM {t};")) for t in list(SCHEMA) + ["rest"]}


# ---- run --------------------------------------------------------------------
def run(n, seed=0):
    counts, pend = build(n)
    reps = 3 if n < 1_000_000 else 2
    k = n // G
    print(f"  rows " + " ".join(f"{t}={c:,}" for t, c in counts.items())
          + f"  k={k} reps={reps}", flush=True)
    base_counts = counts.copy()
    res = {"_counts": counts, "_k": k}

    # M1a cold modes (1% each) for whole-workload totals
    cold = {}
    for t in SCHEMA:
        _, modes = schema_modes(t)
        for X, a, isk in modes:
            if is_hot(X, a):
                continue
            xs, combos = sample_conditions(X, COLD_FRAC, n, seed)
            load_worklist_cond(xs, combos)
            cold[(t, X, a)] = time_mode(t, xs, a, reps) + (isk,)
    res["_cold"] = {f"{t}:{_name(X, a)}": {"ms": v[0] * 1e3, "rows": v[1], "key": v[2]}
                    for (t, X, a), v in cold.items()}

    # M1b hot refresh at each level
    X, a = _S(HOT[0]), AID[HOT[1]]
    xs = order_cols(X)
    hot = {}
    for tbl in ("ocsz", "csz"):
        for lab, frac in HOT_FREQ:
            _, combos = sample_conditions(X, frac, n, seed)
            load_worklist_cond(xs, combos)
            hot[(tbl, lab)] = time_mode(tbl, xs, a, reps)
    def cold_sum(decomp):
        return sum(v[0] for kk, v in cold.items() if kk[0] in decomp)
    res["refresh"] = {}
    for lab, _ in HOT_FREQ:
        dic = cold_sum(D_IC) + hot[("ocsz", lab)][0]
        dus = cold_sum(D_US) + hot[("csz", lab)][0]
        res["refresh"][lab] = {
            "hot_ic_ms": hot[("ocsz", lab)][0] * 1e3, "hot_ic_rows": hot[("ocsz", lab)][1],
            "hot_us_ms": hot[("csz", lab)][0] * 1e3, "hot_us_rows": hot[("csz", lab)][1],
            "total_ic_ms": dic * 1e3, "total_us_ms": dus * 1e3, "ratio": dic / dus}
        print(f"  refresh {lab:4s}: ocsz={hot[('ocsz',lab)][0]*1e3:9.1f}ms/{hot[('ocsz',lab)][1]:>9,}r"
              f"  csz={hot[('csz',lab)][0]*1e3:7.2f}ms/{hot[('csz',lab)][1]:>4}r"
              f"  workload D_IC/D_US={res['refresh'][lab]['ratio']:6.1f}x", flush=True)

    # M2 completion
    sh("DROP TABLE IF EXISTS wl;")                # avoid stale joins
    res["completion"] = {}
    for pool in ("clean", "conflict"):
        row = {}
        for design in ("d_ic", "d_us"):
            tt, m = time_completion(design, pend, pool, reps)
            row[design] = {"ms": tt * 1e3, "batch": m, "ms_per_op": tt * 1e3 / m}
            after = table_counts()
            assert after == base_counts, f"restore drift {pool}/{design}: {after} vs {base_counts}"
        row["ratio"] = row["d_ic"]["ms"] / row["d_us"]["ms"]
        res["completion"][pool] = row
        print(f"  completion {pool:8s}: D_IC={row['d_ic']['ms']:9.1f}ms"
              f"  D_US={row['d_us']['ms']:8.1f}ms  ratio={row['ratio']:6.1f}x"
              f"  (batch={row['d_ic']['batch']})", flush=True)
    return res


def main():
    _selfcheck()
    if "--check" in sys.argv:
        return
    scales = [20_000] if "--tiny" in sys.argv else SCALES
    outfile = "mini_courier.json"
    for i, a in enumerate(sys.argv):
        if a == "--scales":
            scales = [int(x) for x in sys.argv[i + 1].split(",")]
        elif a == "--out":
            outfile = sys.argv[i + 1]
    out = {"_scales": scales, "_G": G, "_m_pend": M_PEND}
    old = int(sh("SELECT @@innodb_buffer_pool_size;", db=None))
    if old >= POOL_BIG:
        old = POOL_SMALL
    print(f"buffer pool -> {POOL_BIG/1024**3:.0f}G (restore {old/1024**2:.0f}M)", flush=True)
    set_pool(POOL_BIG)
    try:
        for n in scales:
            print(f"[N={n:,}]", flush=True)
            out[str(n)] = run(n)
            here = os.path.dirname(os.path.abspath(__file__))
            json.dump(out, open(os.path.join(here, outfile), "w"), indent=1)
    finally:
        if "--tiny" not in sys.argv:
            sh(f"DROP DATABASE IF EXISTS {DB};", db=None)
        set_pool(old)
        print(f"buffer pool restored to {old/1024**2:.0f}M")
    print(f"\nwrote {outfile}")


if __name__ == "__main__":
    main()
