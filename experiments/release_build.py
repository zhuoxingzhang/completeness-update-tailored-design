r"""The two windows of the real release: the COVID table of Our World in Data on 31 March, 30 June
and 19 August 2024.

A window is a pair of editions.  Its relation is the earlier edition, restricted to the
country-days that carry the four core surveillance indicators and to the columns below.  Its
workload is the difference between the two editions, one event per cell that changed, in the order
of the rows and of the columns: a cell that changes its value is a refresh, one that becomes
non-null a completion, and one that becomes null a retraction.

The mining window runs from the edition of 31 March to the base edition of 30 June: the
constraints are mined on its relation (release_mine.py) and its updates give the heat
(release_cost.declare).  The release window runs from the base edition to the edition of
19 August: its relation is what the designs store, and its updates are the ones that are timed.
The end state is the released edition, so every update is one the publisher issued.

The editions are read from a clone of the publisher's repository, which keeps every edition of
the table in its history:

    git clone --filter=blob:none --no-checkout https://github.com/owid/covid-19-data <scratch>/owid

Usage: python release_build.py [<clone>] [<tag>]
       the clone defaults to CUTD_OWID_REPO, then to <scratch>/owid; the tag to owid
Environment: COLS=a,b,... restricts the relations to other columns of the table, in that order;
             they have to contain the four core indicators, which fix the rows.  The default is the
             column set of the paper.
Writes <scratch>/<tag>_mining_relation.pkl and <scratch>/<tag>_relation.pkl, the mining and the
release window: the attribute names, the tuples of the earlier edition, and the events, each with
its row, attribute, old and new value and kind.
"""
import collections
import csv
import io
import os
import pickle
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import config as CFG

PATH = "public/data/owid-covid-data.csv"
MINING = "f6ff01283d585841ed06d736dcaba146629fde99"       # the edition of 31 March 2024
BASE = "257e9651175ff5b90b05845509e2d5ed0a9e46ac"         # the edition of 30 June 2024
RELEASE = "f0d53320b19703cf565940d8269181a8423d7032"      # the edition of 19 August 2024
CORE = ["reproduction_rate", "stringency_index",
        "new_cases_smoothed_per_million", "new_deaths_smoothed_per_million"]
KEEP = ["location", "continent"] + CORE + [
    "new_vaccinations_smoothed_per_million", "positive_rate",
    "people_vaccinated_per_hundred", "population_density", "median_age",
    "aged_65_older", "gdp_per_capita", "extreme_poverty",
    "cardiovasc_death_rate", "diabetes_prevalence",
    "hospital_beds_per_thousand", "life_expectancy", "human_development_index",
    "total_cases_per_million", "total_deaths_per_million",
    "female_smokers", "male_smokers"]
if os.environ.get("COLS"):
    KEEP = [c for c in os.environ["COLS"].split(",") if c]
assert all(c in KEEP for c in CORE), "the rows kept are the ones carrying the core indicators"


def read(repo, sha):
    raw = subprocess.run(["git", "-C", repo, "show", f"{sha}:{PATH}"], capture_output=True)
    if raw.returncode:
        raise SystemExit(f"git show failed in {repo}: {raw.stderr.decode('utf-8', 'replace').strip()}")
    rd = csv.reader(io.StringIO(raw.stdout.decode("utf-8", "replace")))
    head = next(rd)
    ix = {c: i for i, c in enumerate(head)}
    take = {a: ix[a] for a in ["iso_code", "date"] + KEEP if a in ix}
    mx, out = max(take.values()), {}
    for r in rd:
        if len(r) <= mx:
            continue
        row = {a: (sys.intern(r[i].strip()) if r[i].strip() else None) for a, i in take.items()}
        for a in KEEP:
            row.setdefault(a, None)
        if row.get("iso_code") and row.get("date"):
            out[(row["iso_code"], row["date"])] = row
    return out


def window(r0, r1, name, tag):
    """One window: the relation of the earlier edition r0 and the events that lead to r1."""
    shared = r0.keys() & r1.keys()
    keys = [k for k in sorted(shared) if all(r0[k][c] is not None for c in CORE)]
    print(f"{name}: {len(r0)} / {len(r1)} country-days, {len(shared)} shared, "
          f"{len(keys)} carry all four core indicators in the earlier edition")
    data = [tuple(r0[k][c] for c in KEEP) for k in keys]
    log = []
    for i, k in enumerate(keys):
        for c in KEEP:
            x, y = r0[k][c], r1[k][c]
            if x == y:
                continue
            kind = ("refresh" if x is not None and y is not None else
                    "completion" if x is None else "retraction")
            log.append({"i": i, "attr": c, "old": x, "new": y, "kind": kind})
    print(f"{tag}: {len(data)} tuples x {len(KEEP)} attrs; {len(log)} events "
          f"{dict(collections.Counter(e['kind'] for e in log))}")
    per = collections.defaultdict(collections.Counter)
    for e in log:
        per[e["attr"]][e["kind"]] += 1
    for i, c in enumerate(KEEP):
        g = collections.Counter(r[i] for r in data if r[i] is not None)
        nn = sum(1 for r in data if r[i] is None)
        print(f"  {c:38s} null {100 * nn / len(data):5.1f}% distinct {len(g):7d} "
              f"maxgroup {max(g.values()) if g else 0:7d}  {dict(per[c])}")
    out = os.path.join(CFG.scratch_dir(), f"{tag}_relation.pkl")
    pickle.dump({"attrs": KEEP, "data": data, "events": log, "block": list(KEEP)},
                open(out, "wb"), protocol=4)
    print(f"written {out}")


def main(repo, tag):
    mining, base = read(repo, MINING), read(repo, BASE)
    window(mining, base, f"mining window {MINING[:7]} -> {BASE[:7]}", f"{tag}_mining")
    del mining
    window(base, read(repo, RELEASE), f"release window {BASE[:7]} -> {RELEASE[:7]}", tag)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else CFG.owid_repo(), args[1] if len(args) > 1 else "owid")
