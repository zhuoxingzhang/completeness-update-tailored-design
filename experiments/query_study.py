"""Query-side costs of the two courier designs (read counterpart of E3-E5).

One build at N = 10^6 (full scope, original t), both designs materialized side
by side as in every operational study; then three read workloads:

  Q1  full scope reconstruction: 4-way natural join back to R, COUNT + SUM
      anchor (asserted equal across designs and equal to N).
  Q2  hot-rule lookup: c from (s,z), 2000 random pairs; D_theta reads its csz
      subschema by primary key, D_f reads the wider ocsz by key prefix.
  Q3  courier history: all rows of one courier s joined back to full arity,
      10 couriers (n/20 rows each).

Wall-clock on a persistent connection, one warm-up pass, medians over repeats.
Storage footprint (data_length + index_length) is recorded per design.
Results -> query_study.json.
"""
import os, sys, json, time, random
import statistics as st

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
import mini_courier as mc
import ext_courier as ec
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "query_study.json")
N = 1_000_000
REPS = 5

Q1 = {   # full natural joins: every shared attribute equated, so each step is 1:1
    "d_ic": "SELECT COUNT(*), SUM(b.c) FROM oszt a "
            "JOIN ocsz b ON b.o=a.o AND b.s=a.s AND b.z=a.z "
            "JOIN oct c ON c.o=a.o AND c.t=a.t AND c.c=b.c "
            "JOIN op d ON d.o=a.o",
    "d_us": "SELECT COUNT(*), SUM(e.c) FROM oszt a "
            "JOIN csz e ON e.s=a.s AND e.z=a.z "
            "JOIN ocst f ON f.s=a.s AND f.o=a.o AND f.t=a.t AND f.c=e.c "
            "JOIN op d ON d.o=a.o",
}
Q2 = {
    "d_ic": "SELECT c FROM ocsz WHERE s=%s AND z=%s LIMIT 1",
    "d_us": "SELECT c FROM csz WHERE s=%s AND z=%s",
}
Q3 = {
    "d_ic": "SELECT a.o,a.s,a.z,a.t,b.c,d.p FROM oszt a "
            "JOIN ocsz b ON b.s=a.s AND b.z=a.z AND b.o=a.o "
            "JOIN op d ON d.o=a.o WHERE a.s=%s",
    "d_us": "SELECT a.o,a.s,a.z,a.t,e.c,d.p FROM oszt a "
            "JOIN csz e ON e.s=a.s AND e.z=a.z "
            "JOIN op d ON d.o=a.o WHERE a.s=%s",
}


def main():
    if "--nobuild" in sys.argv:
        print("reusing existing build", flush=True)
    else:
        print(f"building N={N} ...", flush=True)
        counts, _, _ = ec.build_variant(N, 1.0, "orig")
        print("counts:", counts, flush=True)

    conn = config.connect(mc.DB)
    cur = conn.cursor()
    for t in mc.SCHEMA:
        cur.execute(f"ANALYZE TABLE {t}")
        cur.fetchall()

    rnd = random.Random(7)
    cur.execute("SELECT s, z FROM csz")
    sz_all = cur.fetchall()
    sz = [sz_all[rnd.randrange(len(sz_all))] for _ in range(2000)]
    couriers = list(range(mc.N_COURIER))
    rnd.shuffle(couriers)
    couriers = couriers[:10]

    res = {"N": N}
    for design, tables in (("d_ic", mc.D_IC), ("d_us", mc.D_US)):
        r = {}
        # storage footprint of this design's tables
        cur.execute(
            "SELECT SUM(data_length), SUM(index_length) FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name IN ({})".format(
                ",".join(["%s"] * len(tables))), (mc.DB, *tables))
        dl, il = cur.fetchone()
        r["storage_mb"] = round((dl + il) / 2**20, 1)

        # Q1 full reconstruction (instances carry a few Armstrong core rows on
        # top of N, so assert repeatability here and cross-design equality below)
        anchors, times = set(), []
        for i in range(REPS + 1):
            t0 = time.perf_counter()
            cur.execute(Q1[design])
            row = cur.fetchone()
            dt = time.perf_counter() - t0
            anchors.add(row)
            if i:                                   # drop warm-up
                times.append(dt)
        assert len(anchors) == 1, f"Q1 unstable anchors {anchors}"
        r["q1_rows"], r["q1_sum"] = anchors.pop()
        r["q1_s"] = round(st.median(times), 3)

        # Q2 hot-rule lookups
        times = []
        for i in range(4):
            t0 = time.perf_counter()
            for s_, z_ in sz:
                cur.execute(Q2[design], (s_, z_))
                cur.fetchall()
            dt = time.perf_counter() - t0
            if i:
                times.append(dt)
        r["q2_ms_per_lookup"] = round(1000 * st.median(times) / len(sz), 4)

        # Q3 courier history
        times, nrows = [], set()
        for i in range(4):
            t0 = time.perf_counter()
            got = 0
            for s_ in couriers:
                cur.execute(Q3[design], (s_,))
                got += len(cur.fetchall())
            dt = time.perf_counter() - t0
            nrows.add(got)
            if i:
                times.append(dt)
        assert len(nrows) == 1, nrows
        r["q3_ms_per_courier"] = round(1000 * st.median(times) / len(couriers), 1)
        r["q3_rows_per_courier"] = nrows.pop() // len(couriers)

        res[design] = r
        print(design, r, flush=True)

    assert (res["d_ic"]["q1_rows"], res["d_ic"]["q1_sum"]) == \
           (res["d_us"]["q1_rows"], res["d_us"]["q1_sum"]), "Q1 designs disagree"
    conn.close()
    json.dump(res, open(OUT, "w"), indent=1, default=float)
    print("wrote query_study.json", flush=True)


if __name__ == "__main__":
    main()
