"""
Simulation Runner for Adaptive Proof Window Scheduling Experiments

Orchestrates the experimental evaluation with configurable parameters,
multiple trial execution, and comprehensive metric collection.
"""

import time
import random
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import deque
import threading
import queue
import logging

from adaptive_scheduler import AdaptiveScheduler, FixedWindowScheduler, ProofWindow

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Transaction:
    """Transaction awaiting proof generation"""
    id: int
    arrival_time: float
    priority: int = 0  # 0=high, 1=medium, 2=low
    complexity: float = 1.0  # Affects proof generation time


@dataclass
class Proof:
    """Generated cryptographic proof"""
    transaction_id: int
    generation_start: float
    generation_end: float
    verification_start: float = 0.0
    verification_end: float = 0.0
    
    @property
    def generation_time(self) -> float:
        """Proof generation duration in ms"""
        return (self.generation_end - self.generation_start) * 1000
    
    @property
    def verification_time(self) -> float:
        """Verification duration in ms"""
        return (self.verification_end - self.verification_start) * 1000
    
    @property
    def total_latency(self) -> float:
        """End-to-end latency in ms"""
        return (self.verification_end - self.generation_start) * 1000


@dataclass
class ExperimentConfig:
    """Configuration for a single experiment run"""
    arrival_rate: float  # transactions per second
    scheduler_type: str  # 'adaptive' or 'fixed'
    trial_id: int
    transactions_count: int = 50000
    warmup_count: int = 5000
    
    # Proof generation parameters
    min_proof_time_ms: float = 50.0
    max_proof_time_ms: float = 500.0
    
    # Verification parameters
    min_verify_time_ms: float = 5.0
    max_verify_time_ms: float = 20.0


@dataclass 
class ExperimentResults:
    """Results from a single experiment run"""
    config: ExperimentConfig
    
    # Latency metrics (in ms)
    latencies: List[float] = field(default_factory=list)
    mean_latency: float = 0.0
    median_latency: float = 0.0
    p95_latency: float = 0.0
    p99_latency: float = 0.0
    latency_std: float = 0.0
    
    # Throughput metrics
    throughput_samples: List[float] = field(default_factory=list)
    mean_throughput: float = 0.0
    throughput_std: float = 0.0
    
    # Resource utilization
    cpu_samples: List[float] = field(default_factory=list)
    memory_samples: List[float] = field(default_factory=list)
    buffer_occupancy_samples: List[float] = field(default_factory=list)
    
    mean_cpu: float = 0.0
    peak_cpu: float = 0.0
    mean_memory_gb: float = 0.0
    mean_buffer_occupancy: float = 0.0
    max_buffer_occupancy: float = 0.0
    
    # Window statistics (adaptive only)
    window_durations: List[float] = field(default_factory=list)
    
    def compute_statistics(self):
        """Compute summary statistics from collected samples"""
        if self.latencies:
            self.mean_latency = np.mean(self.latencies)
            self.median_latency = np.median(self.latencies)
            self.p95_latency = np.percentile(self.latencies, 95)
            self.p99_latency = np.percentile(self.latencies, 99)
            self.latency_std = np.std(self.latencies)
            
        if self.throughput_samples:
            self.mean_throughput = np.mean(self.throughput_samples)
            self.throughput_std = np.std(self.throughput_samples)
            
        if self.cpu_samples:
            self.mean_cpu = np.mean(self.cpu_samples)
            self.peak_cpu = np.max(self.cpu_samples)
            
        if self.memory_samples:
            self.mean_memory_gb = np.mean(self.memory_samples)
            
        if self.buffer_occupancy_samples:
            self.mean_buffer_occupancy = np.mean(self.buffer_occupancy_samples)
            self.max_buffer_occupancy = np.max(self.buffer_occupancy_samples)


class TransactionGenerator:
    """
    Generates transactions following Poisson arrival process.
    """
    
    def __init__(self, arrival_rate: float, seed: int = None):
        self.arrival_rate = arrival_rate
        self.rng = np.random.default_rng(seed)
        self.transaction_counter = 0
        
    def generate_inter_arrival_time(self) -> float:
        """Generate inter-arrival time from exponential distribution"""
        return self.rng.exponential(1.0 / self.arrival_rate)
    
    def generate_transaction(self, arrival_time: float) -> Transaction:
        """Generate a single transaction"""
        self.transaction_counter += 1
        
        # Complexity distribution based on empirical measurements
        complexity = self.rng.lognormal(0, 0.5)
        complexity = np.clip(complexity, 0.5, 3.0)
        
        # Priority distribution (50% high, 30% medium, 20% low)
        priority = self.rng.choice([0, 1, 2], p=[0.5, 0.3, 0.2])
        
        return Transaction(
            id=self.transaction_counter,
            arrival_time=arrival_time,
            priority=priority,
            complexity=complexity
        )


class ProofGenerator:
    """
    Simulates Groth16 proof generation over BN254 curve.
    """
    
    def __init__(
        self,
        min_time_ms: float = 50.0,
        max_time_ms: float = 500.0,
        seed: int = None
    ):
        self.min_time_ms = min_time_ms
        self.max_time_ms = max_time_ms
        self.rng = np.random.default_rng(seed)
        
    def generate_proof(self, transaction: Transaction) -> Proof:
        """Generate proof for a transaction"""
        start_time = time.time()
        
        # Proof generation time based on complexity
        base_time = self.rng.uniform(self.min_time_ms, self.max_time_ms)
        actual_time = base_time * transaction.complexity
        actual_time = np.clip(actual_time, self.min_time_ms, self.max_time_ms * 1.5)
        
        # Simulate proof generation (sleep)
        time.sleep(actual_time / 1000.0)
        
        end_time = time.time()
        
        return Proof(
            transaction_id=transaction.id,
            generation_start=start_time,
            generation_end=end_time
        )


class VerifierPipeline:
    """
    Simulates cryptographic verification using optimized pairing computations.
    Three-stage pipeline: deserialization, pairing verification, result checking.
    """
    
    def __init__(
        self,
        min_time_ms: float = 5.0,
        max_time_ms: float = 20.0,
        seed: int = None
    ):
        self.min_time_ms = min_time_ms
        self.max_time_ms = max_time_ms
        self.rng = np.random.default_rng(seed)
        
    def verify_proof(self, proof: Proof) -> Proof:
        """Verify a proof through the pipeline"""
        proof.verification_start = time.time()
        
        # Verification time
        verify_time = self.rng.uniform(self.min_time_ms, self.max_time_ms)
        time.sleep(verify_time / 1000.0)
        
        proof.verification_end = time.time()
        return proof


class ResourceMonitor:
    """
    Monitors simulated resource utilization.
    """
    
    def __init__(self, seed: int = None):
        self.rng = np.random.default_rng(seed)
        self.base_cpu = 0.3
        self.base_memory = 8.0  # GB
        
    def get_cpu_utilization(self, queue_depth: int, max_queue: int) -> float:
        """Estimate CPU utilization based on queue state"""
        load_factor = queue_depth / max_queue
        cpu = self.base_cpu + 0.6 * load_factor
        cpu += self.rng.normal(0, 0.02)  # Add noise
        return np.clip(cpu, 0.0, 1.0)
    
    def get_memory_usage(self, queue_depth: int) -> float:
        """Estimate memory usage in GB"""
        # Assume ~100KB per queued transaction
        queue_memory = queue_depth * 0.0001
        total = self.base_memory + queue_memory
        total += self.rng.normal(0, 0.5)
        return max(total, self.base_memory)


class SimulationRunner:
    """
    Main simulation orchestrator.
    """
    
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.results = ExperimentResults(config=config)
        
        # Initialize components
        self.tx_generator = TransactionGenerator(
            arrival_rate=config.arrival_rate,
            seed=config.trial_id
        )
        self.proof_generator = ProofGenerator(
            min_time_ms=config.min_proof_time_ms,
            max_time_ms=config.max_proof_time_ms,
            seed=config.trial_id + 1000
        )
        self.verifier = VerifierPipeline(seed=config.trial_id + 2000)
        self.resource_monitor = ResourceMonitor(seed=config.trial_id + 3000)
        
        # Initialize scheduler
        if config.scheduler_type == 'adaptive':
            self.scheduler = AdaptiveScheduler()
        else:
            self.scheduler = FixedWindowScheduler()
            
        # Queues
        self.tx_queue: deque = deque()
        self.proof_queue: deque = deque()
        self.max_queue_size = 10000
        
        # Metrics tracking
        self.verified_count = 0
        self.throughput_window_start = 0.0
        self.throughput_window_proofs = 0
        
    def run(self) -> ExperimentResults:
        """Execute the simulation"""
        logger.info(f"Starting simulation: {self.config.scheduler_type}, "
                   f"rate={self.config.arrival_rate}, trial={self.config.trial_id}")
        
        current_time = 0.0
        next_arrival = 0.0
        transactions_generated = 0
        warmup_complete = False
        
        self.throughput_window_start = current_time
        
        while transactions_generated < self.config.transactions_count:
            # Generate transaction at arrival time
            if current_time >= next_arrival:
                tx = self.tx_generator.generate_transaction(current_time)
                self.tx_queue.append(tx)
                transactions_generated += 1
                
                # Record arrival for adaptive scheduler
                if isinstance(self.scheduler, AdaptiveScheduler):
                    self.scheduler.record_arrival(current_time)
                
                next_arrival = current_time + self.tx_generator.generate_inter_arrival_time()
            
            # Process transactions
            self._process_transactions(current_time, warmup_complete)
            
            # Update metrics
            self._update_metrics(current_time)
            
            # Check warmup completion
            if not warmup_complete and transactions_generated >= self.config.warmup_count:
                warmup_complete = True
                self._reset_metrics()
                logger.info(f"Warmup complete at transaction {transactions_generated}")
            
            # Advance simulation time
            current_time += 0.001  # 1ms time step
            
        # Compute final statistics
        self.results.compute_statistics()
        
        logger.info(f"Simulation complete: throughput={self.results.mean_throughput:.2f}, "
                   f"latency={self.results.mean_latency:.2f}ms")
        
        return self.results
    
    def _process_transactions(self, current_time: float, record_metrics: bool):
        """Process queued transactions"""
        # Generate proofs for queued transactions
        while self.tx_queue:
            tx = self.tx_queue.popleft()
            proof = self.proof_generator.generate_proof(tx)
            self.proof_queue.append(proof)
            
            # Limit processing per time step
            if len(self.proof_queue) >= 10:
                break
        
        # Verify proofs
        while self.proof_queue:
            proof = self.proof_queue.popleft()
            verified_proof = self.verifier.verify_proof(proof)
            
            if record_metrics:
                self.results.latencies.append(verified_proof.total_latency)
                
            self.verified_count += 1
            self.throughput_window_proofs += 1
            
            # Update throughput every second
            if current_time - self.throughput_window_start >= 1.0:
                if record_metrics:
                    self.results.throughput_samples.append(self.throughput_window_proofs)
                self.throughput_window_proofs = 0
                self.throughput_window_start = current_time
            
            if len(self.proof_queue) >= 10:
                break
    
    def _update_metrics(self, current_time: float):
        """Update resource metrics"""
        queue_depth = len(self.tx_queue) + len(self.proof_queue)
        
        cpu = self.resource_monitor.get_cpu_utilization(queue_depth, self.max_queue_size)
        memory = self.resource_monitor.get_memory_usage(queue_depth)
        buffer_occupancy = queue_depth / self.max_queue_size * 100
        
        self.results.cpu_samples.append(cpu * 100)
        self.results.memory_samples.append(memory)
        self.results.buffer_occupancy_samples.append(buffer_occupancy)
        
        # Update adaptive scheduler
        if isinstance(self.scheduler, AdaptiveScheduler):
            latest_latency = (self.results.latencies[-1] 
                            if self.results.latencies else 100.0)
            self.scheduler.update_metrics(cpu, queue_depth, latest_latency)
            self.scheduler.adjust_window_duration(current_time)
            self.results.window_durations.append(self.scheduler.current_window_duration)
    
    def _reset_metrics(self):
        """Reset metrics after warmup"""
        self.results.latencies.clear()
        self.results.throughput_samples.clear()
        self.results.cpu_samples.clear()
        self.results.memory_samples.clear()
        self.results.buffer_occupancy_samples.clear()
        self.results.window_durations.clear()


def run_experiment_suite(
    arrival_rates: List[float],
    scheduler_types: List[str],
    trials_per_config: int = 30,
    transactions_per_trial: int = 50000,
) -> Dict[str, List[ExperimentResults]]:
    """
    Run complete experiment suite across all configurations.
    """
    results = {}
    
    for scheduler_type in scheduler_types:
        for arrival_rate in arrival_rates:
            key = f"{scheduler_type}_{int(arrival_rate)}"
            results[key] = []
            
            for trial_id in range(trials_per_config):
                config = ExperimentConfig(
                    arrival_rate=arrival_rate,
                    scheduler_type=scheduler_type,
                    trial_id=trial_id,
                    transactions_count=transactions_per_trial,
                )
                
                runner = SimulationRunner(config)
                trial_results = runner.run()
                results[key].append(trial_results)
                
                logger.info(f"Completed {key} trial {trial_id + 1}/{trials_per_config}")
    
    return results


if __name__ == "__main__":
    # Quick test run
    config = ExperimentConfig(
        arrival_rate=1000,
        scheduler_type='adaptive',
        trial_id=0,
        transactions_count=1000,  # Reduced for testing
        warmup_count=100,
    )
    
    runner = SimulationRunner(config)
    results = runner.run()
    
    print(f"\nResults Summary:")
    print(f"  Mean Latency: {results.mean_latency:.2f} ms")
    print(f"  P95 Latency: {results.p95_latency:.2f} ms")
    print(f"  Mean Throughput: {results.mean_throughput:.2f} proofs/s")
    print(f"  Mean CPU: {results.mean_cpu:.1f}%")
    print(f"  Mean Buffer Occupancy: {results.mean_buffer_occupancy:.1f}%")
