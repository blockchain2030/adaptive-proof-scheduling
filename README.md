# Adaptive Proof Window Scheduling for Continuous Zero-Knowledge Proof Transfer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## Overview

This repository contains the simulation code, experimental parameters, and datasets for the research paper:

> **Adaptive Proof Window Scheduling for Continuous Zero Knowledge Proof Transfer**  
> Muhammad Shahid, Suziyanti Marjudi, Abd Samad Hasan Basari  
> Universiti Tun Hussein Onn Malaysia (UTHM)

The adaptive proof window scheduling mechanism optimizes zero-knowledge proof generation and verification in blockchain networks, achieving:
- **34.7%** reduction in verification latency
- **28.3%** improvement in throughput
- **19.2%** decrease in resource utilization

## Repository Structure

```
adaptive-proof-scheduling/
├── README.md                    # This file
├── LICENSE                      # MIT License
├── requirements.txt             # Python dependencies
├── configs/
│   ├── simulation_params.yaml   # Core simulation parameters
│   ├── hardware_specs.yaml      # Hardware configuration
│   └── algorithm_params.yaml    # Scheduling algorithm parameters
├── src/
│   ├── __init__.py
│   ├── adaptive_scheduler.py    # Adaptive window scheduling algorithm
│   ├── fixed_scheduler.py       # Fixed window baseline
│   ├── proof_generator.py       # Proof generation simulation
│   ├── verifier_pipeline.py     # Verification pipeline
│   ├── transaction_generator.py # Poisson arrival process
│   └── simulation_runner.py     # Main simulation orchestrator
├── data/
│   ├── raw/
│   │   ├── throughput_results.csv
│   │   ├── latency_results.csv
│   │   └── resource_utilization.csv
│   └── processed/
│       └── summary_statistics.csv
├── scripts/
│   ├── run_experiment.py        # Execute full experiment suite
│   ├── analyze_results.py       # Statistical analysis
│   └── generate_figures.py      # Reproduce paper figures
└── docs/
    └── experimental_setup.md    # Detailed experimental methodology
```

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/[username]/adaptive-proof-scheduling.git
cd adaptive-proof-scheduling

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running Simulations

```bash
# Run complete experiment suite (30 trials per configuration)
python scripts/run_experiment.py --config configs/simulation_params.yaml

# Run single configuration test
python scripts/run_experiment.py --arrival-rate 5000 --trials 5

# Analyze results
python scripts/analyze_results.py --input data/raw/ --output data/processed/

# Generate figures
python scripts/generate_figures.py --input data/processed/
```

## Experimental Parameters

### Simulation Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| Arrival rates | 100–10,000 tx/s | Poisson process mean rates |
| Proof generation time | 50–500 ms | Based on empirical measurements |
| Trials per configuration | 30 | For statistical validity |
| Transactions per trial | 50,000 | After 5,000 warm-up transactions |
| Warm-up period | 5,000 tx | Eliminated from measurements |

### Adaptive Scheduling Algorithm Parameters

| Parameter | Symbol | Value | Description |
|-----------|--------|-------|-------------|
| Smoothing decay | α | 0.15 | Exponential smoothing for arrival rate |
| Proportional gain | K_p | 0.8 | PI controller proportional coefficient |
| Integral gain | K_i | 0.2 | PI controller integral coefficient |
| Expansion factor | β | 1.25 | Multiplicative increase factor |
| Contraction decrement | - | 50 ms | Additive decrease value |
| Minimum adjustment interval | T_adj | 500 ms | Prevents rapid oscillations |
| Hysteresis band | - | ±10% | Prevents threshold chattering |

### Hardware Environment

| Component | Specification |
|-----------|---------------|
| Compute nodes | 8 nodes |
| Processors | Dual AMD EPYC 7763 (128 cores @ 2.45 GHz) |
| Memory | 512 GB DDR4-3200 per node |
| L3 Cache | 256 MB |
| Storage | NVMe SSD (7,000 MB/s sequential read) |
| Network | 100 Gbps Ethernet with RDMA |
| OS | Ubuntu 22.04 LTS, Linux kernel 5.15.0 |

### Cryptographic Configuration

| Component | Implementation |
|-----------|----------------|
| Proving system | Groth16 |
| Elliptic curve | BN254 |
| Framework | arkworks-rs v0.4.2 |
| RNG | ChaCha20 (hardware entropy seeded) |

## Results Summary

### Throughput Comparison (Table 1)

| Arrival Rate (tx/s) | Adaptive (proofs/s) | Fixed (proofs/s) | Improvement |
|---------------------|---------------------|------------------|-------------|
| 1,000 | 987.3 ± 23.4 | 834.6 ± 31.2 | 18.3% |
| 2,500 | 2,456.8 ± 45.7 | 1,987.3 ± 58.9 | 23.6% |
| 5,000 | 4,847.2 ± 89.6 | 3,778.4 ± 112.3 | 28.3% |
| 7,500 | 7,234.5 ± 123.4 | 5,456.7 ± 156.8 | 32.6% |
| 10,000 | 9,234.8 ± 156.2 | 6,882.3 ± 198.7 | 34.2% |

### Latency Distribution at 5,000 tx/s (Table 2)

| Metric | Adaptive | Fixed |
|--------|----------|-------|
| Mean latency | 127.4 ± 18.3 ms | 195.2 ± 34.7 ms |
| Median latency | 119.8 ± 15.6 ms | 178.4 ± 29.3 ms |
| 95th percentile | 168.9 ± 22.4 ms | 287.4 ± 45.8 ms |
| 99th percentile | 198.3 ± 28.7 ms | 356.7 ± 62.4 ms |

## Citation

If you use this code or data in your research, please cite:

```bibtex
@article{shahid2026adaptive,
  title={Adaptive Proof Window Scheduling for Continuous Zero Knowledge Proof Transfer},
  author={Shahid, Muhammad and Marjudi, Suziyanti and Basari, Abd Samad Hasan},
  journal={[Journal Name]},
  year={2026},
  publisher={[Publisher]}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

This research was supported by Universiti Tun Hussein Onn Malaysia (UTHM) through Tier 1 (vot J122).

## Contact

- **Corresponding Author:** Muhammad Shahid
- **Email:** hi240017@student.uthm.edu.my
- **Institution:** Faculty of Computer Science and Information Technology, UTHM
