"""Dataset statistics for the RQ2 benchmark table: rows, attributes, null rate,
and mined FD counts under both NULL readings."""
import subprocess, json, os, csv

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'src'))
import config
BASE = config.FD_BASE
EQ = os.path.join(BASE, "FD on NULL EQUALITY", "FD")
UN = os.path.join(BASE, "FD on NULL UNCERTAINTY", "FD")
BIOCASE_CSV = _os.environ.get("CUTD_BIOCASE_CSV",
                              _os.path.join(config.REPO, "data", "raw",
                                            "t_biocase_identification_r91800_c38.csv"))

def sh(sql):
    r = subprocess.run(config.client_args(config.MYSQL_DB, extra=["-N", "-B"]),
                       input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return r.stdout.strip()

def table_stats(tbl):
    cols = sh(f"SELECT COLUMN_NAME FROM information_schema.columns "
              f"WHERE table_schema='{config.MYSQL_DB}' AND table_name='{tbl}';").split("\n")
    n = int(sh(f"SELECT COUNT(*) FROM `{tbl}`;"))
    nulls = 0
    for c in cols:
        nulls += int(sh(f"SELECT SUM(`{c}` IS NULL) FROM `{tbl}`;") or 0)
    return len(cols), n, nulls / (n * len(cols))

def jsonfds(path, name):
    p = os.path.join(path, name + ".json")
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p))
    return len(d["R"]) if not isinstance(d["R"], int) else d["R"], len(d["fds"])

DATASETS = {  # paper name -> (benchmark table base, json base name)
    "routes": ("routes", "routes"), "claims": ("claims", "claims"),
    "breast": ("breast", "breast"), "biocase": (None, "t_biocase_identification_r91800_c38"),
    "pdbx": ("pdbx", "pdbx"), "hospital": ("hospital", "hospital"),
    "bridges": ("bridges", "bridges"), "echo": ("echo", "echo"),
    "ncvoter": ("ncvoter", "ncvoter"), "weather": ("china_weather", "china_weather"),
    "dblp10k": ("dblp10k", "dblp10k"), "uniprot": ("uniprot", "uniprot"),
    "hepatitis": ("hepatitis", "hepatitis"), "diabetic": ("diabetic", "diabetic"),
}

out = {}
for name, (tbl, jb) in DATASETS.items():
    Req, feq = jsonfds(EQ, jb)
    Run, fun = jsonfds(UN, jb)
    if tbl is not None:
        variant = None
        for suf in ("(nulluc)", "(nulleq)"):
            try:
                sh(f"SELECT 1 FROM `{tbl}{suf}` LIMIT 1;")
                variant = tbl + suf
                break
            except RuntimeError:
                continue
        ncols, nrows, nullrate = table_stats(variant)
    else:
        rows = list(csv.reader(open(BIOCASE_CSV, encoding="utf-8", errors="replace")))
        header, data = rows[0], rows[1:]
        ncols, nrows = len(header), len(data)
        empt = sum(1 for r in data for v in r if v == "" or v == "?" or v.upper() == "NULL")
        nullrate = empt / (nrows * ncols)
    out[name] = {"attrs": ncols, "rows": nrows, "null": round(100 * nullrate, 1),
                 "fds_eq": feq, "fds_un": fun, "R_eq": Req, "R_un": Run}
    print(f"{name:10s} |R|={ncols:3d} rows={nrows:7,d} null={100*nullrate:5.1f}%"
          f"  fds_eq={feq}  fds_un={fun}")

json.dump(out, open(os.path.join(config.RESULTS, "datasets.json"), "w"), indent=1)
print("wrote results/datasets.json")
