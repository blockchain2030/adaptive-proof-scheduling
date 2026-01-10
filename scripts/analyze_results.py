#!/usr/bin/env python3
"""
Statistical Analysis Script for Adaptive Proof Window Scheduling Experiments

Performs statistical analysis including:
- Descriptive statistics (mean, std, percentiles)
- Confidence interval calculation (95%)
- Hypothesis testing (Welch's t-test)
- Normality testing (Shapiro-Wilk)
"""

import argparse
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Tuple


def load_data(input_dir: str) -> Dict[str, pd.DataFrame]:
    """Load all CSV data files from input directory"""
    data = {}
    
    throughput_path = Path(input_dir) / "throughput_results.csv"
    latency_path = Path(input_dir) / "latency_results.csv"
    resource_path = Path(input_dir) / "resource_utilization.csv"
    
    if throughput_path.exists():
        data['throughput'] = pd.read_csv(throughput_path)
        print(f"Loaded throughput data: {len(data['throughput'])} records")
        
    if latency_path.exists():
        data['latency'] = pd.read_csv(latency_path)
        print(f"Loaded latency data: {len(data['latency'])} records")
        
    if resource_path.exists():
        data['resource'] = pd.read_csv(resource_path)
        print(f"Loaded resource data: {len(data['resource'])} records")
        
    return data


def calculate_confidence_interval(
    data: np.ndarray, 
    confidence: float = 0.95
) -> Tuple[float, float, float]:
    """
    Calculate confidence interval using t-distribution.
    
    Returns: (mean, lower_bound, upper_bound)
    """
    n = len(data)
    mean = np.mean(data)
    std_err = stats.sem(data)
    
    # t-critical value for (1-confidence)/2 and n-1 degrees of freedom
    t_crit = stats.t.ppf((1 + confidence) / 2, df=n-1)
    
    margin = t_crit * std_err
    return mean, mean - margin, mean + margin


def welch_t_test(
    group1: np.ndarray, 
    group2: np.ndarray
) -> Tuple[float, float]:
    """
    Perform Welch's t-test for unequal variances.
    
    Returns: (t_statistic, p_value)
    """
    t_stat, p_value = stats.ttest_ind(group1, group2, equal_var=False)
    return t_stat, p_value


def shapiro_wilk_test(data: np.ndarray) -> Tuple[float, float]:
    """
    Perform Shapiro-Wilk test for normality.
    
    Returns: (test_statistic, p_value)
    """
    stat, p_value = stats.shapiro(data)
    return stat, p_value


def analyze_throughput(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze throughput data"""
    results = []
    
    for arrival_rate in df['arrival_rate_txs'].unique():
        rate_data = df[df['arrival_rate_txs'] == arrival_rate]
        
        adaptive = rate_data[rate_data['scheduler_type'] == 'adaptive']['mean_throughput_proofs_s'].values
        fixed = rate_data[rate_data['scheduler_type'] == 'fixed']['mean_throughput_proofs_s'].values
        
        if len(adaptive) == 0 or len(fixed) == 0:
            continue
            
        # Descriptive statistics
        adapt_mean, adapt_ci_low, adapt_ci_high = calculate_confidence_interval(adaptive)
        fixed_mean, fixed_ci_low, fixed_ci_high = calculate_confidence_interval(fixed)
        
        # Statistical tests
        t_stat, p_value = welch_t_test(adaptive, fixed)
        
        # Normality tests
        adapt_norm_stat, adapt_norm_p = shapiro_wilk_test(adaptive)
        fixed_norm_stat, fixed_norm_p = shapiro_wilk_test(fixed)
        
        # Improvement calculation
        improvement = (adapt_mean - fixed_mean) / fixed_mean * 100
        
        results.append({
            'arrival_rate': arrival_rate,
            'adaptive_mean': adapt_mean,
            'adaptive_std': np.std(adaptive),
            'adaptive_ci_low': adapt_ci_low,
            'adaptive_ci_high': adapt_ci_high,
            'fixed_mean': fixed_mean,
            'fixed_std': np.std(fixed),
            'fixed_ci_low': fixed_ci_low,
            'fixed_ci_high': fixed_ci_high,
            'improvement_pct': improvement,
            't_statistic': t_stat,
            'p_value': p_value,
            'significant': p_value < 0.001,
            'adaptive_normal': adapt_norm_p > 0.05,
            'fixed_normal': fixed_norm_p > 0.05,
        })
    
    return pd.DataFrame(results)


def analyze_latency(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze latency data"""
    results = []
    
    metrics = ['mean_latency_ms', 'median_latency_ms', 'p95_latency_ms', 'p99_latency_ms']
    
    for arrival_rate in df['arrival_rate_txs'].unique():
        rate_data = df[df['arrival_rate_txs'] == arrival_rate]
        
        for metric in metrics:
            adaptive = rate_data[rate_data['scheduler_type'] == 'adaptive'][metric].values
            fixed = rate_data[rate_data['scheduler_type'] == 'fixed'][metric].values
            
            if len(adaptive) == 0 or len(fixed) == 0:
                continue
                
            adapt_mean, adapt_ci_low, adapt_ci_high = calculate_confidence_interval(adaptive)
            fixed_mean, fixed_ci_low, fixed_ci_high = calculate_confidence_interval(fixed)
            
            t_stat, p_value = welch_t_test(adaptive, fixed)
            
            # Reduction (lower is better for latency)
            reduction = (fixed_mean - adapt_mean) / fixed_mean * 100
            
            results.append({
                'arrival_rate': arrival_rate,
                'metric': metric,
                'adaptive_mean': adapt_mean,
                'adaptive_std': np.std(adaptive),
                'fixed_mean': fixed_mean,
                'fixed_std': np.std(fixed),
                'reduction_pct': reduction,
                't_statistic': t_stat,
                'p_value': p_value,
                'significant': p_value < 0.001,
            })
    
    return pd.DataFrame(results)


def analyze_resources(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze resource utilization data"""
    results = []
    
    metrics = ['mean_cpu_pct', 'peak_cpu_pct', 'mean_memory_gb', 
               'mean_buffer_occupancy_pct', 'max_buffer_occupancy_pct']
    
    for arrival_rate in df['arrival_rate_txs'].unique():
        rate_data = df[df['arrival_rate_txs'] == arrival_rate]
        
        for metric in metrics:
            adaptive = rate_data[rate_data['scheduler_type'] == 'adaptive'][metric].values
            fixed = rate_data[rate_data['scheduler_type'] == 'fixed'][metric].values
            
            if len(adaptive) == 0 or len(fixed) == 0:
                continue
                
            adapt_mean, adapt_ci_low, adapt_ci_high = calculate_confidence_interval(adaptive)
            fixed_mean, fixed_ci_low, fixed_ci_high = calculate_confidence_interval(fixed)
            
            t_stat, p_value = welch_t_test(adaptive, fixed)
            
            # Reduction (lower is better for resource usage)
            reduction = (fixed_mean - adapt_mean) / fixed_mean * 100
            
            results.append({
                'arrival_rate': arrival_rate,
                'metric': metric,
                'adaptive_mean': adapt_mean,
                'adaptive_std': np.std(adaptive),
                'fixed_mean': fixed_mean,
                'fixed_std': np.std(fixed),
                'reduction_pct': reduction,
                't_statistic': t_stat,
                'p_value': p_value,
                'significant': p_value < 0.001,
            })
    
    return pd.DataFrame(results)


def print_summary(throughput_results: pd.DataFrame, 
                  latency_results: pd.DataFrame,
                  resource_results: pd.DataFrame):
    """Print formatted summary of results"""
    print("\n" + "="*80)
    print("EXPERIMENTAL RESULTS SUMMARY")
    print("="*80)
    
    print("\n--- THROUGHPUT ANALYSIS ---")
    print(throughput_results.to_string(index=False))
    
    print("\n--- LATENCY ANALYSIS ---")
    print(latency_results.to_string(index=False))
    
    print("\n--- RESOURCE UTILIZATION ANALYSIS ---")
    print(resource_results.to_string(index=False))
    
    print("\n" + "="*80)
    print("All p-values < 0.001 indicate statistically significant differences")
    print("95% confidence intervals calculated using t-distribution (df=29)")
    print("="*80)


def main():
    parser = argparse.ArgumentParser(
        description='Statistical analysis of adaptive scheduling experiments'
    )
    parser.add_argument(
        '--input', '-i',
        type=str,
        default='data/raw',
        help='Input directory containing CSV data files'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='data/processed',
        help='Output directory for analysis results'
    )
    parser.add_argument(
        '--confidence',
        type=float,
        default=0.95,
        help='Confidence level for intervals (default: 0.95)'
    )
    
    args = parser.parse_args()
    
    # Load data
    print(f"Loading data from {args.input}...")
    data = load_data(args.input)
    
    if not data:
        print("No data files found!")
        sys.exit(1)
    
    # Perform analysis
    throughput_results = None
    latency_results = None
    resource_results = None
    
    if 'throughput' in data:
        print("\nAnalyzing throughput...")
        throughput_results = analyze_throughput(data['throughput'])
        
    if 'latency' in data:
        print("Analyzing latency...")
        latency_results = analyze_latency(data['latency'])
        
    if 'resource' in data:
        print("Analyzing resource utilization...")
        resource_results = analyze_resources(data['resource'])
    
    # Print summary
    print_summary(throughput_results, latency_results, resource_results)
    
    # Save results
    os.makedirs(args.output, exist_ok=True)
    
    if throughput_results is not None:
        throughput_results.to_csv(
            Path(args.output) / 'throughput_analysis.csv', 
            index=False
        )
        
    if latency_results is not None:
        latency_results.to_csv(
            Path(args.output) / 'latency_analysis.csv',
            index=False
        )
        
    if resource_results is not None:
        resource_results.to_csv(
            Path(args.output) / 'resource_analysis.csv',
            index=False
        )
    
    print(f"\nResults saved to {args.output}/")


if __name__ == "__main__":
    main()
