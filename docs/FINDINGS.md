# Findings from the first campaign on this simulator

Everything below came out of `scripts/run_campaign.py` and `scripts/sweep.py`.
No number here was chosen; they are what the model produced. Read this before
touching the manuscript, because three of these findings contradict claims the
current draft makes.

Run configuration: 1,024 prover slots (8 nodes x 128 cores, from the stated
hardware), 8 verifier slots, proof generation U(50, 500) ms x complexity with
complexity log-normal(0, 0.5) clipped to [0.5, 3.0], batch verification
8 + 0.35k ms, network 1-50 ms, Q_max = 10,000, L_target = 150 ms,
P_max = 100. Demonstration campaign: 10 trials x 7 rates x 3 schedulers,
30,000 transactions per trial. Rerun at 30 trials before using any of it.

## 1. There is no throughput difference between adaptive and fixed

| Rate (tx/s) | Adaptive | Fixed 100 ms | Delta | Holm p |
|---|---|---|---|---|
| 250 | 249.85 | 249.85 | +0.00% | 1.00 |
| 1,000 | 999.27 | 1002.06 | −0.28% | 1.00 |
| 2,000 | 1970.19 | 1974.81 | −0.23% | 0.18 |
| 3,000 | 3018.00 | 3015.56 | +0.08% | 1.00 |

Not one comparison is significant, and every effect is under a third of one
per cent. This is the expected result once the model is explicit: the window
governs *when* proofs are handed to the verifier, and the verifier is not the
bottleneck. Throughput is set by the prover pool, which the scheduler does not
touch. A scheduler that does not change service capacity cannot change goodput.

The current manuscript reports 18.25% to 34.17% higher goodput as its principal
finding. That claim does not survive.

## 2. Latency improves, by roughly a third of what the draft claims

Adaptive against the 100 ms fixed window, mean end-to-end latency:

| Rate (tx/s) | Adaptive | Fixed 100 ms | Delta | Hedges g |
|---|---|---|---|---|
| 250 | 348.29 | 394.86 | −11.79% | −26.40 |
| 1,000 | 353.60 | 417.18 | −15.24% | −36.27 |
| 2,000 | 361.69 | 396.77 | −8.84% | −18.74 |
| 3,000 | 370.70 | 390.01 | −4.95% | −10.46 |

Real, consistent, and significant. It is 5-15%, not 34.75%, and it shrinks as
load rises rather than growing.

The effect sizes are enormous because this is a seeded simulation: across-trial
dispersion reflects sampling noise in the service-time draws and nothing else.
Report them, but say plainly what they are measurements of.

## 3. The advantage disappears against a tuned baseline

This is the finding that matters most, and it is the one Reviewer 1 predicted.

Sweeping the fixed window duration at each rate (mean latency, ms):

| Rate | 10 ms | 20 ms | 50 ms | 100 ms | 200 ms | best | adaptive |
|---|---|---|---|---|---|---|---|
| 250 | **341.7** | 347.8 | 365.3 | 392.7 | 451.6 | 10 ms | 348.3 |
| 1,000 | **345.4** | 353.5 | 379.2 | 418.5 | 421.7 | 10 ms | 353.6 |
| 2,000 | **351.1** | 363.4 | 396.9 | 399.7 | 400.4 | 10 ms | 361.7 |
| 3,000 | **356.6** | 372.1 | 392.6 | 393.6 | 394.3 | 10 ms | 370.7 |

A 10 ms fixed window beats the adaptive controller at every arrival rate
tested. The apparent advantage in section 2 measures the distance between a
tuned system and an untuned one, not the value of the mechanism. Reviewer 1's
W3 says exactly this will be true, and on this simulator it is.

I also checked whether burstiness rescues it, since the requisite-variety
argument predicts a fixed regulator should fail when the disturbance has high
variety. It does not:

| Workload | Rate | IDC | Tuned fixed | Adaptive (best L*) |
|---|---|---|---|---|
| Poisson | 2,500 | 1.29 | 354.2 (10 ms) | 370.8 |
| MMPP | 2,500 | 65.5 | 380.0 (10 ms) | 396.0 |
| On/off | 2,500 | 205.1 | 522.7 (10 ms) | 539.4 |

At an index of dispersion of 205 the fixed window still wins.

## 4. Why, and what would change it

In this pipeline the optimum is always at the shortest admissible window,
because the bottleneck sits *upstream* of the aggregation buffer. Proofs are
generated per transaction by a prover pool; aggregation then only delays
verification, which was never the constraint. Waiting buys nothing, so
W -> W_min dominates at every load and every burstiness, and a controller can
at best match a constant while paying a settling cost on the way.

The requisite-variety argument is not wrong; it is being applied to a pipeline
where the regulator has nothing to regulate. Variety in the actuator only pays
when the loss surface has an interior optimum that moves. Here it has a corner
optimum that never moves.

**The architecture that would make this work is recursive aggregation.** In a
real ZK rollup you do not prove each transaction and then batch the proofs; you
prove a batch once, so prover cost is roughly c0 + c1*k for a batch of k and
larger batches cut prover load per transaction. Then window duration genuinely
trades prover capacity against queueing delay, the optimum is interior, it
moves with arrival rate, and a regulator has something to do. That is the
experiment worth running, and it is one change to `Pipeline._dispatch_provers`
plus a batch-cost function.

I have not implemented it because it changes what the paper is about, and that
is your call, not mine.

## 5. The controller never regulates at the stated target

Sweeping L_target (fraction of trials in which the window sits at W_min):

| Rate | L* = 150 | L* = 300 | L* = 400 | L* = 700 |
|---|---|---|---|---|
| 1,500 | 1.00 | 1.00 | 0.00 | 0.00 |
| 3,000 | 1.00 | 1.00 | 0.00 | 0.00 |

Mean proof generation alone is about 310 ms, so a 150 ms end-to-end target is
below the pipeline's irreducible service time. The error term is negative in
every cycle, contraction fires every cycle, and the window is pinned at
W_min = 20 ms for the whole run.

At L_target = 150 ms the adaptive scheduler is therefore not a controller in
any meaningful sense. It is a 20 ms fixed window that took a few hundred
milliseconds to get there. Above L_target = 400 ms it does open up and
regulate, and latency gets worse, because of finding 4.

Any version of this paper has to either pick a reachable target or report that
the configured one was not reachable.

## 6. The adaptive batch-size baseline needs work before it is fair

As configured it collapses: 52-89% admission shortfall, 16-41% of transactions
dropped. AIMD halves P_max on every latency violation, the target is
unreachable per finding 5, so P_max decays to its floor and the pipeline
starves.

That is a strawman and should not be reported as a comparison. Sweep its
target and its AIMD constants the same way the fixed window is swept, and give
it the same tuning effort as the adaptive scheduler, or the baseline objection
returns with the roles reversed.
