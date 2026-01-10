# Experimental Setup Documentation

This document provides detailed information about the experimental methodology used in the adaptive proof window scheduling research.

## 1. Hardware Environment

### Compute Cluster Specifications

| Component | Specification |
|-----------|---------------|
| **Nodes** | 8 compute nodes |
| **Processor** | Dual AMD EPYC 7763 per node |
| **Cores** | 128 cores total (64 per socket) |
| **Base Frequency** | 2.45 GHz |
| **Boost Frequency** | 3.5 GHz |
| **Architecture** | AMD Zen 3 |
| **Memory** | 512 GB DDR4-3200 per node |
| **L3 Cache** | 256 MB per node |
| **Storage** | NVMe SSD, 7,000 MB/s sequential read |
| **Network** | 100 Gbps Ethernet with RDMA |

### Operating System Configuration

- **Distribution:** Ubuntu 22.04 LTS
- **Kernel:** Linux 5.15.0 with real-time scheduling support

### Kernel Optimizations Applied

```bash
# Disable frequency scaling
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# CPU isolation for proof generation (cores 0-63)
isolcpus=0-63

# Enable huge pages
echo 1024 | tee /proc/sys/vm/nr_hugepages

# Process priority for verification threads
renice -n -20 -p <pid>
```

## 2. Cryptographic Stack

### Proving System

- **System:** Groth16
- **Curve:** BN254 (alt_bn128)
- **Framework:** arkworks-rs version 0.4.2

### Implementation Details

| Component | Implementation |
|-----------|----------------|
| Finite Field Arithmetic | Optimized assembly for Montgomery multiplication |
| Modular Reduction | Optimized assembly routines |
| Pairing Computation | Optimal ate pairing with denominator elimination |
| Random Number Generation | ChaCha20 seeded from hardware entropy |

## 3. Simulation Parameters

### Transaction Generation

- **Arrival Process:** Poisson
- **Arrival Rates:** 100, 500, 1,000, 2,500, 5,000, 7,500, 10,000 tx/s
- **Complexity Distribution:** Log-normal(μ=0, σ=0.5), clipped to [0.5, 3.0]
- **Priority Distribution:** 50% high, 30% medium, 20% low

### Proof Generation

- **Minimum Time:** 50 ms
- **Maximum Time:** 500 ms
- **Distribution:** Based on empirical measurements from production networks

### Network Latency

- **Model:** Measured distribution from geographically distributed deployments
- **Range:** 1-50 ms
- **Mean:** ~10 ms

## 4. Adaptive Scheduling Algorithm Parameters

### PI Controller

| Parameter | Symbol | Value | Description |
|-----------|--------|-------|-------------|
| Proportional Gain | K_p | 0.8 | Fast response to transient disturbances |
| Integral Gain | K_i | 0.2 | Eliminates steady-state error |

### Window Constraints

| Parameter | Value | Description |
|-----------|-------|-------------|
| Minimum Duration | 20 ms | W_min |
| Maximum Duration | 500 ms | W_max |
| Initial Duration | 100 ms | Starting value |

### Adjustment Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Expansion Factor | β = 1.25 | Multiplicative increase |
| Contraction Decrement | 50 ms | Additive decrease |
| Minimum Interval | T_adj = 500 ms | Between adjustments |
| Hysteresis Band | ±10% | Prevents chattering |

### Decision Thresholds

**Expansion Criteria:**
```
EXPAND if:
  (L_observed < 0.7 × L_target) AND
  (U_cpu < 0.6) AND
  (Q_depth < 0.5 × Q_max)
```

**Contraction Criteria:**
```
CONTRACT if:
  (L_observed > 1.2 × L_target) OR
  (U_cpu > 0.85) OR
  (Q_depth > 0.8 × Q_max)
```

### Arrival Rate Estimation

- **Method:** Exponential smoothing
- **Decay Parameter:** α = 0.15
- **Estimation Window:** 1,000 ms

## 5. Experimental Protocol

### Trial Configuration

| Parameter | Value |
|-----------|-------|
| Trials per Configuration | 30 |
| Transactions per Trial | 50,000 |
| Warm-up Period | 5,000 transactions |
| Independent Repetitions | Yes (system state reset between trials) |

### Measurement Collection

**Latency Metrics:**
- Mean latency
- Median latency
- 50th, 90th, 95th, 99th percentiles

**Throughput Metrics:**
- Window size: 1 second
- Peak and sustained throughput

**Resource Utilization:**
- CPU sampling interval: 100 ms
- Memory sampling interval: 500 ms
- Buffer sampling interval: 100 ms

## 6. Statistical Analysis

### Confidence Intervals

- **Level:** 95%
- **Distribution:** t-distribution (df = 29)
- **Precision:** Half-widths 3.2% to 5.8% of mean values

### Hypothesis Testing

- **Method:** Welch's t-test (unequal variances)
- **Significance Level:** p < 0.001

### Normality Testing

- **Test:** Shapiro-Wilk
- **Purpose:** Validate parametric test assumptions

### Software

- **Library:** SciPy version 1.9.3
- **Verification:** Against reference implementations

## 7. Baseline Configurations

### Fixed Window Scheduler

- Window duration: 100 ms
- Maximum proofs per window: 100

### Static Batching

- Batch size: 100 transactions
- No temporal adaptation

### Time-Based Batching

- Fixed interval: 100 ms
- Variable batch sizes

## 8. Reproducibility

### Random Seeds

Each trial uses a deterministic seed based on trial ID:
- Transaction generator: `seed = trial_id`
- Proof generator: `seed = trial_id + 1000`
- Verifier: `seed = trial_id + 2000`
- Resource monitor: `seed = trial_id + 3000`

### Code Availability

All simulation code is available in this repository under MIT license.

### Data Availability

Raw experimental data is provided in CSV format in the `data/raw/` directory.

## 9. Limitations

1. **Simulation vs. Production:** Results are from simulation; actual cryptographic operations may vary.

2. **Network Model:** Uses measured distributions rather than real network conditions.

3. **Hardware Specificity:** Results may differ on other hardware configurations.

4. **Burst Handling:** Sustained overload beyond peak throughput leads to queue accumulation regardless of scheduling.

5. **Geographic Distribution:** Experiments used co-located deployment; distributed scenarios may require parameter tuning.
