"""
Synthesis engine for completeness- and update-tailored database design.

One skeleton, several objectives; the objective is the only variable, so that
the experiments compare designs rather than implementations.

  - "3nf"     : classical lossless, dependency-preserving 3NF synthesis
                [Bernstein 1976; Biskup-Dayal-Bernstein 1979]
  - "bccover" : BCNF whenever one exists                     [Osborn 1979]
  - "conf"    : 3NF, redundant schemata removed by decreasing
                number of minimal keys                       [Zhang-Chen-Link 2023]
  - "so"      : structure-optimal. 3NF, redundant critical schemata removed by
                decreasing number of non-key FDs (f), then redundant BCNF ones
                by decreasing number of minimal keys         [Zhang-Link 2025]
  - "ha"      : heat-aware (Algorithm 1 of the paper). Same skeleton, but
                redundant critical schemata are removed in decreasing E-heat.

The last two differ in one line: which redundant critical schemata are
eliminated first. That line is the contribution the experiments measure.

Input: the atomic closure of the reduct Sigma[E] plus the minimal keys of the
scope. A schema is (R, Sigma_a, keys), Sigma_a a set of single-RHS atomic FDs.

Representation: attribute = int, attribute set = frozenset,
FD = (lhs frozenset, rhs frozenset holding a single attribute).
"""
import json, sys, time, random, os

# ---------- FD primitives ----------

def closure(X, sigma):
    c = set(X)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in sigma:
            if lhs <= c and not rhs <= c:
                c |= rhs
                changed = True
    return c

def is_superkey(X, R, sigma):
    return R <= closure(X, sigma)

def refine_min_key(sigma, key, R):
    # greedily drop attributes while the rest still determines R
    k = set(key)
    for a in list(key):
        if R <= closure(k - {a}, sigma):
            k.discard(a)
    return frozenset(k)

def minimal_keys(R, sigma):
    # Lucchesi-Osborn key enumeration
    keys = [refine_min_key(sigma, R, R)]
    i = 0
    while i < len(keys):
        cur = keys[i]
        for lhs, rhs in sigma:
            S = set(lhs) | (cur - rhs)
            if not any(mk <= S for mk in keys):       # non-redundant candidate
                mk = refine_min_key(sigma, S, R)
                if mk not in keys:
                    keys.append(mk)
        i += 1
    return keys

def projection(sigma, XA):
    # Projection of Sigma onto the subschema XA: keep the atomic FDs that fall entirely within XA.
    # This is EXACT -- it induces the true projected closure closure_Sigma(Y) & XA for every
    # Y subset XA -- PROVIDED `sigma` is a complete atomic closure (every minimal-LHS, single-RHS
    # FD implied by the data), which is exactly what load() supplies. Proof: if B in
    # closure_Sigma(Y) & XA, some minimal X subset Y has X->B in the atomic closure with X,B subset
    # XA, so X->B is kept here; hence closure over the kept FDs recovers B. On a NON-closure cover
    # this may undercount keys / overcount non-key FDs for subschemata whose keys route through
    # attributes outside XA. _check_projection() guards this invariant on real data.
    return [(lhs, rhs) for lhs, rhs in sigma if (lhs | rhs) <= XA]

def is_redundant(fd, sigma):
    lhs, rhs = fd
    rest = [f for f in sigma if f is not fd]
    return rhs <= closure(lhs, rest)

def is_bcnf(XA, proj):
    keys = minimal_keys(XA, proj)
    for lhs, rhs in proj:
        if rhs <= lhs:                      # trivial
            continue
        if not any(k <= lhs for k in keys): # lhs not a superkey
            return False
    return True

# ---------- heat ----------

SCALE = 10            # heat is a 10-level ordinal scale {1,...,10}

# Heat reading of a schema.  "all" (the paper): sum over every non-key atomic FD of the schema,
# since a refresh of any non-key FD rewrites a multi-row group and fires a trigger, whether or not
# the FD is in the cover.  "cover": sum over the FD part of a coolest mixed cover, kept for the
# comparison in the paper's discussion.  Override with the HEAT_READING environment variable.
HEAT = os.environ.get("HEAT_READING", "all")

def fd_hot(fd, hot):
    # heat of an atomic FD = the declared update frequency of its MODE X->A, bound to the FD
    # itself and NOT to its RHS attribute: two FDs with the same RHS but different determinants
    # (e.g. bd->v and dv->b need not be refreshed alike) may carry different heat. `fd` is the
    # (lhs, rhs) pair; `hot` maps an FD (lhs, rhs) -> level in {1..SCALE}, or is None (every mode
    # at the cold baseline, level 1).
    if hot is None:
        return 1
    return hot.get(fd, 1)

def mixed_nonkey_fds(XA, proj_XA, keys_XA):
    # GREEDY nonredundant non-key FD set: keep the FDs not implied by the minimal keys together
    # with the other FDs; superkey-LHS FDs, being implied by the keys, are dropped. This single
    # greedy pass yields a NONREDUNDANT set, not necessarily one of minimum cardinality, and
    # ignores heat. It is retained as the structure-optimal baseline's own notion (that objective
    # ranks critical schemata by len() of this set). The E-heat of the paper is defined on a
    # COOLEST mixed cover instead -- see coolest_nonkey_fds().
    sigma_k = [(k, XA - k) for k in keys_XA]          # key FDs  K -> XA\K
    sigma_f = list(proj_XA)
    for fd in list(proj_XA):
        sigma_f.remove(fd)
        if not fd[1] <= closure(fd[0], sigma_k + sigma_f):   # keys + others do NOT imply fd
            sigma_f.append(fd)
    return sigma_f

def nonkey_atomic(XA, proj_XA):
    # every atomic FD of the schema whose determinant is not a superkey of it
    xp, F = {}, []
    for fd in proj_XA:
        lhs = fd[0]
        if lhs not in xp:
            xp[lhs] = closure(lhs, proj_XA)
        if not xp[lhs] >= XA:
            F.append(fd)
    return F

def schema_nonkey(XA, proj_XA, keys_XA, hot=None):
    # the non-key FDs a schema is charged for, under the active heat reading
    if HEAT == "all":
        return nonkey_atomic(XA, proj_XA)
    return coolest_nonkey_fds(XA, proj_XA, keys_XA, hot)

def coolest_nonkey_fds(XA, proj_XA, keys_XA, hot=None, cap=1 << 18):
    # Non-key FDs of a COOLEST mixed cover (Def. "Mixed cover, heat, coolest" and the classwise
    # factorization lemma): among the minimum-cardinality reduced non-key covers, one of minimum
    # total heat.
    # Exact per determinant class: candidates F_C of a class are optimized independently, with
    # admissibility of P <= F_C checked against the candidates of all other classes as ambient
    # axioms (key FDs are inert in closures of non-superkey determinants, so they are omitted).
    # A class whose 2^|F_C| search exceeds `cap` falls back to the greedy cover's class part
    # (admissible, since the greedy result is a cover) -- never triggered on the benchmarks,
    # where subschema classes carry at most a handful of candidates.
    import itertools
    x_plus = {}
    F = []
    for fd in proj_XA:
        lhs = fd[0]
        if lhs not in x_plus:
            x_plus[lhs] = closure(lhs, proj_XA)
        if not x_plus[lhs] >= XA:                     # non-key candidate
            F.append(fd)
    if not F:
        return []
    classes = {}                                      # closure -> member determinants
    for lhs in {fd[0] for fd in F}:
        classes.setdefault(frozenset(x_plus[lhs]), set()).add(lhs)
    greedy = None
    result = []
    for cl, members in sorted(classes.items(), key=lambda kv: sorted(map(sorted, kv[1]))):
        F_C = sorted((fd for fd in F if fd[0] in members),
                     key=lambda fd: (sorted(fd[0]), sorted(fd[1])))
        ambient = [fd for fd in F if fd[0] not in members]
        def admissible(P):
            base = list(P) + ambient
            return all(x_plus[X] <= closure(X, base) | X for X in members)
        if 2 ** len(F_C) > cap:                       # fallback: greedy class part (admissible)
            if greedy is None:
                greedy = mixed_nonkey_fds(XA, proj_XA, keys_XA)
            result.extend(fd for fd in greedy if fd[0] in members)
            continue
        best = None
        for size in range(len(F_C) + 1):              # minimum cardinality first ...
            for P in itertools.combinations(F_C, size):
                if admissible(P):
                    h = sum(fd_hot(fd, hot) for fd in P)
                    if best is None or h < best[0]:   # ... then minimum hotness
                        best = (h, P)
            if best is not None:
                break
        result.extend(best[1])
    return result

def schema_hot(XA, proj_XA, hot, nonkey=None):
    # E-heat of a schema = SUM of heat over the non-key FDs of a COOLEST mixed cover
    # (= the structure-optimal parameter f when every FD is cold). E-BCNF -> 0 (empty sum).
    if nonkey is None:
        nonkey = schema_nonkey(XA, proj_XA, minimal_keys(XA, proj_XA), hot)
    return sum(fd_hot(fd, hot) for fd in nonkey)

def decomp_max_hot(D, hot):
    return max((schema_hot(XA, p, hot) for XA, p in D), default=0)

def decomp_metrics(D, hot):
    # one pass over the output decomposition: structural + hotness metrics
    nbcnf = ncrit = 0
    keyc_b, keyc_c, fdc, shot = [], [], [], []
    for XA, proj in D:
        ks = minimal_keys(XA, proj)
        nk = schema_nonkey(XA, proj, ks, hot)        # non-key FDs charged under the heat reading
        if nk:                                        # critical schema
            ncrit += 1
            fdc.append(len(nk))
            keyc_c.append(len(ks))                    # minimal keys on critical schemata
            shot.append(sum(fd_hot(fd, hot) for fd in nk))     # schema E-heat (sum)
        else:                                         # BCNF schema
            nbcnf += 1
            keyc_b.append(len(ks))
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return {"size": len(D), "bcnf": nbcnf, "crit": ncrit,
            "avg_keys_b": mean(keyc_b), "avg_keys_c": mean(keyc_c), "avg_fds": mean(fdc),
            "hmax": max(shot) if shot else 0,         # max per-subschema E-heat (the heat-aware objective)
            "htot": sum(shot),                         # total heat-weighted non-key FDs
            "avg_sh": mean(shot)}                      # avg per-critical E-heat

# ---------- synthesis skeleton (one engine, several objectives) ----------

def _add(D, XA, proj_XA):
    if not any(s == XA for s, _ in D):
        D.append((XA, proj_XA))

def _eliminate(order, sigma_work, D, proj):
    # walk FDs in `order`; drop redundant ones from sigma_work, otherwise keep their schema
    for fd in order:
        if is_redundant(fd, sigma_work):
            sigma_work.remove(fd)
        else:
            XA = fd[0] | fd[1]
            _add(D, XA, proj[XA])

def prepare(sigma_a):
    # hot-independent precompute, shared across all modes and seeds for one dataset
    subs = {fd[0] | fd[1] for fd in sigma_a}
    proj = {XA: projection(sigma_a, XA) for XA in subs}
    mkeys = {XA: minimal_keys(XA, proj[XA]) for XA in subs}
    nonkey = {XA: mixed_nonkey_fds(XA, proj[XA], mkeys[XA]) for XA in subs}
    crit = [fd for fd in sigma_a if nonkey[fd[0] | fd[1]]]   # critical iff its mixed cover has a non-key FD
    cset = set(crit)
    noncrit = [fd for fd in sigma_a if fd not in cset]
    return {"proj": proj, "mkeys": mkeys, "nonkey": nonkey, "crit": crit, "noncrit": noncrit}

def synthesize(R, sigma_a, keys, mode, hot=None, prep=None):
    R = frozenset(R)
    if prep is None:
        prep = prepare(sigma_a)
    proj, mkeys, nonkey = prep["proj"], prep["mkeys"], prep["nonkey"]
    crit, noncrit = prep["crit"], prep["noncrit"]
    sigma_work = list(sigma_a)
    D = []

    f_count = lambda fd: len(nonkey[fd[0] | fd[1]])      # structure-optimal f: greedy non-key FD count
    key_count = lambda fd: len(mkeys[fd[0] | fd[1]])
    cool_memo = {}
    def hotness(fd):                                  # schema E-heat on the coolest mixed cover
        XA = fd[0] | fd[1]
        if XA not in cool_memo:
            cool_memo[XA] = schema_nonkey(XA, proj[XA], mkeys[XA], hot)
        return sum(fd_hot(g, hot) for g in cool_memo[XA])

    if mode == "3nf":
        _eliminate(list(sigma_a), sigma_work, D, proj)
    elif mode == "bccover":
        _eliminate(crit, sigma_work, D, proj)         # strip removable critical first
        _eliminate(noncrit, sigma_work, D, proj)
    elif mode == "conf":
        _eliminate(sorted(sigma_a, key=key_count, reverse=True), sigma_work, D, proj)
    elif mode == "so":
        _eliminate(sorted(crit, key=f_count, reverse=True), sigma_work, D, proj)
        _eliminate(sorted(noncrit, key=key_count, reverse=True), sigma_work, D, proj)
    elif mode == "ha":                                # critical removed hottest-first (Algorithm 1)
        _eliminate(sorted(crit, key=hotness, reverse=True), sigma_work, D, proj)
        _eliminate(sorted(noncrit, key=key_count, reverse=True), sigma_work, D, proj)
    else:
        raise ValueError(mode)

    # subset removal
    D = [(XA, p) for XA, p in D if not any(XA < XA2 for XA2, _ in D)]
    # losslessness: ensure some schema contains a candidate key of R
    if not any(any(k <= XA for k in keys) for XA, _ in D):
        K = frozenset(min(keys, key=len))
        _add(D, K, projection(sigma_a, K))
    return D

# ---------- metrics ----------

def classify(D):
    bcnf = crit = 0
    for XA, proj in D:
        if is_bcnf(XA, proj):
            bcnf += 1
        else:
            crit += 1
    return {"schemata": len(D), "bcnf": bcnf, "critical": crit}

# ---------- loader ----------

def load(path):
    # FD-folder files store the atomic closure as multi-RHS FDs (keys encoded as
    # FDs with large RHS). Split every FD into single-RHS atomic FDs (cf. Utils.splitFDs).
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    R = frozenset(range(d["R"]))
    sigma = set()
    for fd in d["fds"]:
        lhs = frozenset(fd["lhs"])
        for a in fd["rhs"]:
            if a not in lhs:                       # drop trivial
                sigma.add((lhs, frozenset({a})))
    sigma = list(sigma)
    keys = [frozenset(k) for k in d.get("keys", [])] or minimal_keys(R, sigma)
    return R, sigma, keys

MODES = ["3nf", "bccover", "conf", "so", "ha"]

# The mined constraint sets shipped with this artifact (atomic closures under the
# NULL-uncertainty reading; see config.FD_BASE and data/fd/README.md).
import os as _os
_NULLUC = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                        "data", "fd", "null-uncertainty", "FD")
DATASETS = {
    "breast":    _os.path.join(_NULLUC, "breast.json"),
    "bridges":   _os.path.join(_NULLUC, "bridges.json"),
    "weather":   _os.path.join(_NULLUC, "china_weather.json"),
    "diabetic":  _os.path.join(_NULLUC, "diabetic.json"),
    "echo":      _os.path.join(_NULLUC, "echo.json"),
    "hepatitis": _os.path.join(_NULLUC, "hepatitis.json"),
    "ncvoter":   _os.path.join(_NULLUC, "ncvoter.json"),
    "pdbx":      _os.path.join(_NULLUC, "pdbx.json"),
    "uniprot":   _os.path.join(_NULLUC, "uniprot.json"),
}

def levels(sigma_a, p, seed=0, scale=SCALE):
    # graded update-MODE skew on the 10-level scale: each atomic FD X->A is an update mode that is
    # "active" (subject to skewed, heavier update load) with probability p and then draws a heat
    # level uniformly from {1..scale}; inactive modes stay at the cold baseline (level 1). Heat is
    # bound to the mode X->A, NOT to the attribute A, so two FDs sharing an RHS may differ.
    # p=0 -> uniform load, where the heat-aware objective degenerates onto the structure-optimal
    # one; p=1 -> every mode graded over the full scale.
    rnd = random.Random(seed)
    key = lambda f: (tuple(sorted(f[0])), tuple(sorted(f[1]))) if isinstance(f, tuple) else (f,)
    return {fd: (rnd.randint(1, scale) if rnd.random() < p else 1) for fd in sorted(sigma_a, key=key)}

def exp(names, ps=(0.25, 0.5, 0.75), seed=0):
    # debug helper: report each objective's output max E-heat and #(critical schemata)
    for name in names:
        R, sigma, keys = load(DATASETS[name])
        print(f"{name}  R={len(R)} atomic_fds={len(sigma)}")
        for p in ps:
            hot = levels(sigma, p, seed)
            cells = []
            for m in MODES:
                D = synthesize(R, sigma, keys, m, hot=hot)
                mx = decomp_max_hot(D, hot)
                ncrit = sum(1 for XA, pr in D if schema_hot(XA, pr, hot) > 0)
                cells.append(f"{m[:4]}={mx}/{ncrit}")
            active = sum(1 for v in hot.values() if v > 1)
            print(f"  p={p:.2f} active_modes={active:3d}/{len(sigma):3d}  maxHot/#crit:  " + "  ".join(cells))

def run(path):
    R, sigma, keys = load(path)
    print(f"  R={len(R)} atomic_fds={len(sigma)} keys={len(keys)}")
    for mode in MODES:
        t0 = time.perf_counter()
        D = synthesize(R, sigma, keys, mode)
        ms = (time.perf_counter() - t0) * 1000
        m = classify(D)
        lossless = any(any(k <= XA for k in keys) for XA, _ in D)
        print(f"  {mode:10s} schemata={m['schemata']:3d} bcnf={m['bcnf']:3d} "
              f"critical={m['critical']:3d} lossless={lossless} {ms:7.1f}ms")

# ---------- self-check ----------

def _check_projection(name="breast"):
    # Guard the projection invariant: on a complete atomic closure (what load() supplies), the
    # syntactic projection() is EXACT, so code minimal keys and mixed-cover non-key FDs match those
    # of the TRUE projected closure closure_Sigma(K) & XA (brute-forced over subsets of XA, empty
    # set included for constant attributes). A failure means the input file is not a full atomic
    # closure and projection() would undercount keys / overcount non-key FDs.
    from itertools import combinations
    R, sigma, _ = load(DATASETS[name])
    def true_keys(XA):
        ks = []
        for r in range(len(XA) + 1):                     # r=0 covers constant-attribute subschemata
            for c in combinations(sorted(XA), r):
                K = frozenset(c)
                if any(k <= K for k in ks):
                    continue
                if XA <= closure(K, sigma):
                    ks.append(K)
        return ks
    for XA in {fd[0] | fd[1] for fd in sigma}:
        if len(XA) > 12:                                 # brute force is 2^|XA|; cap subschema arity
            continue
        proj = projection(sigma, XA)
        ck, tk = minimal_keys(XA, proj), true_keys(XA)
        assert set(ck) == set(tk), f"{name}: projection key mismatch on {sorted(XA)}"
        assert set(mixed_nonkey_fds(XA, proj, ck)) == set(mixed_nonkey_fds(XA, proj, tk)), \
            f"{name}: projection non-key FD mismatch on {sorted(XA)}"

def delivery_example():
    """The delivery running example of the paper, over
    R = {b, c, d, g, r, v, z} = branch, courier, day, gps, round, van, zone,
    encoded as b=0, c=1, d=2, g=3, r=4, v=5, z=6.

    Returns (R, atomic closure of the reduct, minimal keys, heat map), the heat
    map declaring the two modes that a reassignment refreshes hot at level 8 and
    every other mode cold.
    """
    import itertools
    R = frozenset(range(7))
    declared = [
        ({6},       {1}),   # z   -> c   the hot rule, from the eFD (cgz; z->c)
        ({0, 1, 2}, {6}),   # bcd -> z
        ({0, 1},    {5}),   # bc  -> v
        ({0, 5},    {1}),   # bv  -> c   refreshed by the same reassignment
        ({1, 5},    {4}),   # cv  -> r
        ({4, 6},    {0}),   # rz  -> b
        ({5},       {3}),   # v   -> g
    ]
    sigma0 = [(frozenset(l), frozenset(r)) for l, r in declared]
    atomic = []                                   # all X->a implied with X minimal
    for k in range(1, len(R) + 1):
        for X in itertools.combinations(sorted(R), k):
            Xs = frozenset(X)
            for a in sorted(closure(Xs, sigma0) - Xs):
                minimal = k == 1 or all(
                    a not in closure(frozenset(Y), sigma0)
                    for Y in itertools.combinations(X, k - 1))
                if minimal:
                    atomic.append((Xs, frozenset({a})))
    keys = minimal_keys(R, atomic)
    hot = {(frozenset({6}), frozenset({1})): 8,
           (frozenset({0, 5}), frozenset({1})): 8}
    return R, atomic, keys, hot


def _selfcheck():
    R, sigma, keys, hot = delivery_example()
    print("delivery minimal keys:", sorted(sorted(k) for k in keys))
    for mode in MODES:
        D = synthesize(R, sigma, keys, mode)
        lossless = any(any(k <= XA for k in keys) for XA, _ in D)
        # dependency preservation: union of projected FDs must imply every original FD
        union = [fd for _, proj in D for fd in proj]
        dep_pres = all(rhs <= closure(lhs, union) for lhs, rhs in sigma)
        assert lossless, f"{mode}: not lossless"
        assert dep_pres, f"{mode}: not dependency-preserving"
        print(f"  {mode:10s} schemata={len(D)} lossless=OK dep_preserving=OK")

    # Regression for the separation of the paper's Figure 1. The two designs part on the
    # rule that determines the zone: the structure-optimal objective orders critical
    # schemata by the NUMBER of non-key FDs, so it drops bdv->z and keeps bcdz, which stores
    # the hot rule and has maximal E-heat 8; the heat-aware objective orders them by heat, so
    # it drops bcd->z, keeps bdvz and gives the zone its own key subschema cz, for a
    # maximal E-heat of 2, which is the floor h* of the selection lower bound.
    mx_ha = decomp_max_hot(synthesize(R, sigma, keys, "ha", hot=hot), hot)
    mx_so = decomp_max_hot(synthesize(R, sigma, keys, "so", hot=hot), hot)
    assert mx_ha == 2, f"heat-aware max E-heat expected 2, got {mx_ha}"
    assert mx_so == 8, f"structure-optimal max E-heat expected 8, got {mx_so}"
    print(f"  delivery separation  HA maxHeat={mx_ha}  SO maxHeat={mx_so}  OK")

    # projection exactness on a real atomic-closure dataset (guards load()'s inputs are closures)
    try:
        _check_projection("breast")
        print("  projection exact vs. true projected closure (breast)  OK")
    except (FileNotFoundError, KeyError, OSError):
        print("  projection check skipped (dataset files unavailable)")
    print("self-check passed.\n")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "exp":
        names = sys.argv[2:] or ["pdbx", "breast", "bridges", "echo"]
        exp(names)
    else:
        _selfcheck()
        for path in sys.argv[1:]:
            print(path)
            run(path)
