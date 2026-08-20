# Reviewer 1 v1.3 simulation test findings — 20 August 2026

## Scope

Tests were run against the discrete-event model and scheduler logic currently represented by `src/pipeline.py`, `src/schedulers.py`, and `src/workload.py`. The primary final comparison used the adaptive window scheduler, the original 100 ms fixed baseline, and the fixed-window duration selected by the baseline sweep. The untuned adaptive-batch scheduler was exercised in stage-1 testing but was not promoted into the 30-trial final comparison because it collapses under the present configuration and must itself be swept before it can serve as a fair baseline.

## 1. Smoke test

At 5,000 tx/s the simulator completed and produced direct offered/admitted/dropped/verified accounting, latency, resource, queue and window measurements. The controller rapidly reached the lower part of its actuator range. The existing output definition of `served_fraction` needs correction before it is used as a saturation criterion: it divides post-warmup recorded completions by elapsed time that includes final queue drain. Therefore `served_fraction` can be below 0.99 even when all 50,000 offered transactions are eventually verified and no transaction is dropped.

## 2. Fixed-window sweep

Durations 10, 20, 30, 50, 75, 100, 150, 200, 300 and 500 ms were swept. The latency optimum was the boundary value **10 ms at every tested rate from 250 to 3,000 tx/s**.

Mean latency for the 10 ms fixed window was approximately 342.6, 343.6, 346.3, 349.0, 351.5, 354.1 and 356.3 ms at 250, 500, 1,000, 1,500, 2,000, 2,500 and 3,000 tx/s respectively.

This confirms Reviewer 1 W3: the original 100 ms fixed baseline was not tuned, and the apparent advantage over that baseline is not evidence that adaptive interval control beats a tuned fixed window.

## 3. Adaptive versus tuned fixed baseline

Five-trial stage-1 comparisons showed the 10 ms fixed window had lower mean latency than the adaptive controller at every rate from 250 to 3,000 tx/s. The adaptive controller remained better than the untuned 100 ms fixed baseline, but not better than the swept optimum.

The 30-trial × 50,000-transaction Poisson campaign at the manuscript's original rates produced the following primary comparison:

| Offered rate | Adaptive latency (ms) | Fixed 10 ms latency (ms) | Adaptive vs fixed 10 | Adaptive goodput (proof/s) | Fixed 10 goodput (proof/s) | Drop fraction |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 353.46 | 344.94 | +2.47% latency | 991.30 | 991.23 | 0.000 |
| 2,500 | 364.91 | 351.13 | +3.93% latency | 2443.43 | 2444.05 | 0.000 |
| 5,000 | 2320.64 | 2308.16 | +0.54% latency | 3290.72 | 3282.56 | 0.113 |
| 7,500 | 2524.51 | 2512.23 | +0.49% latency | 3255.18 | 3249.12 | 0.337 |
| 10,000 | 2506.51 | 2497.59 | +0.36% latency | 3222.65 | 3215.31 | 0.449 |

Positive latency percentages mean the adaptive controller was slower. Welch tests on goodput found no Holm-corrected adaptive advantage over fixed 10 ms at any of the five rates. The small latency differences favored fixed 10 ms.

Against the old **100 ms** baseline, adaptive latency was lower by about 15.23% at 1,000 tx/s and 6.80% at 2,500 tx/s, but only about 0.54–0.66% at 5,000–10,000 tx/s. Adaptive goodput differed from fixed 100 ms by less than 1% at every final-campaign rate.

## 4. Saturation/capacity location

A 50,000-transaction capacity probe shows that the prover pool, not the aggregation/verifier stage, is the effective bottleneck. With the adaptive scheduler:

- 3,000 tx/s: no transaction queue develops; mean goodput about 2,924 proof/s.
- 3,250 tx/s: small transient transaction queue; mean goodput about 3,159 proof/s.
- 3,500 tx/s: backlog begins to grow materially; mean goodput plateaus around 3,300 proof/s.
- 3,750–4,000 tx/s: backlog grows strongly while mean goodput remains about 3,300 proof/s.
- 4,250 tx/s: queue approaches the 10,000-proof bound and drops begin.
- 4,500 tx/s and above: queue reaches the bound and admission loss increases.

The practical service-capacity knee is therefore approximately **3.3 kproof/s**, with sustained backlog becoming evident around 3.5 ktx/s and admission loss appearing around 4.25 ktx/s for a 50,000-transaction run. This should replace the previous claim that saturation lies below 1,000 tx/s.

## 5. Gain sensitivity

Kp, Ki and beta were varied at 50%, 100% and 150% of nominal at 500, 1,500 and 3,000 tx/s. Ki variation produced effectively identical outputs at these settings; Kp variation had negligible effect; beta produced only small changes. This is diagnostic rather than reassuring: with L_target = 150 ms, the controller spends most of its time at or near W_min, so the PI gains have little opportunity to influence the actuator.

## 6. L_target diagnostic

The target sweep confirms the controller-pinning concern. At L_target = 100–200 ms, the controller spends roughly 78–96% of sampled control states at W_min depending on arrival rate. At 500 tx/s, for example, L_target 150 ms gives a mean window around 22.2 ms and about 96% of sampled states at W_min. Raising the target changes the operating point, but also increases latency as the window expands. The manuscript must not present 150 ms as a successfully regulated target under this service-time model.

## 7. Bursty workloads

MMPP and on/off stage-1 runs were completed and burstiness was measured by IDC rather than asserted. At 500, 1,500 and 3,000 tx/s, mean IDC was approximately 12.7, 35.6 and 67.3 for MMPP and 39.1, 102.9 and 229.0 for on/off in the five-trial stage-1 runs. The fixed 10 ms baseline retained lower mean latency than the adaptive controller at all six rate/workload combinations.

A 30-trial × 50,000-transaction confirmation at 5,000 tx/s gave mean IDC about 113.5 for MMPP and 375.9 for on/off. Fixed 10 ms again had lower mean latency than adaptive: 2234.0 vs 2246.8 ms under MMPP, and 2221.0 vs 2233.8 ms under on/off.

## Consequence for manuscript v1.3

The current rebuilt model supports **Route A / boundary-condition result**, not the original v1.2 headline claim. The evidence says:

1. adaptive control improves latency against the arbitrary 100 ms fixed baseline;
2. a swept 10 ms fixed window is faster than the adaptive controller across the tested Poisson and bursty cases;
3. goodput is governed primarily by the upstream prover pool and is nearly scheduler-invariant until overload/admission loss dominates;
4. the 150 ms target is below the achieved service latency and pins the controller near W_min;
5. `served_fraction` as currently calculated should not be used to infer saturation because it includes final-drain time in the denominator.

Before claiming a positive adaptive advantage in a Route B manuscript, the pipeline model must create a genuine batch-dependent proving/service trade-off with an interior optimum, then the fixed-window sweep and full campaign must be rerun on that changed model. The present results should be retained as the boundary condition showing when interval regulation has no useful operating point to track.
