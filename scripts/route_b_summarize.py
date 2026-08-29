#!/usr/bin/env python3
"""Summarize Route B sweep/campaign CSVs into reviewer-facing tables."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def mean_table(df, keys):
    cols = ["mean_latency_ms", "served_rate_proofs_s", "served_fraction",
            "drop_fraction", "completion_fraction", "mean_batch_size",
            "window_mean_ms", "frac_window_at_min", "idc"]
    use = [c for c in cols if c in df.columns]
    return df.groupby(keys, dropna=False)[use].mean().reset_index()


def holm(pvals):
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    out = np.empty_like(p)
    running = 0.0
    m = len(p)
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * p[idx])
        running = max(running, adj)
        out[idx] = running
    return out


def compare_two(df, metric="mean_latency_ms"):
    rows = []
    for rate in sorted(df.arrival_rate_txs.unique()):
        d = df[df.arrival_rate_txs == rate]
        a = d[d.scheduler == "adaptive"][metric].dropna().to_numpy(float)
        f = d[d.scheduler == "fixed"][metric].dropna().to_numpy(float)
        if len(a) < 2 or len(f) < 2:
            continue
        t, p = stats.ttest_ind(a, f, equal_var=False)
        rows.append(dict(rate=rate, adaptive=np.mean(a), fixed=np.mean(f),
                         delta_pct=(np.mean(a)-np.mean(f))/np.mean(f)*100,
                         t=t, p=p))
    if rows:
        adj = holm([r["p"] for r in rows])
        for r, q in zip(rows, adj):
            r["p_holm"] = q
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke")
    ap.add_argument("--window")
    ap.add_argument("--target")
    ap.add_argument("--gains")
    ap.add_argument("--campaign")
    ap.add_argument("--bursty")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    lines = ["# Route B simulation summary", ""]

    if a.smoke:
        d = pd.read_csv(a.smoke)
        t = mean_table(d, ["scheduler"])
        lines += ["## Smoke test", "", t.to_markdown(index=False), ""]

    if a.window:
        d = pd.read_csv(a.window)
        t = mean_table(d, ["arrival_rate_txs", "fixed_window_ms"])
        best = t.loc[t.groupby("arrival_rate_txs")["mean_latency_ms"].idxmin()].copy()
        lines += ["## Fixed-window sweep", "", "Per-rate latency optimum:", "",
                  best.to_markdown(index=False), ""]

    if a.target:
        d = pd.read_csv(a.target)
        t = mean_table(d, ["arrival_rate_txs", "l_target_ms"])
        agg = t.groupby("l_target_ms").agg(
            mean_latency_ms=("mean_latency_ms", "mean"),
            mean_served_fraction=("served_fraction", "mean"),
            mean_window_ms=("window_mean_ms", "mean"),
            mean_frac_at_min=("frac_window_at_min", "mean"),
        ).reset_index()
        lines += ["## Latency-target sweep", "", "Across-rate calibration summary:", "",
                  agg.to_markdown(index=False), ""]

    if a.gains:
        d = pd.read_csv(a.gains)
        t = mean_table(d, ["arrival_rate_txs", "kp", "ki", "beta"])
        lines += ["## Gain sensitivity", "", t.to_markdown(index=False), ""]

    if a.campaign:
        d = pd.read_csv(a.campaign)
        t = mean_table(d, ["arrival_rate_txs", "scheduler"])
        lat = compare_two(d, "mean_latency_ms")
        good = compare_two(d, "served_rate_proofs_s")
        lines += ["## Final Poisson campaign", "", t.to_markdown(index=False), "",
                  "### Welch comparison: latency", "", lat.to_markdown(index=False), "",
                  "### Welch comparison: goodput", "", good.to_markdown(index=False), ""]

    if a.bursty:
        d = pd.read_csv(a.bursty)
        t = mean_table(d, ["workload", "arrival_rate_txs", "scheduler"])
        lines += ["## Bursty workloads", "", t.to_markdown(index=False), ""]
        for w in sorted(d.workload.unique()):
            lines += [f"### {w}: latency Welch comparison", "",
                      compare_two(d[d.workload == w], "mean_latency_ms").to_markdown(index=False), ""]

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
