import sys, itertools
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import synthesis as B

# Courier-dispatch running example over R = {o,c,s,z,t,p}
# o=order c=courier s=status z=zone t=timeslot p=phone(proof-of-contact)
names = {0: 'o', 1: 'c', 2: 's', 3: 'z', 4: 't', 5: 'p'}
R = frozenset(range(6))

def nm(S):
    return ''.join(names[a] for a in sorted(S))

base = [
    ({0, 2, 3}, {4}),   # osz -> t
    ({0, 2, 4}, {3}),   # ost -> z
    ({0, 1, 2}, {3}),   # ocs -> z
    ({2, 3},    {1}),   # sz  -> c   (HOT mode, from pure eFD  p ⋉ sz->c)
    ({0, 1, 2}, {4}),   # ocs -> t
    ({1, 4},    {0}),   # ct  -> o
    ({0, 4},    {1}),   # ot  -> c
    ({0},       {5}),   # o   -> p
]
sigma0 = [(frozenset(l), frozenset(r)) for l, r in base]

# ---- atomic closure: all X->A implied, X reduced ----
attrs = sorted(R)
atomic = []
for k in range(1, len(attrs) + 1):
    for X in itertools.combinations(attrs, k):
        Xs = frozenset(X)
        cl = B.closure(Xs, sigma0)
        for A in sorted(cl - Xs):
            reduced = all(
                A not in B.closure(frozenset(Y), sigma0)
                for Y in itertools.combinations(X, k - 1)
            ) if k > 1 else True
            if reduced:
                atomic.append((Xs, frozenset({A})))
sigma_a = atomic
print(f"atomic closure ({len(sigma_a)} FDs):")
for l, r in sorted(sigma_a, key=lambda fd: (len(fd[0]), nm(fd[0]), nm(fd[1]))):
    print(f"  {nm(l)} -> {nm(r)}")

keys = B.minimal_keys(R, sigma_a)
print(f"\nminimal keys of R: {sorted(nm(k) for k in keys)}")

HOT = {(frozenset({2, 3}), frozenset({1})): 8}   # sz->c hot, everything else 1

prep = B.prepare(sigma_a)
print("\ncritical generating FDs (subschema | greedy-f | hotness):")
for fd in prep["crit"]:
    XA = fd[0] | fd[1]
    cool = B.coolest_nonkey_fds(XA, prep["proj"][XA], prep["mkeys"][XA], HOT)
    h = sum(B.fd_hot(g, HOT) for g in cool)
    print(f"  {nm(fd[0])}->{nm(fd[1])}  gen {nm(XA)} | f={len(prep['nonkey'][XA])} | H={h} | nonkey={[f'{nm(a)}->{nm(b)}' for a,b in cool]}")

for mode in ("so", "ha"):
    D = B.synthesize(R, sigma_a, keys, mode, HOT, prep)
    m = B.decomp_metrics(D, HOT)
    print(f"\n== {mode} ==")
    for XA, proj in sorted(D, key=lambda x: nm(x[0])):
        ks = B.minimal_keys(XA, proj)
        cool = B.coolest_nonkey_fds(XA, proj, ks, HOT)
        h = sum(B.fd_hot(g, HOT) for g in cool)
        tag = "BCNF" if not cool else f"critical H={h} nonkey={[f'{nm(a)}->{nm(b)}' for a,b in cool]}"
        print(f"  {nm(XA):6} keys={sorted(nm(k) for k in ks)}  {tag}")
    print(f"  hmax={m['hmax']} htot={m['htot']} size={m['size']} bcnf={m['bcnf']} crit={m['crit']}")
    # dependency preservation: union of projections must imply every FD of sigma_a
    union = [fd for _, proj in D for fd in proj]
    dp = all(r <= B.closure(l, union) for l, r in sigma_a)
    lossless = any(any(k <= XA for k in keys) for XA, _ in D)
    print(f"  dependency-preserving={dp}  lossless(key-contained)={lossless}")
