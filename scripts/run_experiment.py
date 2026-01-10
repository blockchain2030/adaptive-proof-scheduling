#!/usr/bin/env python3
"""
Experiment Execution Script

Runs the complete experiment suite with configurable parameters.
"""

import argparse
import os
import sys
import yaml
import time
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from simulation_runner import SimulationRunner, ExperimentConfig, run_experiment_suite


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def save_results(results: dict, output_dir: str):
    """Save experiment results to CSV files"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Collect throughput results
    throughput_records = []
    latency_records = []
    resource_records = []
    
    for key, trial_results in results.items():
        parts = key.split('_')
        scheduler_type = parts[0]
        arrival_rate = int(parts[1])
        
        for i, result in enumerate(trial_results):
            # Throughput record
            throughput_records.append({
                'arrival_rate_txs': arrival_rate,
                'scheduler_type': scheduler_type,
                'trial_id': i + 1,
                'mean_throughput_proofs_s': result.mean_throughput,
                'std_throughput': result.throughput_std,
            })
            
            # Latency record
            latency_records.append({
                'arrival_rate_txs': arrival_rate,
                'scheduler_type': scheduler_type,
                'trial_id': i + 1,
                'mean_latency_ms': result.mean_latency,
                'median_latency_ms': result.median_latency,
                'p95_latency_ms': result.p95_latency,
                'p99_latency_ms': result.p99_latency,
                'std_latency_ms': result.latency_std,
                'coeff_variation': result.latency_std / result.mean_latency if result.mean_latency > 0 else 0,
            })
            
            # Resource record
            resource_records.append({
                'arrival_rate_txs': arrival_rate,
                'scheduler_type': scheduler_type,
                'trial_id': i + 1,
                'mean_cpu_pct': result.mean_cpu,
                'peak_cpu_pct': result.peak_cpu,
                'mean_memory_gb': result.mean_memory_gb,
                'mean_buffer_occupancy_pct': result.mean_buffer_occupancy,
                'max_buffer_occupancy_pct': result.max_buffer_occupancy,
            })
    
    # Save to CSV
    pd.DataFrame(throughput_records).to_csv(
        Path(output_dir) / 'throughput_results.csv', index=False
    )
    pd.DataFrame(latency_records).to_csv(
        Path(output_dir) / 'latency_results.csv', index=False
    )
    pd.DataFrame(resource_records).to_csv(
        Path(output_dir) / 'resource_utilization.csv', index=False
    )
    
    print(f"Results saved to {output_dir}/")


def run_single_experiment(
    arrival_rate: float,
    scheduler_type: str,
    trials: int,
    transactions: int = 50000,
    warmup: int = 5000,
) -> list:
    """Run experiment with single configuration"""
    results = []
    
    for trial_id in range(trials):
        config = ExperimentConfig(
            arrival_rate=arrival_rate,
            scheduler_type=scheduler_type,
            trial_id=trial_id,
            transactions_count=transactions,
            warmup_count=warmup,
        )
        
        runner = SimulationRunner(config)
        result = runner.run()
        results.append(result)
        
        print(f"  Trial {trial_id + 1}/{trials} complete")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Run adaptive proof scheduling experiments'
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='configs/simulation_params.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--arrival-rate', '-r',
        type=float,
        help='Single arrival rate to test (overrides config)'
    )
    parser.add_argument(
        '--scheduler', '-s',
        type=str,
        choices=['adaptive', 'fixed', 'both'],
        default='both',
        help='Scheduler type to test'
    )
    parser.add_argument(
        '--trials', '-t',
        type=int,
        default=30,
        help='Number of trials per configuration'
    )
    parser.add_argument(
        '--transactions', '-n',
        type=int,
        default=50000,
        help='Transactions per trial'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='data/raw',
        help='Output directory for results'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick test run (reduced parameters)'
    )
    
    args = parser.parse_args()
    
    # Quick test mode
    if args.quick:
        args.trials = 3
        args.transactions = 1000
        print("Quick test mode enabled")
    
    print(f"Starting experiments at {datetime.now().isoformat()}")
    print(f"Configuration:")
    print(f"  Trials per config: {args.trials}")
    print(f"  Transactions per trial: {args.transactions}")
    
    # Determine configurations to run
    if args.arrival_rate:
        arrival_rates = [args.arrival_rate]
    else:
        # Load from config or use defaults
        arrival_rates = [1000, 2500, 5000, 7500, 10000]
    
    if args.scheduler == 'both':
        scheduler_types = ['adaptive', 'fixed']
    else:
        scheduler_types = [args.scheduler]
    
    print(f"  Arrival rates: {arrival_rates}")
    print(f"  Scheduler types: {scheduler_types}")
    print()
    
    # Run experiments
    all_results = {}
    start_time = time.time()
    
    for scheduler_type in scheduler_types:
        for arrival_rate in arrival_rates:
            key = f"{scheduler_type}_{int(arrival_rate)}"
            print(f"Running {key}...")
            
            results = run_single_experiment(
                arrival_rate=arrival_rate,
                scheduler_type=scheduler_type,
                trials=args.trials,
                transactions=args.transactions,
            )
            
            all_results[key] = results
            
            # Print intermediate summary
            mean_throughput = np.mean([r.mean_throughput for r in results])
            mean_latency = np.mean([r.mean_latency for r in results])
            print(f"  -> Throughput: {mean_throughput:.1f} proofs/s, Latency: {mean_latency:.1f} ms")
            print()
    
    # Save results
    save_results(all_results, args.output)
    
    elapsed = time.time() - start_time
    print(f"\nExperiments completed in {elapsed/60:.1f} minutes")
    print(f"Results saved to {args.output}/")


if __name__ == "__main__":
    main()
