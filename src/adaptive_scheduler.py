"""
Adaptive Proof Window Scheduler

Implements the proportional-integral (PI) control-based adaptive window
scheduling algorithm for continuous zero-knowledge proof transfer.

Reference: Shahid et al., "Adaptive Proof Window Scheduling for Continuous
Zero Knowledge Proof Transfer"
"""

import time
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from collections import deque
import numpy as np


@dataclass
class ProofWindow:
    """
    Proof window definition: W = (t_start, t_end, P_max, L_target)
    
    Attributes:
        t_start: Window start timestamp
        t_end: Window end timestamp  
        p_max: Maximum proof count triggering early closure
        l_target: Target latency bound for window transactions
    """
    t_start: float
    t_end: float
    p_max: int
    l_target: float
    proofs: List = field(default_factory=list)
    
    @property
    def duration(self) -> float:
        """Window duration in milliseconds"""
        return (self.t_end - self.t_start) * 1000
    
    @property
    def is_full(self) -> bool:
        """Check if proof count threshold reached"""
        return len(self.proofs) >= self.p_max


@dataclass
class SystemMetrics:
    """Real-time system metrics for scheduling decisions"""
    arrival_rate: float = 0.0        # λ(t) - transaction arrival rate
    verification_delay: float = 0.0  # δ(t) - verification delay
    proof_size_growth: float = 0.0   # γ(t) - proof size growth rate
    cpu_utilization: float = 0.0     # U_cpu
    queue_depth: float = 0.0         # Q_depth
    observed_latency: float = 0.0    # L_observed


class AdaptiveScheduler:
    """
    Adaptive proof window scheduler using PI control.
    
    The controller adjusts window duration based on the control law:
    ΔW = K_p · (L_target - L_observed) + K_i · ∫(L_target - L_observed)dt
    """
    
    def __init__(
        self,
        # PI controller coefficients
        k_p: float = 0.8,
        k_i: float = 0.2,
        # Window constraints
        w_min: float = 20.0,    # Minimum window duration (ms)
        w_max: float = 500.0,   # Maximum window duration (ms)
        # Target metrics
        l_target: float = 150.0,  # Target latency (ms)
        p_max: int = 100,         # Max proofs per window
        # Adjustment parameters
        expansion_factor: float = 1.25,
        contraction_decrement: float = 50.0,
        min_adjustment_interval: float = 500.0,
        # Stability safeguards
        hysteresis_band: float = 0.10,
        # Arrival rate estimation
        smoothing_alpha: float = 0.15,
        # Queue parameters
        q_max: int = 10000,
    ):
        # Controller parameters
        self.k_p = k_p
        self.k_i = k_i
        
        # Window constraints
        self.w_min = w_min
        self.w_max = w_max
        self.current_window_duration = 100.0  # Initial duration
        
        # Targets
        self.l_target = l_target
        self.p_max = p_max
        
        # Adjustment parameters
        self.expansion_factor = expansion_factor
        self.contraction_decrement = contraction_decrement
        self.min_adjustment_interval = min_adjustment_interval
        self.hysteresis_band = hysteresis_band
        
        # Arrival rate estimation
        self.smoothing_alpha = smoothing_alpha
        
        # Queue
        self.q_max = q_max
        
        # State tracking
        self.integral_error = 0.0
        self.last_adjustment_time = 0.0
        self.arrival_times: deque = deque(maxlen=1000)
        self.latency_history: deque = deque(maxlen=100)
        
        # Current window
        self.current_window: Optional[ProofWindow] = None
        
        # Metrics
        self.metrics = SystemMetrics()
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Decision thresholds
        self.expansion_thresholds = {
            'latency_ratio': 0.7,
            'cpu_utilization': 0.6,
            'queue_occupancy': 0.5,
        }
        self.contraction_thresholds = {
            'latency_ratio': 1.2,
            'cpu_utilization': 0.85,
            'queue_occupancy': 0.8,
        }
        
    def estimate_arrival_rate(self) -> float:
        """
        Estimate instantaneous transaction arrival rate using
        exponential smoothing with decay parameter α = 0.15
        """
        if len(self.arrival_times) < 2:
            return 0.0
            
        # Calculate inter-arrival times
        times = list(self.arrival_times)
        inter_arrivals = np.diff(times)
        
        if len(inter_arrivals) == 0:
            return 0.0
            
        # Exponential smoothing
        smoothed_rate = 0.0
        weight = 1.0
        total_weight = 0.0
        
        for interval in reversed(inter_arrivals):
            if interval > 0:
                rate = 1.0 / interval
                smoothed_rate += weight * rate
                total_weight += weight
                weight *= (1 - self.smoothing_alpha)
                
        return smoothed_rate / total_weight if total_weight > 0 else 0.0
    
    def calculate_window_adjustment(self) -> float:
        """
        Calculate window duration adjustment using PI control law:
        ΔW = K_p · (L_target - L_observed) + K_i · ∫(L_target - L_observed)dt
        """
        error = self.l_target - self.metrics.observed_latency
        
        # Proportional term: fast response to transient disturbances
        p_term = self.k_p * error
        
        # Integral term: eliminates steady-state error
        self.integral_error += error
        i_term = self.k_i * self.integral_error
        
        return p_term + i_term
    
    def should_expand(self) -> bool:
        """
        Evaluate expansion criterion:
        EXPAND if (L_observed < 0.7 · L_target) AND 
                  (U_cpu < 0.6) AND 
                  (Q_depth < 0.5 · Q_max)
        """
        latency_ok = (self.metrics.observed_latency < 
                      self.expansion_thresholds['latency_ratio'] * self.l_target)
        cpu_ok = (self.metrics.cpu_utilization < 
                  self.expansion_thresholds['cpu_utilization'])
        queue_ok = (self.metrics.queue_depth < 
                    self.expansion_thresholds['queue_occupancy'] * self.q_max)
        
        return latency_ok and cpu_ok and queue_ok
    
    def should_contract(self) -> bool:
        """
        Evaluate contraction criterion:
        CONTRACT if (L_observed > 1.2 · L_target) OR 
                   (U_cpu > 0.85) OR 
                   (Q_depth > 0.8 · Q_max)
        """
        latency_violation = (self.metrics.observed_latency > 
                            self.contraction_thresholds['latency_ratio'] * self.l_target)
        cpu_saturation = (self.metrics.cpu_utilization > 
                         self.contraction_thresholds['cpu_utilization'])
        queue_full = (self.metrics.queue_depth > 
                     self.contraction_thresholds['queue_occupancy'] * self.q_max)
        
        return latency_violation or cpu_saturation or queue_full
    
    def apply_hysteresis(self, value: float, threshold: float, 
                         previous_state: bool) -> bool:
        """
        Apply hysteresis band (±10%) to prevent chattering at decision boundaries
        """
        upper = threshold * (1 + self.hysteresis_band)
        lower = threshold * (1 - self.hysteresis_band)
        
        if previous_state:
            return value > lower  # Stay in state until below lower threshold
        else:
            return value > upper  # Enter state only above upper threshold
    
    def adjust_window_duration(self, current_time: float) -> None:
        """
        Adjust window duration based on system state.
        
        Implements:
        - Multiplicative increase (β = 1.25) for expansion
        - Additive decrease (50ms) for contraction
        - Minimum adjustment interval (T_adj = 500ms)
        - Monotonicity constraints during transient periods
        """
        with self._lock:
            # Check minimum adjustment interval
            if (current_time - self.last_adjustment_time) * 1000 < self.min_adjustment_interval:
                return
            
            # Determine action
            expand = self.should_expand()
            contract = self.should_contract()
            
            # Monotonicity constraint: prevent contradictory commands
            if expand and contract:
                return  # No action during conflicting signals
            
            if expand:
                # Multiplicative increase
                new_duration = self.current_window_duration * self.expansion_factor
            elif contract:
                # Additive decrease
                new_duration = self.current_window_duration - self.contraction_decrement
            else:
                return  # No adjustment needed
            
            # Apply constraints
            self.current_window_duration = np.clip(new_duration, self.w_min, self.w_max)
            self.last_adjustment_time = current_time
    
    def update_metrics(self, cpu_util: float, queue_depth: int, 
                       latest_latency: float) -> None:
        """Update system metrics for scheduling decisions"""
        with self._lock:
            self.metrics.cpu_utilization = cpu_util
            self.metrics.queue_depth = queue_depth
            self.metrics.arrival_rate = self.estimate_arrival_rate()
            
            # Update latency with smoothing
            self.latency_history.append(latest_latency)
            if len(self.latency_history) > 0:
                self.metrics.observed_latency = np.mean(list(self.latency_history))
    
    def record_arrival(self, timestamp: float) -> None:
        """Record transaction arrival for rate estimation"""
        self.arrival_times.append(timestamp)
    
    def create_window(self) -> ProofWindow:
        """Create a new proof window with current parameters"""
        t_start = time.time()
        t_end = t_start + (self.current_window_duration / 1000.0)
        
        self.current_window = ProofWindow(
            t_start=t_start,
            t_end=t_end,
            p_max=self.p_max,
            l_target=self.l_target
        )
        return self.current_window
    
    def should_close_window(self) -> bool:
        """Check if current window should be closed"""
        if self.current_window is None:
            return False
            
        current_time = time.time()
        
        # Close if time exceeded or proof count reached
        time_exceeded = current_time >= self.current_window.t_end
        count_reached = self.current_window.is_full
        
        return time_exceeded or count_reached
    
    def get_statistics(self) -> dict:
        """Return current scheduler statistics"""
        return {
            'window_duration_ms': self.current_window_duration,
            'arrival_rate': self.metrics.arrival_rate,
            'observed_latency_ms': self.metrics.observed_latency,
            'cpu_utilization': self.metrics.cpu_utilization,
            'queue_depth': self.metrics.queue_depth,
            'integral_error': self.integral_error,
        }


class FixedWindowScheduler:
    """
    Fixed window scheduler baseline for comparison.
    Uses static temporal boundaries regardless of system state.
    """
    
    def __init__(
        self,
        window_duration: float = 100.0,  # Fixed duration (ms)
        p_max: int = 100,
        l_target: float = 150.0,
    ):
        self.window_duration = window_duration
        self.p_max = p_max
        self.l_target = l_target
        self.current_window: Optional[ProofWindow] = None
    
    def create_window(self) -> ProofWindow:
        """Create a new fixed-duration window"""
        t_start = time.time()
        t_end = t_start + (self.window_duration / 1000.0)
        
        self.current_window = ProofWindow(
            t_start=t_start,
            t_end=t_end,
            p_max=self.p_max,
            l_target=self.l_target
        )
        return self.current_window
    
    def should_close_window(self) -> bool:
        """Check if current window should be closed"""
        if self.current_window is None:
            return False
            
        current_time = time.time()
        return (current_time >= self.current_window.t_end or 
                self.current_window.is_full)


if __name__ == "__main__":
    # Example usage
    scheduler = AdaptiveScheduler(
        k_p=0.8,
        k_i=0.2,
        l_target=150.0,
        p_max=100,
    )
    
    # Create initial window
    window = scheduler.create_window()
    print(f"Created window with duration: {window.duration:.2f}ms")
    
    # Simulate metrics update
    scheduler.update_metrics(cpu_util=0.5, queue_depth=100, latest_latency=120.0)
    
    # Get statistics
    stats = scheduler.get_statistics()
    print(f"Scheduler statistics: {stats}")
