# Completeness- and Update-Tailored Database Design — Artifact

Implementation, declared constraint sets, workload generators, and result files
for the paper *Completeness- and Update-Tailored Database Design*.

The paper introduces normal forms that bound, over the completeness scope of an
application, the **update heat** a design materializes redundantly, together with
a synthesis algorithm that minimizes the maximal subschema heat among the designs
synthesis reaches. This repository lets you re-run every experiment.

## What is here

```
src/
  synthesis.py     the synthesis engine: FD primitives, minimal keys, the
                   non-key FDs and heat of a schema, and one skeleton carrying
                   every objective. Run it directly for a self-check.
  config.py        paths and database credentials, all overridable by environment
                   variables. The only file you may need to touch.
experiments/       one script per research question (table below)
data/fd/           the declared constraint sets: atomic closures mined from the
                   benchmark relations under both NULL readings
results/           the result files behind the paper's tables and figures
```

### The three objectives

All experiments compare three synthesizers that share one front end — the reduct
`Sigma[E]`, its atomic closure, and the key computations — so that the objective
is the only variable:

| key   | objective |
|-------|-----------|
| `3nf` | classical lossless, dependency-preserving 3NF synthesis |
| `so`  | structure-optimal: fewest procedurally maintained FDs per subschema |
| `ha`  | heat-aware: Algorithm 1 of the paper |

`so` and `ha` differ in one line — which redundant critical schemata are
eliminated first. That line is what the experiments measure.

## Quick start (no database needed)

```bash
python src/synthesis.py
```

This runs the engine's self-check on the delivery running example of the paper.
It verifies that every objective returns a lossless, dependency-preserving
design, and reproduces the separation of Figure 1: the structure-optimal design
has maximal subschema heat 8, the heat-aware design has 2.

```bash
python experiments/delivery_example.py
```

prints the six-tuple snapshot of Table 1 and both designs of Figure 1 subschema
by subschema, with their minimal keys and the rows each one stores, and checks
the snapshot against the rules it illustrates.

```bash
python experiments/delivery_schema.py --orders
```

shuffles the atomic closure 200 times and reports the design each objective
returns on each listing. Both objectives break ties by input order, so this is
what says whether a separation rests on the criterion or on the tie break.

```bash
python experiments/reduct_frontend.py
```

reproduces Tables 3 and 4 (maximal and total design heat on twenty reducts of
real incomplete relations, and the sweep over `p`) from the shipped constraint
sets, sweeping the graded declaration over ten values of `p`, from 0.1 to 1 in
steps of 0.1, with twenty draws each. About two hours on 18 workers, dominated
by hepatitis under equality; set `CUTD_WORKERS` to match your machine. The per-synthesis times it records are
inflated by parallel contention; the synthesis times quoted in the paper were measured with
`CUTD_WORKERS=1`. Writes `results/rq2_reducts.json`.

## Reproducing the experiments

| Script | Produces |
|---|---|
| `experiments/delivery_example.py` | Table 1 and Figure 1 |
| `experiments/delivery_trace.py` | Examples "Heat of the delivery subschemata" and "Synthesis on the delivery reduct": the eliminations each objective performs, the number it ranks by, and the heat of the reduct and of every subschema a design keeps |
| `experiments/delivery_schema.py` | the schema, the instance generator and the offline cost model the other delivery scripts import; `--orders` for the order study above, `--costs` for the rows one update of each kind rewrites, `--window` for `results/rq7_window_model.json` |
| `experiments/delivery_live.py --ops` | Figure 2 and Table 3 (RQ1, one update of each kind over group depths; `results/rq1_operations.json`) † |
| `experiments/delivery_live.py --mixed` | Figure 4 and the first row of Table 7 (RQ3, refreshes with a growing completion share; `results/rq3_mixed.json`) † |
| `experiments/delivery_live.py --reads` | Table 7 (RQ3, reconstruction, key lookups, history, storage; `results/rq3_reads.json`) † |
| `experiments/delivery_live.py` | Table 10 and Figure 8 (RQ7, one maintenance window under three rate profiles; `results/rq7_window.json`) † |
| `experiments/delivery_curves.py` | Figure 5 and Table 8 (RQ4 and RQ5, skew, completeness drift, and the four declarations; `results/rq4_rq5_curves.json`) |
| `experiments/delivery_tables.py` | every figure and table of the delivery study as LaTeX, from the result files above |
| `experiments/reduct_frontend.py` | Table 4 (RQ2, maximal and total design heat at `p = 0.5`) and Table 5 (the sweep over `p`); `results/rq2_reducts.json` |
| `experiments/sweep_skew.py` | Figure 3(b) (RQ2, worst single hot rule) |
| `experiments/redundancy_study.py` | Table 6 (RQ2, redundant value occurrences) † |
| `experiments/real_workload.py` | RQ6 null control on routes and the heat-channel runs on ncvoter (`results/rq6_end_to_end.json`) † |
| `experiments/weather_census.py` | Figure 6 (RQ6, counting census over the fat rules of weather; `results/rq6_weather_census.json`) † |
| `experiments/weather_rules.py` | Table 9 (RQ6, live runs of the five separating weather rules on their storing subschemata; `results/rq6_weather_rules_*.json`) † |
| `experiments/weather_rows.py` | Table 9, rows column: rows one refresh of the 20 deepest groups rewrites, counted offline on the storing subschemata (`results/rq6_weather_rows.json`) |
| `experiments/weather_full.py` | Figure 7 (RQ6, full materialization and whole workload on the widest-gap rule; `results/rq6_weather_full.json`) † |
| `experiments/weather_recon.py` | Figure 7, reconstruction re-measured on the designs `weather_full.py` leaves in place (`results/rq6_weather_reconstruction.json`) † |
| `experiments/dataset_stats.py` | Table 2 (dataset dimensions) † |

`weather_rules.py`, `weather_full.py` and `weather_recon.py` share the front end
`weather_common.py`; the four `delivery_live.py` studies share `delivery_schema.py`
and `delivery_curves.py`.

† needs a MySQL server; see below.

Scripts marked † build and populate MySQL databases of their own and drop them
again. They assume a server they may create and drop schemas on; point them at a
scratch instance rather than a production one.

`delivery_live.py` accepts `--dry` for the row counts alone, which needs no
server and is the fastest way to see the mechanism, `--verify` to run one window
on both designs and compare the reconstructed relations by count and checksum,
and `--tiny` for a single small scale.

## Setup

```bash
python -m pip install -r requirements.txt
```

Python 3.12 and MySQL 8.0 were used for the reported numbers. Nothing depends on
the versions beyond that.

### Database configuration

No credentials are stored in this repository. `src/config.py` reads them from the
environment, with portable defaults:

| variable | default | meaning |
|---|---|---|
| `CUTD_MYSQL_HOST` | `localhost` | server host |
| `CUTD_MYSQL_PORT` | `3306` | server port |
| `CUTD_MYSQL_USER` | `root` | user |
| `CUTD_MYSQL_PASSWORD` | *(empty)* | password |
| `CUTD_MYSQL_DB` | `benchmarks` | database holding the benchmark relations |
| `CUTD_DELIVERY_DB` | `delivery_study` | database the delivery study builds its designs in |
| `CUTD_MYSQL_CLIENT` | `mysql` | path to the command-line client |
| `CUTD_FD_BASE` | `data/fd` | directory of the constraint sets |
| `CUTD_SCRATCH` | `.scratch` | directory for bulk-load temporaries |

For example:

```bash
export CUTD_MYSQL_PASSWORD=secret
export CUTD_MYSQL_DB=benchmarks
```

The delivery study raises the buffer pool for a run and restores it afterwards,
which needs a server the configured user may set global variables on.

### Benchmark relations

The mined **constraint sets** are shipped here in full, under `data/fd/`. The
underlying **relations** are the public profiling benchmarks used throughout the
data-profiling literature and are not redistributed. To run the scripts marked †,
load them into the database named by `CUTD_MYSQL_DB`, one table per relation.

The operational studies expect the two NULL readings as separate tables, named
`<relation>(nulleq)` and `<relation>(nulluc)`, matching the two constraint-set
directories. `experiments/redundancy_study.py` documents the calibration step
that aligns a loaded table with its mined constraint set.

The delivery studies (`delivery_live.py`, `delivery_curves.py`) need no benchmark
data at all: they generate an instance of the delivery schema that satisfies the
declared rules and, by the Armstrong witnesses appended in a disjoint value
range, nothing more. `delivery_schema.py` recomputes the instance's own
dependencies over all seven attributes and compares them against the closure
before every run.

## Data format

A constraint set is a JSON file

```json
{"R": 11, "fds": [{"lhs": [0, 3], "rhs": [5, 7]}, ...]}
```

where `R` is the number of attributes, attributes are `0 .. R-1`, and each entry
is an FD. `synthesis.load()` splits these into single-right-hand-side atomic FDs
and computes the minimal keys. Attribute names are not part of the benchmark
files: rules are identified by attribute index throughout, in the paper as well.

## Results

`results/` holds the JSON output behind each table and figure, so the numbers in
the paper can be checked without re-running anything. File names match the table
above.

## License

MIT, see `LICENSE`.
