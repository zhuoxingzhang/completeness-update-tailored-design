# -*- coding: utf-8 -*-
"""Figure 7 of the paper: the refreshes that every rule of the reduct receives in the real release.

A rule X -> a of the reduct has the heat theta = the number of refreshes of a inside the scope, so
every rule that determines an attribute receives that attribute's count, whether a design maintains
the rule through a key or as a non-key FD (the co-refresh lemma of the paper).  The script reads the
inputs of the timed runs and does not load the relation:
  - the reduct, from the orders the designs are synthesized from (results/rq7_real_picks.json);
  - the attribute names, from the constraint set (data/release/<tag>_fds.json);
  - the refreshes and priced updates of every priced attribute, from the run record in
    results/rq7_real_live.json.
release_cost.coalesce counts the events of an attribute exactly as theta does, and it gives every
refreshed attribute that some rule determines a non-empty determinant, so an attribute that a rule
determines but that priced_attrs lacks is never refreshed in the scope (asserted below: no rule has
an empty determinant).  The rules that determine one attribute receive one count and take
consecutive ranks, so each attribute is drawn as one bar over its ranks.  The figure uses the plot
styles of the paper's preamble (exfig, its small legend and swatch).

Usage: python release_skew.py [<tag>]          default owid
Environment: PICK (default results/rq7_real_picks.json), BLOCKS (default results/blocks)
Writes results/blocks/fig_real_skew.tex (the tikzpicture) and real_skew.json (the numbers the prose
cites), and prints the counts per attribute.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config as CFG

BLOCKS = os.environ.get("BLOCKS", os.path.join(CFG.RESULTS, "blocks"))
TAG = sys.argv[1] if len(sys.argv) > 1 else "owid"
RUN = f"{TAG}:3NF=priced_worst,SO=hottest,HA=priced_best"
PICK = os.environ.get("PICK", os.path.join(CFG.RESULTS, "rq7_real_picks.json"))
# refreshed attribute -> legend entry
LABEL = {"aged_65_older": "aged 65 and older", "cardiovasc_death_rate": "cardiovascular death rate",
         "gdp_per_capita": "GDP per capita", "population_density": "population density",
         "human_development_index": "human development index",
         "hospital_beds_per_thousand": "hospital beds", "location": "location"}
# per attribute in rank order: the tint, the darker shade of its outline and pattern, and the pattern
FILLS = [("blue!10", "blue!65!black", "Lines[angle=45, distance=1.8pt, line width=0.35pt]"),
         ("orange!16", "orange!80!black", "Lines[angle=-45, distance=1.8pt, line width=0.35pt]"),
         ("teal!12", "teal!70!black", "Hatch[angle=45, distance=2.2pt, line width=0.3pt]"),
         ("brown!14", "brown!70!black", "Lines[angle=0, distance=1.6pt, line width=0.35pt]"),
         ("violet!10", "violet!70!black", "Dots[radius=0.35pt, distance=1.6pt]"),
         ("red!10", "red!70!black", "Lines[angle=90, distance=1.8pt, line width=0.35pt]"),
         ("gray!12", "gray!70!black", "Hatch[angle=0, distance=2.2pt, line width=0.3pt]")]
HOT = 0.5    # an attribute is hot if it receives at least half the refreshes of the hottest one

names = json.load(open(os.path.join(CFG.REPO, "data", "release", f"{TAG}_fds.json"), encoding="utf-8"))["attrs"]
orders = json.load(open(PICK))[TAG]
reducts = {frozenset((frozenset(l), frozenset(r)) for l, r in rec["fds"])
           for design in orders.values() for rec in design.values()}
assert len(reducts) == 1, "the order file holds different reducts"
reduct = next(iter(reducts))
assert all(len(r) == 1 and l and not l & r for l, r in reduct), \
    "a rule is not atomic, is trivial, or has an empty determinant"
run = json.load(open(os.path.join(CFG.RESULTS, "rq7_real_live.json")))[RUN]
assert run["relation"]["reduct"] == len(reduct), "the run record and the order file disagree on the reduct"
priced = run["priced_attrs"]
assert sum(p["events"] for p in priced.values()) == run["priced_events"]
assert sum(p["updates"] for p in priced.values()) == run["priced_updates"]

rules = collections.Counter(names[next(iter(r))] for _, r in reduct)
assert set(priced) <= set(rules), "a priced attribute that no rule determines"
refreshed = sorted(priced, key=lambda a: (-priced[a]["events"], a))
assert set(refreshed) == set(LABEL), "a refreshed attribute without a legend entry"
assert len(refreshed) <= len(FILLS)
cold = sorted(a for a in rules if a not in priced)
top = priced[refreshed[0]]["events"]
hot = [a for a in refreshed if priced[a]["events"] >= HOT * top]

blocks, first = [], 1
for a in refreshed:
    blocks.append({"attr": a, "label": LABEL[a], "rules": rules[a], "refreshes": priced[a]["events"],
                   "updates": priced[a]["updates"], "first": first, "last": first + rules[a] - 1})
    first += rules[a]
N = len(reduct)
refreshed_rules = first - 1
hot_rules = sum(rules[a] for a in hot)
assert [b["attr"] for b in blocks[:len(hot)]] == hot, "the hot attributes do not rank first"
bars = sum(b["rules"] * b["refreshes"] for b in blocks)
nums = {"tag": TAG, "run": RUN, "rules": N, "refreshed_attrs": len(refreshed),
        "refreshed_rules": refreshed_rules, "cold_attrs": len(cold), "cold_rules": N - refreshed_rules,
        "cold": cold, "hot_attrs": len(hot), "hot": hot, "hot_rules": hot_rules,
        "priced_events": run["priced_events"], "priced_updates": run["priced_updates"],
        "hot_share_of_bars": sum(rules[a] * priced[a]["events"] for a in hot) / bars,
        "hot_share_of_refreshes": sum(priced[a]["events"] for a in hot) / run["priced_events"],
        "hot_share_of_priced_updates": sum(priced[a]["updates"] for a in hot) / run["priced_updates"],
        "blocks": blocks}
assert nums["cold_rules"] == sum(rules[a] for a in cold)

print(f"{TAG}: {N:,} rules, {refreshed_rules:,} determine one of {len(refreshed)} refreshed attributes, "
      f"{nums['cold_rules']:,} determine one of {len(cold)} attributes the window never refreshes")
for b in blocks:
    print(f"  ranks {b['first']:5d}-{b['last']:5d}  {b['attr']:28s} {b['rules']:4d} rules "
          f"{b['refreshes']:7,d} refreshes {b['updates']:4d} priced updates")
print(f"  never refreshed: {', '.join(f'{a} ({rules[a]})' for a in cold)}")
print(f"  the {len(hot)} hot attributes: {100 * nums['hot_share_of_bars']:.2f}% of the bars, "
      f"{100 * nums['hot_share_of_refreshes']:.2f}% of the refreshes, "
      f"{100 * nums['hot_share_of_priced_updates']:.2f}% of the priced updates")

# log axis from the decade at or below the least refreshed attribute to the decade at or above the hottest
assert blocks[-1]["refreshes"] > 0
LOW = 1
while 10 * LOW <= blocks[-1]["refreshes"]:
    LOW *= 10
TOP = 1
while TOP < top:
    TOP *= 10
ticks = [LOW]
while ticks[-1] < TOP:
    ticks.append(10 * ticks[-1])
out = [r"\begin{tikzpicture}",
       r"\begin{axis}[",
       r"  width=0.98\linewidth, height=3.4cm,",
       f"  xmin=0.5, xmax={N}.5, xtick={{1,{hot_rules},{refreshed_rules},{N}}},",
       f"  ymode=log, log origin=infty, ymin={LOW}, ymax={TOP}, ytick={{{','.join(map(str, ticks))}}}, log ticks with fixed point, yminorticks=false,",
       r"  xlabel={rule rank}, ylabel={refreshes},",
       r"  exfig, ymajorgrids, xtick pos=left, ytick pos=left,",
       r"  exfig small legend, legend pos=north east,",
       r"]"]
for (tint, shade, pattern), b in zip(FILLS, blocks):
    # one bar over the ranks of the attribute's rules, which all receive its count
    out += [f"\\addplot[ybar interval, fill={tint}, draw={shade}, line width=0.4pt, exfig swatch,",
            f"  postaction={{pattern={{{pattern}}}, pattern color={shade}}}]",
            f"  coordinates {{({b['first'] - 0.5:g},{b['refreshes']}) ({b['last'] + 0.5:g},{b['refreshes']})}};"
            f" \\addlegendentry{{{b['label']}}}"]
out += [r"\end{axis}", r"\end{tikzpicture}"]
os.makedirs(BLOCKS, exist_ok=True)
open(os.path.join(BLOCKS, "fig_real_skew.tex"), "w", encoding="utf-8").write("\n".join(out) + "\n")
json.dump(nums, open(os.path.join(BLOCKS, "real_skew.json"), "w", encoding="utf-8"), indent=1)
print(f"wrote {os.path.join(BLOCKS, 'fig_real_skew.tex')} and real_skew.json")
