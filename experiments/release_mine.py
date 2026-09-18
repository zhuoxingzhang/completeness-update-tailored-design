"""The minimal functional dependencies of a built relation, one right-hand side per process.

Under the uncertainty reading a group is formed only by the tuples that are total on the
determinant, and the dependency holds when every group carries at most one non-null value of the
dependent attribute; under the equality reading nulls compare equal.  The search for one
right-hand side is independent of every other, so they run in parallel; the coded columns are
written once to a memory map and opened read-only by each worker, so the matrix is not copied per
process.  The shipped constraint set of the real release, data/release/owid_fds.json, is the
output of this search on the relation release_build.py builds, with at most four determinant
attributes.

Usage: python release_mine.py <nulluc|nulleq> <max_lhs> <in.pkl> <out.json> [workers]
"""
import itertools
import json
import multiprocessing as mp
import os
import pickle
import sys
import tempfile
import time

import numpy as np

NUL = -1
_G = {}


def _init(path, shape, sem, maxl):
    _G["code"] = np.memmap(path, dtype=np.int64, mode="r", shape=shape)
    _G["sem"], _G["maxl"], _G["n"] = sem, maxl, shape[1]


def holds(lhs, rhs):
    code, sem, n = _G["code"], _G["sem"], _G["n"]
    if sem == "nulluc":
        mask = np.ones(n, dtype=bool)
        for c in lhs:
            mask &= code[c] != NUL
        if not mask.any():
            return True
        keys = np.stack([code[c][mask] for c in lhs])
        rv = code[rhs][mask]
        order = np.lexsort((rv, *keys[::-1]))
        keys, rv = keys[:, order], rv[order]
        newg = np.zeros(keys.shape[1], dtype=bool)
        newg[0] = True
        newg[1:] = (keys[:, 1:] != keys[:, :-1]).any(axis=0)
        same = (rv[1:] == rv[:-1]) | (rv[1:] == NUL) | (rv[:-1] == NUL)
        return bool((newg[1:] | same).all())
    keys = np.stack([code[c] for c in lhs])
    rv = code[rhs]
    order = np.lexsort((rv, *keys[::-1]))
    keys, rv = keys[:, order], rv[order]
    newg = np.zeros(n, dtype=bool)
    newg[0] = True
    newg[1:] = (keys[:, 1:] != keys[:, :-1]).any(axis=0)
    return bool((newg[1:] | (rv[1:] == rv[:-1])).all())


def one(args):
    rhs, m = args
    t0 = time.time()
    found, out, checks = [], [], 0
    others = [c for c in range(m) if c != rhs]
    for s in range(1, _G["maxl"] + 1):
        for lhs in itertools.combinations(others, s):
            ls = set(lhs)
            if any(f <= ls for f in found):
                continue
            checks += 1
            if holds(lhs, rhs):
                found.append(ls)
                out.append({"lhs": list(lhs), "rhs": [rhs]})
    return rhs, out, checks, time.time() - t0


def main(sem, maxl, inp, outp, workers):
    d = pickle.load(open(inp, "rb"))
    ATTRS, data = d["attrs"], d["data"]
    n, m = len(data), len(ATTRS)
    print(f"{n:,} tuples x {m} attributes, sem={sem}, max lhs={maxl}, "
          f"{workers} workers", flush=True)

    tmp = os.path.join(tempfile.gettempdir(), f"minepar_{os.getpid()}.dat")
    code = np.memmap(tmp, dtype=np.int64, mode="w+", shape=(m, n))
    for c in range(m):
        vals = {}
        col = code[c]
        for i, r in enumerate(data):
            v = r[c]
            col[i] = -1 if v is None else vals.setdefault(v, len(vals))
        print(f"  {ATTRS[c]:14s} {len(vals):8,} distinct, "
              f"{int((col < 0).sum()):8,} null", flush=True)
    code.flush()
    del code, data, d

    t0 = time.time()
    fds, total = [], 0
    with mp.Pool(workers, initializer=_init,
                 initargs=(tmp, (m, n), sem, maxl)) as pool:
        for rhs, out, checks, dt in pool.imap_unordered(
                one, [(r, m) for r in range(m)]):
            fds.extend(out)
            total += checks
            print(f"  {ATTRS[rhs]:14s} -> {len(out):4d} minimal determinants "
                  f"({dt:.0f}s, {checks} checks)", flush=True)
    json.dump({"R": m, "attrs": ATTRS, "fds": fds}, open(outp, "w"), indent=1)
    try:                       # Windows keeps the map open a moment after the pool closes
        os.remove(tmp)
    except OSError:
        print(f"  (left {tmp} behind)")
    print(f"\n{len(fds)} minimal FDs, {total} checks in {time.time() - t0:.0f}s -> {outp}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "nulluc", int(a[1]) if len(a) > 1 else 4,
         a[2], a[3], int(a[4]) if len(a) > 4 else 12)
