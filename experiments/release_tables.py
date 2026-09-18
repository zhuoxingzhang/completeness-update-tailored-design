r"""Table 8 and Figure 8 of the paper: the priced updates of the real release under the observed and
the re-numbered levels.

release_maps.py runs the window live under each map of the levels, with every subschema indexed on
its minimal keys alone and non-key FDs refreshed through trigger tables.  This reads those runs,
checks that every pass is correct, and writes the table and the figure with every number the prose
of the paper quotes, so that no number in the text is transcribed by hand.  The window statistics
come from the record release_live.py kept of the same window, since they do not depend on how a
design is maintained, and the heat of each design from release_rules.py, which rebuilds the picked
designs under the heat convention in force.

A map is summarized over the passes it has.  Times are means over positions; the per-round
multiples of HA under the observed levels stay in real_maps.json.  The blocks are written once
every map has a pass for every design, or with PARTIAL=1 from the maps run so far.

Usage: python release_tables.py [<tag>]          default owid
Environment: PARTIAL=1, BLOCKS (another directory for the blocks, default results/blocks), WIN_MAP
             and SUMMARY (another record to read and summary to write, for testing the layout)
Writes results/rq7_real_summary.json and results/blocks/tab_real_maps.tex, fig_real_maps.tex,
       real_maps.json, real_maps.txt
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config as CFG

BLOCKS = os.environ.get("BLOCKS", os.path.join(CFG.RESULTS, "blocks"))
TAG = sys.argv[1] if len(sys.argv) > 1 else "owid"
VARS = "3NF=priced_worst,SO=hottest,HA=priced_best"
MAPS = ("obs", "sq", "exp2", "cube")
TEX = {"obs": r"$\ell$", "sq": r"$\ell^2$", "exp2": r"$2^{\ell}$", "cube": r"$\ell^3$"}
WANT = {"obs": 3, "sq": 1, "exp2": 1, "cube": 1}       # the passes the series runs per map
ORDER = ("3NF", "SO", "HA")
BASE = ("3NF", "SO")
PARTIAL = os.environ.get("PARTIAL") == "1"


def th(x):
    """A thousands separator LaTeX renders as one, which the paper writes {,} and not \\,."""
    return f"{int(x):,}".replace(",", "{,}")


def one(x):
    """Half away from zero, since round() would send a tie to the even digit."""
    return math.floor(x * 10 + 0.5) / 10


def two(x):
    return math.floor(x * 100 + 0.5) / 100


def bal(pos, xs):
    """The mean over positions of the mean within a position, so an unequal cell cannot tilt it."""
    by = {}
    for p, x in zip(pos, xs):
        by.setdefault(p, []).append(x)
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def rx(v):
    """Multiples as the figures write them: two digits under ten, one under a thousand."""
    return th(round(v)) if v >= 1000 else (f"{one(v):.1f}" if v >= 10 else f"{two(v):.2f}")


held = json.load(open(os.environ.get("WIN_MAP", os.path.join(CFG.RESULTS, "rq7_real_maps.json"))))
e2e = json.load(open(os.path.join(CFG.RESULTS, "rq7_real_live.json")))[f"{TAG}:{VARS}"]
# The heat of a design is read from rq7_real_rules.json, which rebuilds the picked designs under the
# heat convention in force (the floor of 1 of release_cost.HEAT_FLOOR), while rq7_real_live.json
# keeps the heats the run computed; the sizes have to agree.
_rules = os.path.join(CFG.RESULTS, "rq7_real_rules.json")
if os.path.exists(_rules):
    _rd = json.load(open(_rules))["designs"]
    for _k in ORDER:
        assert _rd[_k]["size"] == e2e["designs"][_k]["size"], (_k, _rd[_k]["size"], e2e["designs"][_k]["size"])
        e2e["designs"][_k]["htot"] = _rd[_k]["htot"]
        e2e["designs"][_k]["hmax"] = _rd[_k]["hmax"]
    print(f"heats read from {_rules}: " + ", ".join(f"{k} htot {e2e['designs'][k]['htot']:,}" for k in ORDER))
SUMMARY = os.environ.get("SUMMARY", os.path.join(CFG.RESULTS, "rq7_real_summary.json"))
maps, out = {}, []
for m in MAPS:
    res = held.get(f"{TAG}:{m}:{VARS}:keys+G")
    if not res:
        continue
    ds = res["designs"]
    done = min(len(ds[k]["priced_s"]) for k in ORDER)
    if done == 0:
        continue
    rec = {"priced_updates": res["priced_updates"], "passes": done, "complete": done >= WANT[m],
           "quiet_pause": res.get("quiet_pause", 0), "visit_plan": res.get("visit_plan", []),
           "levels": res["levels"], "designs": {}}
    for k in ORDER:
        r = ds[k]
        assert r["size"] == e2e["designs"][k]["size"], f"{m} {k}: not the design release_live.py ran"
        assert all(not v for v in r["violations"][:done]), f"{m} {k}: violations {r['violations']}"
        assert all(x[0] == 0 for x in r["mismatch"][:done]), f"{m} {k}: rowcount mismatches {r['mismatch']}"
        pos, ts, a = r["position"][:done], r["priced_s"][:done], r["acct"]
        rec["designs"][k] = {"positions": pos, "priced_s": ts, "mean_s": bal(pos, ts),
                             "statements": a.get("priced_stmts", 0), "rows": a.get("priced_rows", 0),
                             "group_rows": a.get("charged_rows", 0), "g_refreshes": a.get("priced_gu", 0),
                             "g_admissions": a.get("priced_ga", 0), "g_resets": a.get("priced_gd", 0),
                             "g_rules": len(r["g_rules"]), "plain_rules": len(r["g_failed"]),
                             "pass_s": r["rounds_s"][:done]}
    h = rec["designs"]["HA"]
    rec["over_ha"] = {k: rec["designs"][k]["mean_s"] / h["mean_s"] for k in BASE}
    rec["round_over_ha"] = {k: [t / u for t, u in zip(rec["designs"][k]["priced_s"], h["priced_s"])]
                            for k in BASE}
    rec["ha_fastest_every_round"] = all(
        h["priced_s"][i] < min(rec["designs"][k]["priced_s"][i] for k in BASE) for i in range(done))
    maps[m] = rec
    out.append(f"{m}: {res['priced_updates']:,} priced updates, {done} pass(es)"
               + ("" if rec["complete"] else f" of {WANT[m]}"))
    for k in ORDER:
        d = rec["designs"][k]
        out.append(f"  {k:4s} pos {d['positions']}  priced {', '.join(f'{t:.1f}' for t in d['priced_s'])} s"
                   f"  mean {d['mean_s']:.1f} s"
                   + ("" if k == "HA" else f"  x{rec['over_ha'][k]:.3f} of HA (rounds "
                      + ", ".join(f"{x:.3f}" for x in rec["round_over_ha"][k]) + ")")
                   + f"   stmts {d['statements']:,} rows {d['rows']:,} group rows {d['group_rows']:,}"
                   f"   G {d['g_refreshes']:,} refreshes, {d['g_admissions']} admissions, {d['g_resets']} resets"
                   f"   passes {d['pass_s']}")
    out.append(f"  HA fastest in every round: {rec['ha_fastest_every_round']}")

json.dump({"tag": TAG, "pickvar": VARS, "maps": maps}, open(SUMMARY, "w"), indent=1)
print("\n".join(out))
ready = [m for m in MAPS if m in maps and (maps[m]["complete"] or PARTIAL)]
if "obs" not in ready or (len(ready) < len(MAPS) and not PARTIAL):
    print("\nthe blocks wait for every map" + (" (obs first)" if "obs" not in ready else ""))
    raise SystemExit


def table():
    d, pa, rel = e2e["designs"], e2e["priced_attrs"], e2e["relation"]
    assert maps["obs"]["priced_updates"] == e2e["priced_updates"]
    obs = maps["obs"]["designs"]
    window = [("tuples", rel["tuples"]), ("tuples in the scope", e2e["scope"]),
              ("atomic FDs of the reduct", rel["reduct"]), ("minimal keys", rel["keys"]),
              (f"refreshes of the {len(pa)} priced attributes", e2e["priced_events"]),
              ("priced updates they coalesce into", e2e["priced_updates"])]
    sec = lambda x: f"{x:,.1f}".replace(",", "{,}")
    rows = [("subschemata", {k: d[k]["size"] for k in ORDER}, th, False),
            ("total heat", {k: d[k]["htot"] for k in ORDER}, th, True),
            r"\emph{the " + th(e2e["priced_updates"]) + " priced updates}",
            ("statements", {k: obs[k]["statements"] for k in ORDER}, th, True),
            ("rows written", {k: obs[k]["rows"] for k in ORDER}, th, True),
            ("group rows", {k: obs[k]["group_rows"] for k in ORDER}, th, True),
            ("refresh time (s)", {k: one(obs[k]["mean_s"]) for k in ORDER}, sec, True)]
    if len(ready) > 1:
        rows.append(r"\emph{refresh time (s) under re-numbered levels}")
        rows += [(f"{TEX[m]}, {th(maps[m]['priced_updates'])} priced updates",
                  {k: one(maps[m]["designs"][k]["mean_s"]) for k in ORDER}, sec, True) for m in ready[1:]]
    # two tabulars across the column, the window's counts in two label-value columns, then the
    # designs, joined by \nointerlineskip
    L = [r"\begin{tabular*}{\columnwidth}{@{\extracolsep{\fill}}l r l r@{}}", r"\toprule",
         r"\multicolumn{4}{@{}l}{\emph{the window}}\\"]
    for i in range(0, len(window), 2):
        pair = window[i:i + 2]
        L.append(" & ".join([c for nm, v in pair for c in (nm, th(v))] + ["", ""] * (2 - len(pair))) + r"\\")
    # the heading rows: a block's name (already in italics), then the three designs
    head = lambda cell: " & ".join([cell] + [r"\emph{" + k + "}" for k in ORDER]) + r"\\"
    L += [r"\midrule", r"\end{tabular*}\par\nointerlineskip",
          r"\begin{tabular*}{\columnwidth}{@{\extracolsep{\fill}}l rrr@{}}", head(r"\emph{the designs}")]
    for row in rows:
        if isinstance(row, str):
            L += [r"\midrule", head(row)]
            continue
        nm, v, f, mark = row
        low = min(v.values())
        solo = list(v.values()).count(low) == 1
        L.append(nm + " & " + " & ".join((r"\textbf{" + f(v[k]) + "}") if mark and solo and v[k] == low
                                         else f(v[k]) for k in ORDER) + r"\\")
    L += [r"\bottomrule", r"\end{tabular*}"]
    return "\n".join(L) + "\n"


def figure():
    """3NF and SO as multiples of HA, one point per numbering of the levels."""
    # the plot styles of the paper's preamble: exfig A for SO, C for 3NF, and HA's colour for its line;
    # a label takes the colour of its line and clears its mark (the diamond of 3NF is the taller)
    COL = {"3NF": ("exfig C", "orange!80!black", "2pt"), "SO": ("exfig A", "blue!80!black", "1pt")}
    n = len(ready)
    val = {k: [maps[m]["over_ha"][k] for m in ready] for k in BASE}
    top = max(max(val[k]) for k in BASE)
    # a log axis in doublings: on a linear axis from 0 the label of SO at l^2 ran into the line of 3NF,
    # which lies only 1.2 units higher; the label above the highest point needs about 0.45 of a doubling
    ymax = 2 ** math.ceil(math.log2(top * 1.4))
    ticks = ",".join(str(2 ** i) for i in range(0, int(math.log2(ymax)) + 1))
    # a legend sample is drawn at the middle of its name's box, and the box the font gives the names put
    # that middle 0.6pt below the middle of the capitals; a box as tall as the capitals of \scriptsize
    # (3.9pt) with no depth centres each line on its name, as exfig small legend does for the swatches
    q = [r"\begin{tikzpicture}",
         r"\begin{axis}[",
         r"  height=3.4cm, width=0.9\columnwidth,",
         f"  xmin=0.6, xmax={n + 0.4:g}, xtick={{{','.join(str(i) for i in range(1, n + 1))}}},",
         "  xticklabels={" + ",".join(TEX[m] for m in ready) + "},",
         r"  xlabel={levels}, ylabel={refresh time ($\times$ HA)},",
         f"  ymode=log, log basis y=2, ymin=0.8, ymax={ymax}, ytick={{{ticks}}}, yticklabels={{{ticks}}},",
         r"  exfig, grid=major,",
         r"  legend columns=3, legend style={draw=none, fill=none, at={(0.5,1.02)},",
         r"                anchor=south, /tikz/every even column/.append style={column sep=6pt},",
         r"                nodes={text height=3.9pt, text depth=0pt}},",
         r"]",
         f"\\draw[red!80!black, densely dashed, thick] (axis cs:0.6,1) -- (axis cs:{n + 0.4:g},1);"]
    for k in BASE:
        style, c, lift = COL[k]
        pts = [f"({i},{v:.4f}) [${rx(v)}\\times$]" for i, v in enumerate(val[k], start=1)]
        # the line of 3NF is one step heavier than exfig's thick, and its marks keep the thick outline,
        # which would otherwise fill the light core of the diamonds; SO keeps exfig's thick
        weight = "very thick, every mark/.append style={thick}, " if k == "3NF" else ""
        q += [f"\\addplot[{style}, {weight}nodes near coords, point meta=explicit symbolic,",
              f"         nodes near coords style={{font=\\tiny, {c}, anchor=south, yshift={lift}}}]"
              " coordinates {" + " ".join(pts) + "};"]
    q += [r"\addlegendimage{red!80!black, densely dashed, thick}", r"\legend{3NF, SO, HA}",
          r"\end{axis}", r"\end{tikzpicture}"]
    return "\n".join(q) + "\n"


nums = {"maps": ready, "priced_events": e2e["priced_events"], "priced_updates_obs": e2e["priced_updates"]}
for m in ready:
    rec = maps[m]
    nums[f"{m}_priced_updates"] = rec["priced_updates"]
    nums[f"{m}_passes"] = rec["passes"]
    nums[f"{m}_quiet_pause"] = rec["quiet_pause"]
    nums[f"{m}_ha_fastest_every_round"] = rec["ha_fastest_every_round"]
    for k in ORDER:
        d = rec["designs"][k]
        nums[f"{m}_{k}_s"] = one(d["mean_s"])
        nums[f"{m}_{k}_statements"] = d["statements"]
        nums[f"{m}_{k}_rows"] = d["rows"]
        nums[f"{m}_{k}_group_rows"] = d["group_rows"]
    for k in BASE:
        nums[f"{m}_{k}_over_HA"] = two(rec["over_ha"][k])
        nums[f"{m}_{k}_over_HA_rows"] = two(rec["designs"][k]["rows"] / max(rec["designs"]["HA"]["rows"], 1))
        nums[f"{m}_{k}_over_HA_statements"] = two(rec["designs"][k]["statements"]
                                                  / max(rec["designs"]["HA"]["statements"], 1))
        nums[f"{m}_{k}_over_HA_round_lo"] = two(min(rec["round_over_ha"][k]))
        nums[f"{m}_{k}_over_HA_round_hi"] = two(max(rec["round_over_ha"][k]))
for k in BASE:
    xs = [maps[m]["over_ha"][k] for m in ready]
    nums[f"{k}_over_HA_min"], nums[f"{k}_over_HA_max"] = two(min(xs)), two(max(xs))
    nums[f"{k}_over_HA_min_map"] = ready[xs.index(min(xs))]
    nums[f"{k}_over_HA_max_map"] = ready[xs.index(max(xs))]
nums["ha_fastest_everywhere"] = all(maps[m]["ha_fastest_every_round"] for m in ready)
if all(m in ready for m in MAPS[1:]):
    # one pass per map, so no map balances positions within itself: record where each design ran, and
    # whether 3NF, which writes several times the rows of the others, ran last under every map
    nums["maps_positions_latin"] = all(
        sorted(maps[m]["designs"][k]["positions"][0] for m in MAPS[1:]) == [1, 2, 3] for k in ORDER)
    nums["maps_3NF_last"] = all(maps[m]["designs"]["3NF"]["positions"][0] == 3 for m in MAPS[1:])
    for m in MAPS[1:]:
        for k in ORDER:
            nums[f"{m}_{k}_position"] = maps[m]["designs"][k]["positions"][0]
for k in ORDER:
    nums[f"{k}_htot"] = e2e["designs"][k]["htot"]
    nums[f"{k}_size"] = e2e["designs"][k]["size"]

os.makedirs(BLOCKS, exist_ok=True)
open(os.path.join(BLOCKS, "tab_real_maps.tex"), "w").write(table())
open(os.path.join(BLOCKS, "fig_real_maps.tex"), "w").write(figure())
json.dump(nums, open(os.path.join(BLOCKS, "real_maps.json"), "w"), indent=1)
open(os.path.join(BLOCKS, "real_maps.txt"), "w").write("\n".join(out) + "\n")
print(f"\nwritten {BLOCKS}: tab_real_maps.tex, fig_real_maps.tex, real_maps.json, real_maps.txt"
      + ("   (PARTIAL)" if len(ready) < len(MAPS) or not all(maps[m]["complete"] for m in ready) else ""))
