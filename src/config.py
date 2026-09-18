"""Local configuration: paths and database credentials.

Nothing here is secret and nothing is machine-specific. Every value has a
portable default and can be overridden by an environment variable, so the
artifact runs unmodified on a fresh checkout.

    CUTD_FD_BASE     directory holding the mined constraint sets
                     (default: <repo>/data/fd)
    CUTD_MYSQL_HOST  MySQL host      (default: localhost)
    CUTD_MYSQL_PORT  MySQL port      (default: 3306)
    CUTD_MYSQL_USER  MySQL user      (default: root)
    CUTD_MYSQL_PASSWORD  MySQL password (default: empty)
    CUTD_MYSQL_DB    database holding the benchmark relations (default: benchmarks)
    CUTD_DELIVERY_DB database the delivery study builds its designs in
                     (default: delivery_study)
    CUTD_RELEASE_DB  database the real-release study builds its designs in
                     (default: release_study)
    CUTD_MYSQL_CLIENT  path to the mysql command-line client (default: mysql)
    CUTD_SCRATCH     directory for bulk-load temporaries and the built relation of
                     the real release (default: <repo>/.scratch)
    CUTD_OWID_REPO   clone of github.com/owid/covid-19-data the real release is
                     read from (default: <scratch>/owid)

The operational studies need a MySQL 8 server. Set the password before running
them, for example

    export CUTD_MYSQL_PASSWORD=...        # POSIX shells
    $env:CUTD_MYSQL_PASSWORD = '...'      # PowerShell

See README.md for how to load the benchmark relations.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- data ----------
FD_BASE = os.environ.get("CUTD_FD_BASE", os.path.join(REPO, "data", "fd"))
RESULTS = os.path.join(REPO, "results")

# Directory names of the two NULL readings under FD_BASE.
SEMS = {"nulleq": "null-equality", "nulluc": "null-uncertainty"}

# ---------- MySQL ----------
MYSQL_HOST = os.environ.get("CUTD_MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("CUTD_MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("CUTD_MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("CUTD_MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("CUTD_MYSQL_DB", "benchmarks")
MYSQL_CLIENT = os.environ.get("CUTD_MYSQL_CLIENT", "mysql")

# The delivery study builds and drops its own tables, so it is kept away from the
# benchmark relations.
DELIVERY_DB = os.environ.get("CUTD_DELIVERY_DB", "delivery_study")

# The real-release study (RQ7) does the same in a database of its own.
RELEASE_DB = os.environ.get("CUTD_RELEASE_DB", "release_study")


def connect(database=None, **kw):
    """A pymysql connection to the benchmark server."""
    import pymysql
    return pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                           password=MYSQL_PASSWORD, database=database,
                           charset="utf8mb4", **kw)


def client_args(database=None, extra=()):
    """Argument vector for the mysql command-line client.

    The password is passed on the command line only when one is configured, so
    that a passwordless local server works out of the box.
    """
    args = [MYSQL_CLIENT, "-h", MYSQL_HOST, "-P", str(MYSQL_PORT), "-u", MYSQL_USER]
    if MYSQL_PASSWORD:
        args.append("-p" + MYSQL_PASSWORD)
    args += list(extra)
    if database:
        args.append(database)
    return args


def scratch_dir():
    """Directory for bulk-load temporaries, created on demand."""
    d = os.environ.get("CUTD_SCRATCH", os.path.join(REPO, ".scratch"))
    os.makedirs(d, exist_ok=True)
    return d


def owid_repo():
    """The clone of the publisher's repository the real release is read from."""
    return os.environ.get("CUTD_OWID_REPO", os.path.join(scratch_dir(), "owid"))
