#!/usr/bin/env python3
"""
Run an experimental campaign and write per-trial records to CSV.

Execution order is interleaved across schedulers rather than blocked, so that
any drift across the campaign affects every arm equally. Trial index is
recorded in the output so independence can be tested rather than asserted.

Examples
--------
    # locate the saturation point first
    python scripts/run_campaign.py --sweep-saturation

    # main campaign, sub-saturation rates
    python scripts/run_campaign.py --rates 250 500 1000 1500 2000 2500 3000 \
        --schedulers adaptive fixed adaptive_batch --trials 30

    # bursty workloads
    python scripts/run_campaign.py --workload mmpp --trials 30
"""
import argparse, csv, itertools, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import schedulers as S           # noqa: E402
import pipeline as P             # noqa: E402

FIELDS = ["scheduler", "arrival_rate_txs", "workload", "trial_id",
          "window_ms_setting", "l_target_ms", "offered", "admitted", "dropped",
          "verified", "verified_recorded", "drop_fraction",
          "served_rate_proofs_s", "served_fraction", "mean_throughput_proofs_s",
          "std_throughput", "mean_latency_ms", "median_latency_ms",
          "p95_latency_ms", "p99_latency_ms", "std_latency_ms",
          "coeff_variation", "mean_cpu_pct", "peak_cpu_pct", "mean_memory_gb",
          "mean_buffer_occupancy_pct", "max_buffer_occupancy_pct",
          "mean_batch_size", "final_tx_queue", "final_buffer", "idc",
          "sim_seconds"]


def one(scheduler_name, rate, trial, args):
    kw = {"l_target_ms": args.l_target}
    if scheduler_name == "fixed":
        kw["window_ms"] = args.fixed_window
    if scheduler_name == "adaptive_batch":
        kw.pop("l_target_ms"); kw["l_target_ms"] = args.l_target
    sch = S.build(scheduler_name, **kw)
    res = P.Pipeline(sch, arrival_rate=rate, trial_id=trial,
                     workload=args.workload,
                     n_transactions=args.transactions,
                     warmup=args.warmup,
                     prover_slots=args.prover_slots,
                     verifier_slots=args.verifier_slots,
                     q_max=args.q_max).run()
    row = res.summary()
    row["l_target_ms"] = args.l_target
    if scheduler_name == "fixed":
        row["window_ms_setting"] = args.fixed_window
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", type=float, nargs="+",
                    default=[250, 500, 1000, 1500, 2000, 2500, 3000])
    ap.add_argument("--schedulers", nargs="+",
                    default=["adaptive", "fixed", "adaptive_batch"])
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--workload", default="poisson",
                    choices=["poisson", "mmpp", "onoff"])
    ap.add_argument("--transactions", type=int, default=50000)
    ap.add_argument("--warmup", type=int, default=5000)
    ap.add_argument("--fixed-window", type=float, default=100.0)
    ap.add_argument("--l-target", type=float, default=150.0)
    ap.add_argument("--prover-slots", type=int, default=1024)
    ap.add_argument("--verifier-slots", type=int, default=8)
    ap.add_argument("--q-max", type=int, default=10000)
    ap.add_argument("--out", default="data/raw/campaign.csv")
    ap.add_argument("--sweep-saturation", action="store_true",
                    help="probe a wide rate range with 3 trials to find the knee")
    args = ap.parse_args()

    if args.sweep_saturation:
        args.rates = [250, 500, 1000, 1500, 2000, 2500, 3000,
                      3250, 3500, 4000, 5000, 7500, 10000]
        args.trials = 3
        args.out = "data/raw/saturation_sweep.csv"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # interleave: trial is the outer loop so arms alternate throughout
    jobs = [(s, r, t) for t in range(1, args.trials + 1)
            for r in args.rates for s in args.schedulers]

    t0 = time.time()
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for i, (s, r, t) in enumerate(jobs, 1):
            w.writerow(one(s, r, t, args))
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} trials  ({time.time()-t0:.0f}s)",
                      flush=True)
    print(f"wrote {out} — {len(jobs)} trials in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
