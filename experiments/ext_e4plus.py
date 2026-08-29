"""E4 extension: skew curve out to w=128 (both scales), merged into ext_courier.json."""
import os, sys, json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import mini_courier as mc
import ext_courier as ec

ec.SKEWS = [1, 2, 4, 8, 16, 32, 64, 128]
OUT = ec.OUT


def main():
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out["_skews_x"] = ec.SKEWS
    old = int(mc.sh("SELECT @@innodb_buffer_pool_size;", db=None))
    if old >= mc.POOL_BIG:
        old = mc.POOL_SMALL
    mc.set_pool(mc.POOL_BIG)
    try:
        for n in ec.SCALES_E34:
            reps = 3 if n < 1_000_000 else 2
            print(f"[E4x N={n:,}]", flush=True)
            mc.build(n)
            out[f"e4x_{n}"] = ec.run_e4(n, reps)
            json.dump(out, open(OUT, "w"), indent=1)
    finally:
        mc.sh(f"DROP DATABASE IF EXISTS {mc.DB};", db=None)
        mc.set_pool(old)
    print("merged e4x into ext_courier.json")


if __name__ == "__main__":
    main()
