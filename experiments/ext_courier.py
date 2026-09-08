"""E3-E5: mixed workloads, skew sensitivity, and robustness on the courier designs.

Extends mini_courier.py (imported as mc; reuses its Armstrong instance, MySQL
harness, index policy, and timing protocol).

E3 (RQ3)  Mixed refresh-completion workloads.  T=100 operation units, a share
          gamma of which are completions (variant clean | conflict), the rest
          single-group hot refreshes.  Refresh groups and completion groups are
          disjoint so forward and inverse statements commute; the whole
          interleaved sequence is timed in-server, the inverse restores state,
          counts and SUM(c) checksums are asserted unchanged.
E4 (RQ4)  Skew sensitivity.  Whole-workload time as a function of the hot heat
          w in {1,2,4,8,16,32}: every cold mode run once at 1% coverage,
          the hot mode w times on rotated 1% samples.
E5a (RQ5) Completeness drift.  Instances with scope fraction {25,50,75,100}%
          (held-out layers pending in rest, p NULL); hot refresh pass and
          conflicting-completion batch issued per fraction.
E5b (RQ5) Misestimated heat.  Variant instance (timeslot reuse: t = e*G + j%20)
          in which the groups of ct->o and ot->c carry redundancy 5; the
          declared-hot and the actually-hot mode are run at 1% coverage on
          both designs, giving the cost of an adversarial hot-rule swap.

Run:  python ext_courier.py --check     # instance checks only, no MySQL
      python ext_courier.py             # full run -> ext_courier.json
"""
import os, sys, json, random, itertools
import statistics as st

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import mini_courier as mc

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ext_courier.json")

T_UNITS = 100
GAMMAS = [0.0, 0.1, 0.25, 0.5]
SKEWS = [1, 2, 4, 8, 16, 32]
SCALES_E34 = [100_000, 1_000_000]
SCALE_E5 = 1_000_000
SCOPE_FRACS = [0.25, 0.5, 0.75, 1.0]


def val(a, e, j, tmode):
    if a == "t" and tmode == "slot":
        return e * mc.G + (j % mc.N_COURIER)
    return mc.attr_val(a, e, j)


def bulk_rows(n, tmode):
    k = n // mc.G
    for e in range(k):
        for j in range(mc.G):
            yield tuple(val(a, e, j, tmode) for a in mc.ATTRS)


# ---- instance checks --------------------------------------------------------
def selfcheck():
    rows = list(bulk_rows(20 * mc.G, "slot"))
    for l, r in mc.SIGMA_S:
        assert not mc._violated(rows, mc._S(l), mc.AID[r]), f"slot bulk breaks {l}->{r}"
    ct = {}
    for tup in rows:
        ct.setdefault((tup[mc.AID["c"]], tup[mc.AID["t"]]), set()).add(tup[mc.AID["s"]])
    sizes = {len(v) for v in ct.values()}
    assert sizes == {5}, f"ct-group sizes {sizes}"
    print(f"slot variant OK: 8 declared FDs hold, ct-groups have redundancy 5")
    for variant in ("clean", "conflict"):
        for design in ("d_ic", "d_us"):
            pend = mc.pending_rows(20 * mc.G)
            f, i = e3_scripts(design, variant, 0.5, pend, seed=1)
            assert len(f) and len(i)
    print("E3 statement generation OK")


# ---- variant build (scope fraction / t formula) -----------------------------
def build_variant(n, scope_frac=1.0, tmode="orig"):
    mc.sh(f"CREATE DATABASE IF NOT EXISTS {mc.DB};", db=None)
    k = n // mc.G
    scope_k = max(1, round(scope_frac * k))
    dedup = {"csz", "op"} | ({"oct"} if tmode == "slot" else set())
    paths = {t: os.path.join(mc.SCRATCH, f"ec_{t}.csv") for t in mc.SCHEMA}
    rest_path = os.path.join(mc.SCRATCH, "ec_rest.csv")
    fh = {t: open(p, "w", newline="") for t, p in paths.items()}
    rf = open(rest_path, "w", newline="")
    seen = {t: set() for t in mc.SCHEMA}
    try:
        for e in range(k):
            for j in range(mc.G):
                row = tuple(val(a, e, j, tmode) for a in mc.ATTRS)
                if e >= scope_k:                      # held-out layer: pending
                    rf.write(",".join(map(str, row[:5])) + ",\\N\n")
                    continue
                for t, cols in mc.SCHEMA.items():
                    v = tuple(row[mc.AID[a]] for a in cols)
                    if t in dedup:
                        if v in seen[t]:
                            continue
                        seen[t].add(v)
                    fh[t].write(",".join(map(str, v)) + "\n")
        for row in mc.core_rows():
            for t, cols in mc.SCHEMA.items():
                v = tuple(row[mc.AID[a]] for a in cols)
                if v in seen[t]:
                    continue
                seen[t].add(v)
                fh[t].write(",".join(map(str, v)) + "\n")
    finally:
        for f in fh.values():
            f.close()
        rf.close()
    stmts = ["DROP TABLE IF EXISTS rest;"] + ["DROP TABLE IF EXISTS " + t + ";" for t in mc.SCHEMA]
    for t, cols in mc.SCHEMA.items():
        pk, uq, sec = mc.schema_indexes(t)
        defs = [f"{a} BIGINT NOT NULL" for a in cols]
        defs.append(f"PRIMARY KEY({','.join(mc.INV[i] for i in pk)})")
        defs += [f"UNIQUE KEY u{i}({','.join(mc.INV[c] for c in u)})" for i, u in enumerate(uq)]
        defs += [f"KEY s{i}({','.join(mc.INV[c] for c in s)})" for i, s in enumerate(sec)]
        stmts.append(f"CREATE TABLE {t}({', '.join(defs)}) ENGINE=InnoDB;")
    stmts.append("CREATE TABLE rest(o BIGINT NOT NULL, c BIGINT, s BIGINT, z BIGINT,"
                 " t BIGINT, p BIGINT, KEY ro(o), KEY rsz(s,z)) ENGINE=InnoDB;")
    mc.sh("\n".join(stmts))
    for t in mc.SCHEMA:
        mc.sh(f"LOAD DATA LOCAL INFILE '{paths[t].replace(chr(92), '/')}' INTO TABLE {t} "
              f"FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' ({','.join(mc.SCHEMA[t])});")
        os.remove(paths[t])
    if scope_frac < 1.0:
        mc.sh(f"LOAD DATA LOCAL INFILE '{rest_path.replace(chr(92), '/')}' INTO TABLE rest "
              "FIELDS TERMINATED BY ',' LINES TERMINATED BY '\\n' (o,c,s,z,t,p);")
    os.remove(rest_path)
    pend = mc.pending_rows(n)
    vals = ",".join(f"({r['o']},{r['c']},{r['s']},{r['z']},{r['t']},NULL)" for r in pend)
    mc.sh(f"INSERT INTO rest(o,c,s,z,t,p) VALUES {vals};")
    counts = {t: int(mc.sh(f"SELECT COUNT(*) FROM {t};")) for t in list(mc.SCHEMA) + ["rest"]}
    return counts, pend, scope_k


# ---- E3: interleaved mixed workload -----------------------------------------
def compl_unit(design, r, conflict):
    o, c, s, z, t, p, co = r["o"], r["c"], r["s"], r["z"], r["t"], r["p_new"], r["c_old"]
    if design == "d_ic":
        ins = [f"INSERT INTO ocsz VALUES({o},{c},{s},{z});",
               f"INSERT INTO oszt VALUES({o},{s},{z},{t});",
               f"INSERT INTO oct VALUES({o},{c},{t});",
               f"INSERT INTO op VALUES({o},{p});"]
        dele = [f"DELETE FROM ocsz WHERE o={o} AND s={s} AND z={z};",
                f"DELETE FROM oszt WHERE o={o} AND s={s} AND z={z};",
                f"DELETE FROM oct WHERE o={o} AND t={t};",
                f"DELETE FROM op WHERE o={o};"]
        rep_f = [f"UPDATE ocsz SET c={c} WHERE s={s} AND z={z};"] if conflict else []
        rep_i = [f"UPDATE ocsz SET c={co} WHERE s={s} AND z={z};"] if conflict else []
    else:
        ins = [f"INSERT IGNORE INTO csz VALUES({c},{s},{z});",
               f"INSERT INTO oszt VALUES({o},{s},{z},{t});",
               f"INSERT INTO ocst VALUES({o},{c},{s},{t});",
               f"INSERT INTO op VALUES({o},{p});"]
        dele = [f"DELETE FROM oszt WHERE o={o} AND s={s} AND z={z};",
                f"DELETE FROM ocst WHERE o={o} AND t={t};",
                f"DELETE FROM op WHERE o={o};"]
        rep_f = [f"UPDATE csz SET c={c} WHERE s={s} AND z={z};"] if conflict else []
        rep_i = [f"UPDATE csz SET c={co} WHERE s={s} AND z={z};"] if conflict else []
    fwd = rep_f + ins + [f"DELETE FROM rest WHERE o={o};"]
    inv = [f"INSERT INTO rest(o,c,s,z,t,p) VALUES({o},{c},{s},{z},{t},NULL);"] + dele + rep_i
    return fwd, inv


def refresh_unit(design, j):
    tbl = "ocsz" if design == "d_ic" else "csz"
    s, z = j // mc.N_ZONE, j % mc.N_ZONE
    return ([f"UPDATE {tbl} SET c=c+@step WHERE s={s} AND z={z};"],
            [f"UPDATE {tbl} SET c=c-@step WHERE s={s} AND z={z};"])


def e3_scripts(design, variant, gamma, pend, seed):
    conflict = variant == "conflict"
    pool = [r for r in pend if r["pool"] == variant]
    n_c = round(gamma * T_UNITS)
    assert n_c <= len(pool)
    cgroups = {r["s"] * mc.N_ZONE + r["z"] for r in pool}
    rgroups = [j for j in range(mc.G) if j not in cgroups]
    rnd = random.Random(seed)
    cpos = {round(i * T_UNITS / n_c) for i in range(n_c)} if n_c else set()
    fwd, inv, ci = [], [], 0
    for u in range(T_UNITS):
        if u in cpos and ci < n_c:
            f, i = compl_unit(design, pool[ci], conflict)
            ci += 1
        else:
            f, i = refresh_unit(design, rnd.choice(rgroups))
        fwd += f
        inv = i + inv
    return fwd, inv


def checksums(design):
    tbl = "ocsz" if design == "d_ic" else "csz"
    return mc.sh(f"SELECT COUNT(*), COALESCE(SUM(c),0) FROM {tbl};")


def run_e3(n, pend, base_counts, reps):
    res = {}
    for variant in ("clean", "conflict"):
        for g in GAMMAS:
            row = {}
            for design in ("d_ic", "d_us"):
                fwd, inv = e3_scripts(design, variant, g, pend, seed=7)
                before = checksums(design)
                sql = (f"SET @step={mc.STEP};\nSET @t=NOW(6);\n" + "\n".join(fwd)
                       + "\nSET @e=NOW(6);\n" + "\n".join(inv)
                       + "\nSELECT TIMESTAMPDIFF(MICROSECOND,@t,@e);\n")
                ts = []
                for _ in range(reps):
                    mc.quiesce()
                    out = mc.sh(sql).split()
                    ts.append(int(out[0]) / 1e6)
                assert checksums(design) == before, f"E3 restore drift {variant}/{g}/{design}"
                assert mc.table_counts() == base_counts
                row[design] = st.median(ts) * 1e3
            row["ratio"] = row["d_ic"] / row["d_us"]
            res[f"{variant}:{g}"] = row
            print(f"  E3 {variant:8s} g={g:4.2f}: D_IC={row['d_ic']:9.1f}ms"
                  f"  D_US={row['d_us']:7.1f}ms  ratio={row['ratio']:7.1f}x", flush=True)
    return res


# ---- E4: skew curve ---------------------------------------------------------
def run_e4(n, reps):
    cold = {}
    for t in mc.SCHEMA:
        _, modes = mc.schema_modes(t)
        for X, a, isk in modes:
            if mc.is_hot(X, a):
                continue
            xs, combos = mc.sample_conditions(X, mc.COLD_FRAC, n, 0)
            mc.load_worklist_cond(xs, combos)
            cold[(t, X, a)] = mc.time_mode(t, xs, a, reps)[0]
    X, a = mc._S(mc.HOT[0]), mc.AID[mc.HOT[1]]
    xs = mc.order_cols(X)
    hot = {}
    for tbl in ("ocsz", "csz"):
        hot[tbl] = []
        for i in range(max(SKEWS)):
            _, combos = mc.sample_conditions(X, 0.01, n, 100 + i)
            mc.load_worklist_cond(xs, combos)
            hot[tbl].append(mc.time_mode(tbl, xs, a, reps)[0])
    mc.sh("DROP TABLE IF EXISTS wl;")
    def cold_sum(decomp):
        return sum(v for kk, v in cold.items() if kk[0] in decomp)
    res = {}
    for w in SKEWS:
        dic = cold_sum(mc.D_IC) + sum(hot["ocsz"][:w])
        dus = cold_sum(mc.D_US) + sum(hot["csz"][:w])
        res[str(w)] = {"d_ic": dic * 1e3, "d_us": dus * 1e3, "ratio": dic / dus}
        print(f"  E4 w={w:2d}: D_IC={dic*1e3:9.1f}ms  D_US={dus*1e3:7.1f}ms"
              f"  ratio={dic/dus:6.1f}x", flush=True)
    return res


# ---- E5a: completeness drift ------------------------------------------------
def run_e5a(reps):
    res = {}
    X, a = mc._S(mc.HOT[0]), mc.AID[mc.HOT[1]]
    xs = mc.order_cols(X)
    for frac in SCOPE_FRACS:
        counts, pend, scope_k = build_variant(SCALE_E5, scope_frac=frac)
        row = {"scope_rows": counts["oszt"], "k_scope": scope_k}
        _, combos = mc.sample_conditions(X, 1.0, SCALE_E5, 0)
        mc.load_worklist_cond(xs, combos)
        for tbl, key in (("ocsz", "d_ic"), ("csz", "d_us")):
            row["hot_" + key] = mc.time_mode(tbl, xs, a, reps)[0] * 1e3
        mc.sh("DROP TABLE IF EXISTS wl;")
        base = mc.table_counts()
        for design in ("d_ic", "d_us"):
            tt, m = mc.time_completion(design, pend, "conflict", reps)
            row["compl_" + design] = tt * 1e3 / m
            assert mc.table_counts() == base
        res[str(frac)] = row
        print(f"  E5a scope={frac:4.0%} (k'={scope_k}): hot D_IC={row['hot_d_ic']:9.1f}ms"
              f" D_US={row['hot_d_us']:6.1f}ms  compl/op D_IC={row['compl_d_ic']:7.2f}ms"
              f" D_US={row['compl_d_us']:5.2f}ms", flush=True)
    return res


# ---- E5b: misestimated hot rule ---------------------------------------------
def sample_ct(n, frac, seed):
    k = n // mc.G
    total = k * mc.N_COURIER
    m = max(1, round(frac * total))
    rnd = random.Random(seed)
    seen = set()
    while len(seen) < m:
        seen.add((rnd.randrange(k), rnd.randrange(mc.N_COURIER)))
    return [(c, e * mc.G + c) for e, c in seen]


def run_e5b(reps):
    counts, pend, _ = build_variant(SCALE_E5, tmode="slot")
    res = {"counts": counts}
    X, a = mc._S(mc.HOT[0]), mc.AID[mc.HOT[1]]
    xs = mc.order_cols(X)
    _, combos = mc.sample_conditions(X, 0.01, SCALE_E5, 0)
    mc.load_worklist_cond(xs, combos)
    for tbl, key in (("ocsz", "d_ic"), ("csz", "d_us")):
        res["declared_" + key] = mc.time_mode(tbl, xs, a, reps)[0] * 1e3
    ct = sample_ct(SCALE_E5, 0.01, 0)
    mc.load_worklist_cond([mc.AID["c"], mc.AID["t"]], ct)
    for tbl, key in (("oct", "d_ic"), ("ocst", "d_us")):
        res["actual_" + key] = mc.time_mode(tbl, [mc.AID["c"], mc.AID["t"]], mc.AID["o"], reps)[0] * 1e3
    mc.sh("DROP TABLE IF EXISTS wl;")
    print(f"  E5b declared hot sz->c 1%: D_IC={res['declared_d_ic']:9.1f}ms D_US={res['declared_d_us']:6.2f}ms\n"
          f"      actual   hot ct->o 1%: D_IC={res['actual_d_ic']:9.1f}ms D_US={res['actual_d_us']:6.1f}ms",
          flush=True)
    return res


# ---- main -------------------------------------------------------------------
def main():
    mc._selfcheck()
    selfcheck()
    if "--check" in sys.argv:
        return
    out = {"_T": T_UNITS, "_gammas": GAMMAS, "_skews": SKEWS, "_G": mc.G}
    old = int(mc.sh("SELECT @@innodb_buffer_pool_size;", db=None))
    if old >= mc.POOL_BIG:
        old = mc.POOL_SMALL
    print(f"buffer pool -> {mc.POOL_BIG/1024**3:.0f}G", flush=True)
    mc.set_pool(mc.POOL_BIG)
    try:
        for n in SCALES_E34:
            reps = 3 if n < 1_000_000 else 2
            print(f"[E3/E4 N={n:,}]", flush=True)
            counts, pend = mc.build(n)
            out[f"e3_{n}"] = run_e3(n, pend, counts, reps)
            json.dump(out, open(OUT, "w"), indent=1)
            out[f"e4_{n}"] = run_e4(n, reps)
            json.dump(out, open(OUT, "w"), indent=1)
        print(f"[E5a N={SCALE_E5:,}]", flush=True)
        out["e5a"] = run_e5a(2)
        json.dump(out, open(OUT, "w"), indent=1)
        print(f"[E5b N={SCALE_E5:,}]", flush=True)
        out["e5b"] = run_e5b(2)
        json.dump(out, open(OUT, "w"), indent=1)
    finally:
        mc.sh(f"DROP DATABASE IF EXISTS {mc.DB};", db=None)
        mc.set_pool(old)
        print(f"buffer pool restored to {old/1024**2:.0f}M")
    print("\nwrote ext_courier.json")


if __name__ == "__main__":
    main()
