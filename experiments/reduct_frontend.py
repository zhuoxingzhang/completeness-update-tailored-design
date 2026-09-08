"""RQ2: three synthesizers on the reduct Sigma[E] of real incomplete data.

Inputs: atomic closures of FDs mined from benchmark datasets under BOTH NULL
semantics (NULL EQUALITY / NULL UNCERTAINTY), shipped under data/fd/.
Positioning for the paper: each mined FD set is the reduct Sigma[E] the design
operates on; the two semantics bracket how a completeness reading turns the
same incomplete table into constraints.

Compared synthesizers (all on the same reduct, same keys):
  3nf        classical 3NF synthesis (Bernstein-style baseline)
  so         structure-optimal (fewest procedurally maintained FDs), frequency-blind
  ha         heat-aware (Algorithm 1 of the paper)

Heat protocol: every atomic FD is one update mode, hot with probability p, a hot
mode drawing its level uniformly from {1..SCALE}.  p is swept over ten values
from 0.1 to 1 in steps of 0.1 and every configuration is repeated over twenty
draws.  Table 3 of the paper is the p = 0.5 slice and Table 4 summarizes the
sweep.  Per-draw values
of hmax, htot, size and crit are kept, so the paper's statistics can be recomputed
from the result file without re-running, together with the time t of every
synthesis call.  Times measured under parallel workers are inflated by
contention; the time column of Table 3 was measured with CUTD_WORKERS=1.

Tasks are (reduct, p) pairs run in parallel.  Closures above CAP atomic FDs
(pathological ones such as diabetic, 40k-144k atomic FDs) are reported, not run.
Partial results land in rq2_parts/ and are merged into results/rq2_reducts.json;
rerun with --merge to rebuild the merged file from the parts alone.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import config

MODES = ["3nf", "so", "ha"]
PS = [round(0.1 * i, 1) for i in range(1, 11)]
SEEDS = list(range(20))
SCALE = 10
CAP = 10_000
WORKERS = int(os.environ.get("CUTD_WORKERS", "18"))
HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.join(HERE, "rq2_parts")
OUT = os.path.join(config.RESULTS, "rq2_reducts.json")


def atomic_count(path):
    d = json.load(open(path, encoding="utf-8"))
    return sum(len(fd["rhs"]) for fd in d["fds"])


def task(arg):
    """One (reduct, p) cell: twenty draws x three synthesizers."""
    tag, path, p = arg
    import synthesis as B
    R, sigma, keys = B.load(path)
    prep = B.prepare(sigma)
    per = {m: {"hmax": [], "htot": [], "size": [], "crit": [], "t": []} for m in MODES}
    t0 = time.perf_counter()
    for seed in SEEDS:
        hot = B.levels(sigma, p, seed, scale=SCALE)
        for m in MODES:
            t1 = time.perf_counter()
            dec = B.synthesize(R, sigma, keys, m, hot=hot, prep=prep)
            per[m]["t"].append(time.perf_counter() - t1)
            met = B.decomp_metrics(dec, hot)
            for k in ("hmax", "htot", "size", "crit"):
                per[m][k].append(met[k])
    rec = {"tag": tag, "p": p, "R": len(R), "fds": len(sigma), "keys": len(keys),
           "per": per, "wall": round(time.perf_counter() - t0, 1)}
    json.dump(rec, open(os.path.join(PARTS, f"{tag.replace(':', '_')}_{p}.json"), "w"))
    return tag, p, rec["wall"]


def merge(skipped=()):
    if not os.path.isdir(PARTS):
        raise SystemExit(f"no partial results in {PARTS}; run without --merge first")
    out = {}
    for f in sorted(os.listdir(PARTS)):
        r = json.load(open(os.path.join(PARTS, f)))
        e = out.setdefault(r["tag"], {"R": r["R"], "fds": r["fds"], "keys": r["keys"], "ps": {}})
        e["ps"][str(r["p"])] = r["per"]
    json.dump({"protocol": {"p": PS, "seeds": SEEDS, "scale": SCALE, "modes": MODES,
                            "skipped": list(skipped)},
               "reducts": out}, open(OUT, "w"), indent=1)
    print(f"merged {len(out)} reducts into {OUT}")


def main():
    os.makedirs(PARTS, exist_ok=True)
    os.makedirs(config.RESULTS, exist_ok=True)
    jobs, skipped = [], []
    for sem, folder in config.SEMS.items():
        fdir = os.path.join(config.FD_BASE, folder, "FD")
        for f in sorted(os.listdir(fdir)):
            if f.endswith(".json"):
                path = os.path.join(fdir, f)
                n = atomic_count(path)
                tag = f"{f[:-5]}:{sem}"
                if n > CAP:
                    skipped.append(f"{tag}({n})")
                    print(f"SKIP {tag} atomic={n} > {CAP}", flush=True)
                else:
                    jobs.append((n, tag, path))
    jobs.sort(reverse=True)                    # heaviest reducts first, for load balance
    tasks = [(tag, path, p) for _, tag, path in jobs for p in PS]
    print(f"{len(jobs)} reducts x {len(PS)} p x {len(SEEDS)} seeds = {len(tasks)} tasks "
          f"on {WORKERS} workers", flush=True)
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        for i, (tag, p, w) in enumerate(ex.map(task, tasks), 1):
            print(f"[{i:3d}/{len(tasks)}] {tag:36s} p={p:<5} {w:7.1f}s "
                  f"(elapsed {time.perf_counter()-t0:.0f}s)", flush=True)
    merge(skipped)
    print(f"done in {time.perf_counter()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    if "--merge" in sys.argv:
        merge()
    else:
        main()
