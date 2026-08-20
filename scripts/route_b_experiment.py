#!/usr/bin/env python3
"""Run Route B calibration, sweeps and final campaigns.

The script always writes per-trial CSV rows.  Summary statistics are generated
separately so the raw trial unit remains available for Reviewer 1's requested
Welch tests, confidence intervals and independence checks.
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import schedulers as S  # noqa: E402
from pipeline_route_b import RouteBPipeline  # noqa: E402

BASE_FIELDS = [
    "scheduler", "arrival_rate_txs", "workload", "trial_id", "l_target_ms",
    "window_ms_setting", "offered", "admitted", "dropped", "verified",
    "drop_fraction", "completion_fraction", "served_rate_proofs_s",
    "served_fraction", "mean_latency_ms", "median_latency_ms", "p95_latency_ms",
    "p99_latency_ms", "std_latency_ms", "coeff_variation", "mean_cpu_pct",
    "peak_cpu_pct", "mean_memory_gb", "mean_queue_occupancy_pct",
    "max_queue_occupancy_pct", "mean_batch_size", "mean_batch_prove_ms",
    "final_waiting", "idc", "measurement_seconds", "final_time_s",
    "window_mean_ms", "window_min_ms", "window_max_ms", "frac_window_at_min",
    "kp", "ki", "beta", "fixed_window_ms",
]


def build_scheduler(name, l_target, fixed_window=100.0, kp=0.8, ki=0.2,
                    beta=1.25):
    if name == "adaptive":
        return S.AdaptiveWindowScheduler(
            kp=kp, ki=ki, beta=beta, l_target_ms=l_target,
            w_min_ms=20.0, w_max_ms=500.0, w_init_ms=100.0,
            p_max=100, decrement_ms=50.0, t_adj_ms=500.0,
            hysteresis=0.10, integral_clamp_ms_s=(-500.0, 500.0),
            control_period_ms=100.0,
        )
    if name == "fixed":
        return S.FixedWindowScheduler(
            window_ms=fixed_window, p_max=100, l_target_ms=l_target)
    if name == "adaptive_batch":
        return S.AdaptiveBatchScheduler(
            p_init=100, p_min=1, p_max_cap=100,
            l_target_ms=l_target, timeout_ms=500.0,
            t_adj_ms=500.0, additive=8, multiplicative=0.5)
    raise ValueError(name)


def one(name, rate, trial, workload, ntx, warmup, l_target,
        fixed_window=100.0, kp=0.8, ki=0.2, beta=1.25):
    sch = build_scheduler(name, l_target, fixed_window, kp, ki, beta)
    res = RouteBPipeline(
        sch, arrival_rate=rate, trial_id=trial, workload=workload,
        n_transactions=ntx, warmup=warmup,
        batch_prover_slots=8, verifier_slots=8,
        prove_fixed_ms=180.0, prove_marginal_ms=0.60,
        verify_fixed_ms=5.0, verify_marginal_ms=0.05,
        q_max=10_000, control_period_ms=100.0, sample_period_ms=100.0,
        n_batches_window=20, net_mean_ms=10.0, net_max_ms=50.0,
    ).run()
    d = res.summary()
    w = np.asarray([x[1] for x in res.window_trajectory], float)
    d["window_mean_ms"] = float(w.mean()) if w.size else float("nan")
    d["window_min_ms"] = float(w.min()) if w.size else float("nan")
    d["window_max_ms"] = float(w.max()) if w.size else float("nan")
    d["frac_window_at_min"] = float(np.mean(w <= 20.0001)) if w.size else float("nan")
    d["kp"], d["ki"], d["beta"] = kp, ki, beta
    d["fixed_window_ms"] = fixed_window if name == "fixed" else float("nan")
    return d


def write_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def mode_smoke(a):
    rows = []
    for t in range(1, a.trials + 1):
        for s in ("adaptive", "fixed", "adaptive_batch"):
            rows.append(one(s, 1500, t, "poisson", a.transactions, a.warmup,
                            a.l_target, fixed_window=100.0))
    write_rows(a.out, rows)


def mode_window_sweep(a):
    durations = [10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300, 500]
    rates = a.rates or [250, 500, 1000, 1500, 2000, 2500, 3000]
    rows = []
    for t in range(1, a.trials + 1):
        for rate in rates:
            for d in durations:
                rows.append(one("fixed", rate, t, "poisson",
                                a.transactions, a.warmup, a.l_target,
                                fixed_window=d))
    write_rows(a.out, rows)


def mode_target_sweep(a):
    targets = [180, 200, 220, 240, 260, 300, 350, 400]
    rates = a.rates or [250, 500, 1000, 1500, 2000, 2500, 3000]
    rows = []
    for t in range(1, a.trials + 1):
        for rate in rates:
            for lt in targets:
                rows.append(one("adaptive", rate, t, "poisson",
                                a.transactions, a.warmup, lt))
    write_rows(a.out, rows)


def mode_gain_sensitivity(a):
    rows = []
    rates = a.rates or [500, 1500, 3000]
    base = {"kp": 0.8, "ki": 0.2, "beta": 1.25}
    for t in range(1, a.trials + 1):
        for rate in rates:
            for p, nominal in base.items():
                for mult in (0.5, 1.0, 1.5):
                    kw = dict(base)
                    kw[p] = nominal * mult
                    rows.append(one("adaptive", rate, t, "poisson",
                                    a.transactions, a.warmup, a.l_target,
                                    kp=kw["kp"], ki=kw["ki"], beta=kw["beta"]))
    write_rows(a.out, rows)


def mode_campaign(a):
    rates = a.rates or [250, 500, 1000, 1500, 2000, 2500, 3000]
    schedulers = a.schedulers or ["adaptive", "fixed"]
    rows = []
    for t in range(1, a.trials + 1):
        for rate in rates:
            for s in schedulers:
                rows.append(one(s, rate, t, a.workload,
                                a.transactions, a.warmup, a.l_target,
                                fixed_window=a.fixed_window))
    write_rows(a.out, rows)


def mode_bursty(a):
    rates = a.rates or [500, 1500, 3000]
    rows = []
    for t in range(1, a.trials + 1):
        for workload in ("mmpp", "onoff"):
            for rate in rates:
                for s in ("adaptive", "fixed"):
                    rows.append(one(s, rate, t, workload,
                                    a.transactions, a.warmup, a.l_target,
                                    fixed_window=a.fixed_window))
    write_rows(a.out, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=[
        "smoke", "window-sweep", "target-sweep", "gain-sensitivity",
        "campaign", "bursty"])
    ap.add_argument("--rates", nargs="+", type=float)
    ap.add_argument("--schedulers", nargs="+")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--transactions", type=int, default=20_000)
    ap.add_argument("--warmup", type=int, default=2_000)
    ap.add_argument("--l-target", type=float, default=240.0)
    ap.add_argument("--fixed-window", type=float, default=30.0)
    ap.add_argument("--workload", choices=["poisson", "mmpp", "onoff"],
                    default="poisson")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    {
        "smoke": mode_smoke,
        "window-sweep": mode_window_sweep,
        "target-sweep": mode_target_sweep,
        "gain-sensitivity": mode_gain_sensitivity,
        "campaign": mode_campaign,
        "bursty": mode_bursty,
    }[a.mode](a)


if __name__ == "__main__":
    main()
