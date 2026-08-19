#!/usr/bin/env python3
"""
Parameter sweeps.

--fixed-window   sweeps the fixed-window duration at every arrival rate and
                 reports the best duration found per rate. Comparing the
                 adaptive scheduler against that per-rate optimum, rather than
                 against one arbitrary setting, is what makes the baseline a
                 tuned one. Reviewer 1 W3 asks for exactly this.

--l-target       sweeps the controller's latency target. This matters because
                 a target below the pipeline's irreducible service time cannot
                 be met, and a controller chasing an unreachable target sits
                 saturated at an actuator limit for the whole run.

--gains          sensitivity of the result to Kp, Ki and beta at +/- 50%.
                 A controller that only works at one gain setting is not
                 deployable, and Reviewer 1 says so.

    python scripts/sweep.py --fixed-window --trials 5
    python scripts/sweep.py --l-target --trials 5
    python scripts/sweep.py --gains --trials 5
"""
import argparse, csv, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import schedulers as S       # noqa: E402
import pipeline as P         # noqa: E402

RATES = [250, 500, 1000, 1500, 2000, 2500, 3000]


def run(sch, rate, trial, ntx, warm):
    return P.Pipeline(sch, arrival_rate=rate, trial_id=trial,
                      n_transactions=ntx, warmup=warm).run().summary()


def sweep_fixed_window(a):
    durations = [10, 20, 30, 50, 75, 100, 150, 200, 300, 500]
    rows = []
    print(f"{'rate':>6} " + "".join(f"{d:>9}" for d in durations) +
          "   best  best_lat")
    for rate in RATES:
        lats = []
        for d in durations:
            v = [run(S.FixedWindowScheduler(window_ms=d, l_target_ms=a.l_target),
                     rate, t, a.transactions, a.warmup)["mean_latency_ms"]
                 for t in range(1, a.trials + 1)]
            lats.append(float(np.mean(v)))
            rows.append(dict(rate=rate, window_ms=d, mean_latency_ms=lats[-1]))
        i = int(np.argmin(lats))
        print(f"{rate:>6} " + "".join(f"{v:9.1f}" for v in lats) +
              f"  {durations[i]:5d}  {lats[i]:8.1f}")
    return rows, ["rate", "window_ms", "mean_latency_ms"]


def sweep_l_target(a):
    targets = [100, 150, 200, 300, 400, 500, 700, 1000]
    rows = []
    print(f"{'rate':>6} {'L_target':>9} {'lat':>9} {'W_mean':>8} {'W_min':>7} "
          f"{'W_max':>7} {'batch':>7} {'saturated':>10}")
    for rate in RATES:
        for lt in targets:
            lat, wm, wl_, wh, bs = [], [], [], [], []
            for t in range(1, a.trials + 1):
                sch = S.AdaptiveWindowScheduler(l_target_ms=lt)
                res = P.Pipeline(sch, arrival_rate=rate, trial_id=t,
                                 n_transactions=a.transactions,
                                 warmup=a.warmup).run()
                d = res.summary()
                w = np.array([x[1] for x in res.window_trajectory])
                lat.append(d["mean_latency_ms"]); bs.append(d["mean_batch_size"])
                wm.append(w.mean()); wl_.append(w.min()); wh.append(w.max())
            frac_at_limit = float(np.mean([x <= 20.0001 for x in wl_]))
            print(f"{rate:>6} {lt:>9} {np.mean(lat):9.1f} {np.mean(wm):8.1f} "
                  f"{np.mean(wl_):7.1f} {np.mean(wh):7.1f} {np.mean(bs):7.1f} "
                  f"{frac_at_limit:10.2f}")
            rows.append(dict(rate=rate, l_target_ms=lt,
                             mean_latency_ms=float(np.mean(lat)),
                             window_mean_ms=float(np.mean(wm)),
                             window_min_ms=float(np.mean(wl_)),
                             window_max_ms=float(np.mean(wh)),
                             mean_batch_size=float(np.mean(bs)),
                             frac_trials_hitting_w_min=frac_at_limit))
    return rows, list(rows[0].keys())


def sweep_gains(a):
    base = dict(kp=0.8, ki=0.2, beta=1.25)
    rows = []
    print(f"{'rate':>6} {'param':>6} {'value':>8} {'lat':>9} {'srv':>9} {'batch':>7}")
    for rate in [500, 1500, 3000]:
        for name, val in base.items():
            for mult in (0.5, 1.0, 1.5):
                kw = dict(base); kw[name] = val * mult
                kw["l_target_ms"] = a.l_target
                lat, srv, bs = [], [], []
                for t in range(1, a.trials + 1):
                    d = run(S.AdaptiveWindowScheduler(**kw), rate, t,
                            a.transactions, a.warmup)
                    lat.append(d["mean_latency_ms"])
                    srv.append(d["served_rate_proofs_s"])
                    bs.append(d["mean_batch_size"])
                print(f"{rate:>6} {name:>6} {val*mult:8.3f} {np.mean(lat):9.1f} "
                      f"{np.mean(srv):9.1f} {np.mean(bs):7.1f}")
                rows.append(dict(rate=rate, param=name, value=val * mult,
                                 mean_latency_ms=float(np.mean(lat)),
                                 served_rate=float(np.mean(srv)),
                                 mean_batch_size=float(np.mean(bs))))
    return rows, list(rows[0].keys())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixed-window", action="store_true")
    ap.add_argument("--l-target", action="store_true")
    ap.add_argument("--gains", action="store_true")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--transactions", type=int, default=20000)
    ap.add_argument("--warmup", type=int, default=2000)
    ap.add_argument("--l-target-value", dest="l_target", type=float, default=150.0)
    ap.add_argument("--out", default="data/processed")
    a = ap.parse_args()

    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    jobs = [(a.fixed_window, sweep_fixed_window, "sweep_fixed_window.csv"),
            (a.l_target, sweep_l_target, "sweep_l_target.csv"),
            (a.gains, sweep_gains, "sweep_gains.csv")]
    ran = False
    for flag, fn, fname in jobs:
        if not flag:
            continue
        ran = True
        print(f"\n=== {fname} " + "=" * 40)
        rows, fields = fn(a)
        with (outdir / fname).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader(); w.writerows(rows)
        print(f"wrote {outdir/fname}")
    if not ran:
        ap.error("choose at least one of --fixed-window, --l-target, --gains")


if __name__ == "__main__":
    main()
