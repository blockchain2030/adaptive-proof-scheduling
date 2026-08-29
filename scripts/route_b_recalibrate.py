#!/usr/bin/env python3
"""Calibration and validation runner for the feedback-ready Route B model."""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import schedulers as S  # noqa: E402
from route_b_scheduler import FeedbackReadyAdaptiveWindowScheduler  # noqa: E402
from pipeline_route_b import RouteBPipeline  # noqa: E402
from route_b_experiment import BASE_FIELDS  # noqa: E402

TUNED_FIXED = {250: 25, 500: 25, 1000: 25, 1500: 30,
               2000: 30, 2500: 30, 3000: 40}


def run_one(label, rate, trial, workload, ntx, warmup, l_target,
            kp=0.8, ki=0.2, beta=1.25, fixed_window=None):
    if label == "adaptive":
        sch = FeedbackReadyAdaptiveWindowScheduler(
            kp=kp, ki=ki, beta=beta, l_target_ms=l_target,
            w_min_ms=20.0, w_max_ms=500.0, w_init_ms=100.0,
            p_max=100, decrement_ms=50.0, t_adj_ms=500.0,
            hysteresis=0.10, integral_clamp_ms_s=(-500.0, 500.0),
            control_period_ms=100.0)
    else:
        fw = float(fixed_window)
        sch = S.FixedWindowScheduler(window_ms=fw, p_max=100,
                                     l_target_ms=l_target)

    res = RouteBPipeline(
        sch, arrival_rate=rate, trial_id=trial, workload=workload,
        n_transactions=ntx, warmup=warmup,
        batch_prover_slots=8, verifier_slots=8,
        prove_fixed_ms=180.0, prove_marginal_ms=0.60,
        verify_fixed_ms=5.0, verify_marginal_ms=0.05,
        q_max=10_000, control_period_ms=100.0, sample_period_ms=100.0,
        n_batches_window=20, net_mean_ms=10.0, net_max_ms=50.0).run()
    d = res.summary()
    d["scheduler"] = label
    w = np.asarray([x[1] for x in res.window_trajectory], float)
    d["window_mean_ms"] = float(w.mean()) if w.size else float("nan")
    d["window_min_ms"] = float(w.min()) if w.size else float("nan")
    d["window_max_ms"] = float(w.max()) if w.size else float("nan")
    d["frac_window_at_min"] = float(np.mean(w <= 20.0001)) if w.size else float("nan")
    d["kp"], d["ki"], d["beta"] = kp, ki, beta
    d["fixed_window_ms"] = float(fixed_window) if fixed_window is not None else float("nan")
    return d


def write(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BASE_FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def target_sweep(a):
    rates = a.rates or [250, 500, 1000, 1500, 2000, 2500, 3000]
    targets = [180, 190, 200, 210, 220, 230, 240, 250, 260, 280, 300]
    rows = []
    for t in range(a.trial_offset + 1, a.trial_offset + a.trials + 1):
        for rate in rates:
            for lt in targets:
                rows.append(run_one("adaptive", rate, t, "poisson",
                                    a.transactions, a.warmup, lt,
                                    kp=0.8, ki=0.2, beta=1.25))
    write(a.out, rows)


def controller_grid(a):
    rates = a.rates or [500, 1500, 3000]
    targets = [190, 200, 210, 220, 230, 240, 250, 260]
    kps = [0.4, 0.8, 1.2]
    rows = []
    for t in range(a.trial_offset + 1, a.trial_offset + a.trials + 1):
        for rate in rates:
            for lt in targets:
                for kp in kps:
                    rows.append(run_one("adaptive", rate, t, "poisson",
                                        a.transactions, a.warmup, lt,
                                        kp=kp, ki=0.2, beta=1.25))
    write(a.out, rows)


def gain_sensitivity(a):
    rates = a.rates or [500, 1500, 3000]
    rows = []
    # Beta sensitivity is applied to the expansion increment (beta-1),
    # keeping beta > 1: 1.125, 1.25, 1.375.
    variants = []
    for mult in (0.5, 1.0, 1.5):
        variants.append(("kp", a.kp * mult, a.kp * mult, 0.2, 1.25))
    for mult in (0.5, 1.0, 1.5):
        variants.append(("ki", 0.2 * mult, a.kp, 0.2 * mult, 1.25))
    for mult in (0.5, 1.0, 1.5):
        beta = 1.0 + (1.25 - 1.0) * mult
        variants.append(("beta", beta, a.kp, 0.2, beta))
    for t in range(a.trial_offset + 1, a.trial_offset + a.trials + 1):
        for rate in rates:
            for _, _, kp, ki, beta in variants:
                rows.append(run_one("adaptive", rate, t, "poisson",
                                    a.transactions, a.warmup, a.l_target,
                                    kp=kp, ki=ki, beta=beta))
    write(a.out, rows)


def campaign(a):
    rates = a.rates or [250, 500, 1000, 1500, 2000, 2500, 3000]
    rows = []
    for t in range(a.trial_offset + 1, a.trial_offset + a.trials + 1):
        for rate in rates:
            rows.append(run_one("adaptive", rate, t, "poisson",
                                a.transactions, a.warmup, a.l_target,
                                kp=a.kp, ki=0.2, beta=1.25))
            rows.append(run_one("fixed_tuned", rate, t, "poisson",
                                a.transactions, a.warmup, a.l_target,
                                fixed_window=TUNED_FIXED.get(int(rate), a.fixed_window)))
            rows.append(run_one("fixed_100", rate, t, "poisson",
                                a.transactions, a.warmup, a.l_target,
                                fixed_window=100.0))
    write(a.out, rows)


def bursty(a):
    rates = a.rates or [500, 1500, 3000]
    rows = []
    for t in range(a.trial_offset + 1, a.trial_offset + a.trials + 1):
        for workload in ("mmpp", "onoff"):
            for rate in rates:
                rows.append(run_one("adaptive", rate, t, workload,
                                    a.transactions, a.warmup, a.l_target,
                                    kp=a.kp, ki=0.2, beta=1.25))
                rows.append(run_one("fixed_tuned", rate, t, workload,
                                    a.transactions, a.warmup, a.l_target,
                                    fixed_window=TUNED_FIXED[int(rate)]))
    write(a.out, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["target-sweep", "controller-grid",
                                     "gain-sensitivity", "campaign", "bursty"])
    ap.add_argument("--rates", nargs="+", type=float)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--trial-offset", type=int, default=0)
    ap.add_argument("--transactions", type=int, default=20000)
    ap.add_argument("--warmup", type=int, default=2000)
    ap.add_argument("--l-target", type=float, default=220.0)
    ap.add_argument("--kp", type=float, default=0.8)
    ap.add_argument("--fixed-window", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    {"target-sweep": target_sweep,
     "controller-grid": controller_grid,
     "gain-sensitivity": gain_sensitivity,
     "campaign": campaign,
     "bursty": bursty}[a.mode](a)


if __name__ == "__main__":
    main()
