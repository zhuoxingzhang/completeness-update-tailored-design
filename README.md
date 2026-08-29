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
  synthesis.py     the synthesis engine: FD primitives, minimal keys, mixed
                   covers, coolest covers, and one skeleton carrying every
                   objective. Run it directly for a self-check.
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

This runs the engine's self-check on the courier-dispatch running example of the
paper. It verifies that every objective returns a lossless, dependency-preserving
design, and reproduces the separation of Figure 1: the structure-optimal design
has maximal subschema heat 8, the heat-aware design has 2.

```bash
python experiments/courier_example.py
```

prints both designs of Figure 1 subschema by subschema, with minimal keys,
coolest mixed covers, and per-subschema heat.

```bash
python experiments/reduct_frontend.py
```

reproduces Table 3 (schema-level heat on twenty reducts of real incomplete
relations) from the shipped constraint sets. Takes a few minutes; writes
`rq2_draft.json`.

## Reproducing the experiments

| Script | Produces |
|---|---|
| `experiments/courier_example.py` | Figure 1, Example "Coolest covers" |
| `experiments/reduct_frontend.py` | Table 3 (RQ2, schema-level heat) |
| `experiments/sweep_skew.py` | Figure 3(b) (RQ2, worst single hot rule) |
| `experiments/redundancy_study.py` | Table 4 (RQ2, redundant value occurrences) † |
| `experiments/mini_courier.py` | Figure 2 (RQ1, controlled-redundancy sweep) † |
| `experiments/ext_courier.py` | Figure 4 (RQ3, mixed workloads), Figure 5 (RQ4/RQ5) † |
| `experiments/ext_e4plus.py` | RQ4 and RQ5 robustness curves † |
| `experiments/query_study.py` | RQ3 read half: reconstruction, lookups, history † |
| `experiments/real_workload.py` | Table 5 (RQ6, end-to-end replay) † |
| `experiments/dataset_stats.py` | Table 2 (dataset dimensions) † |

† needs a MySQL server; see below.

Scripts marked † build and populate MySQL databases of their own and drop them
again. They assume a server they may create and drop schemas on; point them at a
scratch instance rather than a production one.

`mini_courier.py` accepts `--tiny` for a single small scale and
`--scales 1000,10000` for an explicit list, which is the fastest way to see the
mechanism without waiting for the full sweep to `10^6` rows.

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
| `CUTD_MYSQL_CLIENT` | `mysql` | path to the command-line client |
| `CUTD_FD_BASE` | `data/fd` | directory of the constraint sets |

For example:

```bash
export CUTD_MYSQL_PASSWORD=secret
export CUTD_MYSQL_DB=benchmarks
```

### Benchmark relations

The mined **constraint sets** are shipped here in full, under `data/fd/`. The
underlying **relations** are the public profiling benchmarks used throughout the
data-profiling literature and are not redistributed. To run the scripts marked †,
load them into the database named by `CUTD_MYSQL_DB`, one table per relation.

The operational studies expect the two NULL readings as separate tables, named
`<relation>(nulleq)` and `<relation>(nulluc)`, matching the two constraint-set
directories. `experiments/redundancy_study.py` documents the calibration step
that aligns a loaded table with its mined constraint set.

The controlled studies (`mini_courier.py`, `ext_courier.py`, `query_study.py`)
need no benchmark data at all: they generate Armstrong relations for the courier
schema that satisfy exactly the declared constraints and nothing more.

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
