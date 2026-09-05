# Adaptive Proof Scheduling

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
![License](https://img.shields.io/badge/license-BSD%203--Clause-lightgrey.svg)

## Overview

A reproducible discrete-event simulation toolkit for evaluating aggregation-window scheduling in zero-knowledge proof pipelines. It supports fixed and adaptive schedulers, multiple workload models, parameter sweeps, and statistical analysis of latency, served rate, batch size, queueing, admission, and resource metrics.

This repository contains model-based simulation code and generated datasets; it does not execute a production ZK prover or benchmark real prover hardware.

## Repository Structure

```text
src/        Core pipeline, schedulers, controller, and workload models
scripts/    Campaigns, parameter sweeps, analysis, and figure generation
configs/    Simulation, controller, and hardware-model parameters
data/       Raw campaign outputs and processed results
docs/       Experimental setup, provenance, and supporting notes
```

## Quick Start

```bash
git clone https://github.com/blockchain2030/adaptive-proof-scheduling.git
cd adaptive-proof-scheduling

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run a campaign:

```bash
python scripts/run_campaign.py --trials 30
```

Run alternative workloads:

```bash
python scripts/run_campaign.py --workload mmpp --trials 30
python scripts/run_campaign.py --workload onoff --trials 30
```

Run parameter sweeps:

```bash
python scripts/sweep.py --fixed-window --trials 5
python scripts/sweep.py --l-target --trials 5
python scripts/sweep.py --gains --trials 5
```

Analyze a campaign:

```bash
python scripts/analyze.py data/raw/campaign.csv
```

## Experimental Scope

- Workloads: Poisson, Markov-modulated Poisson, and on/off arrivals
- Scheduling: fixed-window and adaptive control variants
- Repeated seeded trials for reproducibility
- Bounded queues with explicit admission, drop, backlog, and completion accounting
- Fixed-window, latency-target, controller-gain, and saturation sweeps
- Raw and processed CSV outputs retained under `data/`

Detailed assumptions and provenance are available in `docs/experimental_setup.md` and `docs/PROVENANCE.md`.

## License

Licensed under the BSD 3-Clause License. See [LICENSE](LICENSE).
