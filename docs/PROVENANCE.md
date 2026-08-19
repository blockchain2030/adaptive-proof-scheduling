# Provenance rules

This repository exists so that every number in the paper can be traced to the
run that produced it. That property is easy to lose and hard to recover, so the
rules are short and absolute.

## The four rules

1. **Every number in the manuscript is produced by `scripts/analyze.py`.**
   If a figure appears in a table and this script does not print it, it does
   not go in the paper. No hand-entered values, no values carried over from an
   earlier draft, no rounding done by eye.

2. **The code is never adjusted to reproduce a number the paper already
   contains.** Parameters are chosen on physical grounds and documented in
   `configs/simulation.yaml` before a campaign runs. If the output disagrees
   with the draft, the draft changes.

3. **Raw campaign CSVs are committed unmodified**, with the command line that
   produced them recorded in `data/raw/PROVENANCE.txt`. A CSV whose generating
   command is not recorded is not evidence.

4. **The claims in the paper are checked against the code before submission.**
   Concretely: read the Model and Method section beside `src/schedulers.py` and
   confirm that every mechanism described is one the code executes, and that
   every mechanism the code executes is described. Dead code that the paper
   describes as active is the failure mode to watch for.

## Recording a campaign

```bash
python scripts/run_campaign.py --trials 30 --workload poisson \
    --out data/raw/campaign_poisson.csv
echo "campaign_poisson.csv | $(date -Is) | $(git rev-parse --short HEAD) | \
  run_campaign.py --trials 30 --workload poisson" >> data/raw/PROVENANCE.txt
python scripts/analyze.py data/raw/campaign_poisson.csv > \
    data/processed/analysis_poisson.txt
```

Commit the CSV, the provenance line and the analysis output together.

## Controller listing for the manuscript

Reviewer 1's W4 asks for a line-numbered discrete-time algorithm. This is the
listing, and it is what `AdaptiveWindowScheduler.tick` executes — the two must
be checked against each other whenever either changes.

```
Algorithm 1  Supervisory-gated PI control of the aggregation window
Input   Kp, Ki, W_min, W_max, L*, beta, Dec, T_adj, h, [I_min, I_max], Tc
State   W (window duration), I (integral), t_last (last adjustment)

 1  every Tc milliseconds:
 2      if (t - t_last) < T_adj: return                    # rate limit
 3      sample L_obs (mean over last N_b closed batches), U_cpu, Q_depth
 4      e <- L* - L_obs
 5      expand   <- (L_obs < 0.7 L* .lo) AND (U_cpu < 0.60 .lo)
 6                                        AND (Q_depth < 0.50 Q_max .lo)
 7      contract <- (L_obs > 1.2 L* .hi) OR  (U_cpu > 0.85 .hi)
 8                                        OR  (Q_depth > 0.80 Q_max .hi)
 9      if contract: expand <- false                       # contraction wins
10      # .lo and .hi are the hysteresis band (1-h) and (1+h); on entry the
11      # entry threshold applies, while already in the state the exit
12      # threshold applies, so a boundary signal cannot chatter
13      at_limit <- (W >= W_max and e > 0) or (W <= W_min and e <= 0)
14      if (expand or contract) and not at_limit:          # conditional
15          I <- clamp(I + e * Tc/1000, I_min, I_max)      # integration
16      u <- Kp*e + Ki*I
17      if contract:   dW <- -min(Dec, |u|)                # additive decrease
18      elif expand:   dW <- +min(W*(beta-1), |u|)         # multiplicative
19      else:          t_last <- t; return                 # gate declines
20      W <- clamp(W + dW, W_min, W_max)
21      t_last <- t
```

Units: `e` and `W` are milliseconds, so `Kp` is dimensionless. `I` accumulates
`e` over time and carries millisecond-seconds, so `Ki` carries inverse seconds.
Line 15 is the anti-windup scheme: clamping plus conditional integration.
Lines 13-14 are what stop the integrator accumulating against a saturated
actuator.

## Parameter table for the manuscript

| Symbol | Meaning | Value | Units | How chosen |
|---|---|---|---|---|
| Kp | proportional gain | 0.8 | — | inherited from the original design; sweep with `sweep.py --gains` |
| Ki | integral gain | 0.2 | s^-1 | as above |
| [I_min, I_max] | integral clamp | ±500 | ms·s | set to the actuator range |
| W_min | minimum window | 20 | ms | shortest window the verifier dispatch can service |
| W_max | maximum window | 500 | ms | equals the maximum proof-generation time |
| W_init | initial window | 100 | ms | midpoint; equals the fixed baseline |
| L* | latency target | 150 | ms | **not reachable — see FINDINGS §5** |
| P_max | proofs per window | 100 | proofs | early-closure threshold |
| Q_max | queue capacity | 10,000 | proofs | admission bound |
| beta | expansion factor | 1.25 | — | multiplicative-increase constant |
| Dec | contraction decrement | 50 | ms | additive-decrease constant |
| T_adj | minimum adjustment interval | 500 | ms | 5x the control period |
| Tc | control period | 100 | ms | equals the monitor sampling period |
| h | hysteresis band | 0.10 | — | ±10% around each threshold |
| alpha | arrival smoothing | 0.15 | — | exponential smoothing decay |

Four of these — Kp, Ki, beta and Dec — have no derivation behind them and are
inherited values. Say so in the paper. Reviewer 1 asks how each constant was
obtained, and "it was inherited and swept for sensitivity" is an acceptable
answer where "it was tuned" is not.
