# -*- coding: utf-8 -*-
"""The curves the experiment section reports, on the delivery schema, priced offline.

Four questions the paper asks of a synthetic schema, each a sweep over one quantity with the
others held fixed.  Everything here is a row count from the model `delivery_schema` calibrated,
so a curve that does not separate here will not separate on a server either; the timings are
measured only for the sweeps that do.

    redundancy   what one update of each kind costs as the group a rule ranges over grows
    skew         what a whole window costs as the traffic moves from one hot operation to
                 the other, and where the two designs cross
    drift        the same window as the fraction of tuples that are in the scope grows
    misestimate  the window on the design each declaration returns, when the declaration is
                 right, blind, read off the data, or wrong

Usage: python delivery_curves.py [--json out.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import config as CFG
import delivery_schema as S

def result(name):
    """Where a result file goes, which the artifact keeps in one directory."""
    return os.path.join(CFG.RESULTS, name)


DEPTHS = (6, 12, 24, 48, 96, 192, 384)
OPS = ["reassign", "swap", "completion_clean", "completion_conflict", "insert_total"]


def inst_of(depth):
    """The instance whose district holds `depth` deliveries."""
    return S.Instance(couriers=6, branches=3, districts=2, days=depth * 2 // 3)


def two_designs():
    """The two families, taken from the declaration that reaches each.

    The closure admits four designs in two families whose costs differ by 0.4%, so the two
    the canonical listing returns stand for the families throughout.
    """
    out = {}
    for a in ("c", "v"):
        D = S.designs(S.op_heat({x: (10 if x == a else 1)
                                 for x in S.REFRESH.values()}))["HA"]
        out["cheap on " + a] = D
    assert len(out) == 2, out
    return out


def unit(rows, comp, a):
    """The tuples one update of the attribute in the middle of the instance writes."""
    return [rows[n] for n in comp[a][len(comp[a]) // 2]]


def one_op(inst, rows, comp, D, sup, op):
    """Rows one update of the given kind writes on one design."""
    if op in S.REFRESH:
        a = S.REFRESH[op]
        return S.change_cost(D, S.dets_of(S.AID[a]), unit(rows, comp, a),
                             {S.AID[a]: -1}, sup)["rows"]
    t = inst.fresh_tuple(0, 0, 10 ** 6)
    if op == "completion_clean":
        return S.entry_cost(D, t, sup, +1, remainder=1)["rows"]
    if op == "insert_total":
        return S.entry_cost(D, t, sup, +1)["rows"]
    return (S.entry_cost(D, t, sup, +1, remainder=1)["rows"]
            + S.change_cost(D, S.dets_of(S.AID["c"]), unit(rows, comp, "c"),
                            {S.AID["c"]: -1}, sup)["rows"])


def redundancy():
    """RQ1: one update of each kind, as the group a rule ranges over grows."""
    res = []
    for depth in DEPTHS:
        inst = inst_of(depth)
        rows = list(inst.rows())
        comp = {a: S.components(rows, S.AID[a]) for a in S.REFRESH.values()}
        named = two_designs()
        sup = {k: S.support(rows, D) for k, D in named.items()}
        for op in OPS:
            r = {k: one_op(inst, rows, comp, D, sup[k], op) for k, D in named.items()}
            res.append({"depth": inst.depth, "n": inst.n, "op": op, **r})
    return res


def skew_mixes(w, base="desk"):
    """A window whose two hot operations split a fixed budget in the ratio `w` to one."""
    mix = dict(S.MIXES[base])
    hot = mix["reassign"] + mix["swap"]
    mix["reassign"], mix["swap"] = hot * w / (w + 1), hot / (w + 1)
    return mix


def skew(depth=192, reps=1000, ws=(1 / 16, 1 / 8, 1 / 4, 1 / 2, 1, 2, 4, 8, 16)):
    """RQ4: the window on each design as the traffic moves between the hot operations."""
    inst = inst_of(depth)
    rows = list(inst.rows())
    comp = {a: S.components(rows, S.AID[a]) for a in S.REFRESH.values()}
    named = two_designs()
    res = []
    for w in ws:
        got, _ = S.window(inst, named, skew_mixes(w), reps)
        r = {k: got[k]["total"]["rows"] for k in named}
        res.append({"depth": inst.depth, "w": w, **r})
    return res


def drift(depth=192, reps=1000, fracs=(0.25, 0.5, 0.75, 1.0)):
    """RQ5a: the same window as the fraction of tuples that are in the scope grows.

    A tuple whose tracker is not yet registered sits outside the scope, so it is neither
    stored by the design nor counted by any rule; the sweep takes the first `frac` of each
    district into the scope and prices the window on what is left.
    """
    res = []
    for frac in fracs:
        inst = inst_of(depth)
        seen, rows, cap = {}, [], max(1, int(round(frac * inst.depth)))
        for t in inst.rows():
            k = t[S.AID["d"]]
            seen[k] = seen.get(k, 0) + 1
            rows.append(t if seen[k] <= cap else None)
        named = two_designs()
        got, _ = S.window(inst, named, S.MIXES["desk"], reps, rel=rows)
        r = {k: got[k]["total"]["rows"] for k in named}
        res.append({"depth": cap, "frac": frac,
                    "scope": sum(t is not None for t in rows), **r})
    return res


def misestimate(depth=192, reps=1000):
    """RQ5b: the window on the design each way of declaring the operations returns."""
    inst = inst_of(depth)
    rows = list(inst.rows())
    comp = {a: S.components(rows, S.AID[a]) for a in S.REFRESH.values()}
    res = []
    for name, mix in S.MIXES.items():
        cache = {}
        for ch in S.CHANNELS:
            r = S.run_window(inst, comp, mix, reps, ch, cache, name)
            for lab in S.ORDER:
                res.append({"depth": inst.depth, "mix": name, "channel": ch,
                            "design": lab, "rows": r[lab]["rows"],
                            "rows_max": r[lab]["rows_max"], "hmax": r[lab]["hmax"],
                            "designs": r[lab]["designs"]})
    return res


def main():
    out = {"redundancy": redundancy(), "skew": skew(), "drift": drift(),
           "misestimate": misestimate()}
    print("  redundancy: rows one update writes, by the group its rule ranges over")
    keys = [k for k in out["redundancy"][0] if k.startswith("cheap")]
    print(f"    {'group':>6}  {'operation':<22}" + "".join(f"{k:>16}" for k in keys)
          + "     ratio")
    for r in out["redundancy"]:
        v = [r[k] for k in keys]
        print(f"    {r['depth']:>6}  {r['op']:<22}" + "".join(f"{x:>16,}" for x in v)
              + f"   {max(v) / min(v):7.2f}x")

    print("\n  skew: rows one window of 1,000 updates writes, by the ratio of the two")
    print(f"    {'reassign:swap':>14}" + "".join(f"{k:>16}" for k in keys) + "     ratio")
    for r in out["skew"]:
        v = [r[k] for k in keys]
        w = f"{r['w']:.3g}:1" if r["w"] >= 1 else f"1:{1 / r['w']:.3g}"
        print(f"    {w:>14}" + "".join(f"{x:>16,}" for x in v)
              + f"   {v[0] / v[1]:7.2f}x")

    print("\n  drift: the same window, by the fraction of tuples that are in the scope")
    print(f"    {'in scope':>10}{'tuples':>10}" + "".join(f"{k:>16}" for k in keys)
          + "     ratio")
    for r in out["drift"]:
        v = [r[k] for k in keys]
        print(f"    {r['frac']:>9.0%}{r['scope']:>10,}" + "".join(f"{x:>16,}" for x in v)
              + f"   {max(v) / min(v):7.2f}x")

    print("\n  misestimate: the window on what each declaration returns, group "
          f"{out['misestimate'][0]['depth']}")
    print(f"    {'window':<8}{'declared':<10}" + "".join(f"{lab:>14}" for lab in S.ORDER)
          + "   HA pays")
    for name in S.MIXES:
        best = min(x["rows"] for x in out["misestimate"] if x["mix"] == name)
        for ch in S.CHANNELS:
            r = {x["design"]: x for x in out["misestimate"]
                 if x["mix"] == name and x["channel"] == ch}
            print(f"    {name:<8}{ch:<10}"
                  + "".join(f"{r[lab]['rows']:>14,}" for lab in S.ORDER)
                  + f"   {r['HA']['rows'] / best:6.2f}x")
    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
    else:
        p = result("rq4_rq5_curves.json")
    json.dump(out, open(p, "w"), indent=1)
    print(f"\n  written {p}")


if __name__ == "__main__":
    main()
