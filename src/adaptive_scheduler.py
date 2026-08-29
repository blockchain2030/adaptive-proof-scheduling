"""
Adaptive Proof-Window Scheduler — manuscript-aligned implementation

Implements the supervisory-gated PI controller described in Algorithm 1 of the
current manuscript revision.

Key properties:
- Window duration W[k] is the only actuator.
- Feedback uses mean completed-batch latency, modelled prover utilization,
  and normalized aggregation-buffer occupancy.
- No arrival-rate or proof-size feed-forward term.
- Conditional integration and integral clamping for anti-windup.
- Stateful hysteresis for expand/contract supervision.
- Multiplicative increase and additive decrease retained as evaluated.
- Simulation time is supplied by the caller; wall-clock time is not used.

Units:
- window duration and latency: milliseconds
- T_c and T_adj: seconds
- K_p: dimensionless
- K_i: 1/second
- integral state: millisecond-seconds
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional
import math


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp value to [lower, upper]."""
    return max(lower, min(upper, value))


@dataclass
class ProofWindow:
    """One aggregation window expressed in simulation time."""
    t_start: float
    t_end: float
    p_max: int
    l_target_ms: float
    transactions: List[object] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return (self.t_end - self.t_start) * 1000.0

    @property
    def is_full(self) -> bool:
        return len(self.transactions) >= self.p_max


@dataclass
class ControllerObservation:
    mean_completed_batch_latency_ms: Optional[float]
    prover_utilization: float
    aggregation_queue_depth: int
    aggregation_queue_occupancy: float


@dataclass
class ControllerDecision:
    now_s: float
    previous_window_ms: float
    new_window_ms: float
    error_ms: Optional[float]
    integral_ms_s: float
    dW_pi_ms: Optional[float]
    applied_dW_ms: float
    expand: bool
    contract: bool
    acting: bool
    at_limit: bool
    startup_guard: bool
    adjustment_interval_guard: bool
    mean_latency_ms: Optional[float]
    prover_utilization: float
    queue_occupancy: float


class AdaptiveScheduler:
    """Supervisory-gated proportional-integral proof-window controller."""

    def __init__(
        self,
        *,
        k_p: float = 0.8,
        k_i_per_s: float = 0.2,
        w_min_ms: float = 20.0,
        w_max_ms: float = 500.0,
        w_init_ms: float = 100.0,
        l_target_ms: float = 260.0,
        p_max: int = 100,
        q_max: int = 10_000,
        beta: float = 1.25,
        delta_dec_ms: float = 50.0,
        control_period_s: float = 0.100,
        min_adjustment_interval_s: float = 0.500,
        hysteresis_half_width: float = 0.10,
        n_latency_batches: int = 20,
        i_min_ms_s: float = -500.0,
        i_max_ms_s: float = 500.0,
        expand_latency_ratio: float = 0.70,
        expand_utilization: float = 0.60,
        expand_queue_occupancy: float = 0.50,
        contract_latency_ratio: float = 1.20,
        contract_utilization: float = 0.85,
        contract_queue_occupancy: float = 0.80,
    ) -> None:
        if not (0.0 < w_min_ms <= w_init_ms <= w_max_ms):
            raise ValueError("Require 0 < W_min <= W_init <= W_max.")
        if l_target_ms <= 0:
            raise ValueError("L_target must be positive.")
        if p_max <= 0 or q_max <= 0:
            raise ValueError("P_max and Q_max must be positive.")
        if beta < 1.0:
            raise ValueError("beta must be >= 1.")
        if delta_dec_ms < 0:
            raise ValueError("delta_dec_ms must be non-negative.")
        if control_period_s <= 0 or min_adjustment_interval_s <= 0:
            raise ValueError("Control timing values must be positive.")
        if min_adjustment_interval_s < control_period_s:
            raise ValueError("T_adj must be >= T_c.")
        if not (0.0 <= hysteresis_half_width < 1.0):
            raise ValueError("hysteresis_half_width must be in [0, 1).")
        if n_latency_batches <= 0:
            raise ValueError("n_latency_batches must be positive.")
        if i_min_ms_s > i_max_ms_s:
            raise ValueError("I_min must be <= I_max.")

        self.k_p = float(k_p)
        self.k_i_per_s = float(k_i_per_s)
        self.w_min_ms = float(w_min_ms)
        self.w_max_ms = float(w_max_ms)
        self.current_window_ms = float(w_init_ms)
        self.l_target_ms = float(l_target_ms)
        self.p_max = int(p_max)
        self.q_max = int(q_max)
        self.beta = float(beta)
        self.delta_dec_ms = float(delta_dec_ms)
        self.control_period_s = float(control_period_s)
        self.min_adjustment_interval_s = float(min_adjustment_interval_s)
        self.h = float(hysteresis_half_width)
        self.n_latency_batches = int(n_latency_batches)
        self.i_min_ms_s = float(i_min_ms_s)
        self.i_max_ms_s = float(i_max_ms_s)
        self.integral_ms_s = 0.0

        self.expand_latency_ratio = float(expand_latency_ratio)
        self.expand_utilization = float(expand_utilization)
        self.expand_queue_occupancy = float(expand_queue_occupancy)
        self.contract_latency_ratio = float(contract_latency_ratio)
        self.contract_utilization = float(contract_utilization)
        self.contract_queue_occupancy = float(contract_queue_occupancy)

        self.expanding = False
        self.contracting = False
        self.last_adjust_s = -math.inf
        self.completed_batch_latencies_ms: Deque[float] = deque(maxlen=self.n_latency_batches)
        self.current_window: Optional[ProofWindow] = None
        self.decision_history: List[ControllerDecision] = []

    def record_completed_batch_latency(self, latency_ms: float) -> None:
        latency_ms = float(latency_ms)
        if math.isfinite(latency_ms) and latency_ms > 0.0:
            self.completed_batch_latencies_ms.append(latency_ms)

    def mean_completed_batch_latency_ms(self) -> Optional[float]:
        if not self.completed_batch_latencies_ms:
            return None
        return sum(self.completed_batch_latencies_ms) / len(self.completed_batch_latencies_ms)

    def observe(self, *, prover_utilization: float, aggregation_queue_depth: int) -> ControllerObservation:
        u = clamp(float(prover_utilization), 0.0, 1.0)
        q_depth = max(0, int(aggregation_queue_depth))
        q = clamp(q_depth / self.q_max, 0.0, 1.0)
        return ControllerObservation(
            mean_completed_batch_latency_ms=self.mean_completed_batch_latency_ms(),
            prover_utilization=u,
            aggregation_queue_depth=q_depth,
            aggregation_queue_occupancy=q,
        )

    def _expand_gate(self, latency_ms: float, u: float, q: float) -> bool:
        if self.expanding:
            return (
                latency_ms < self.expand_latency_ratio * self.l_target_ms * (1.0 + self.h)
                and u < self.expand_utilization * (1.0 + self.h)
                and q < self.expand_queue_occupancy * (1.0 + self.h)
            )
        return (
            latency_ms < self.expand_latency_ratio * self.l_target_ms
            and u < self.expand_utilization
            and q < self.expand_queue_occupancy
        )

    def _contract_gate(self, latency_ms: float, u: float, q: float) -> bool:
        if self.contracting:
            return (
                latency_ms > self.contract_latency_ratio * self.l_target_ms * (1.0 - self.h)
                or u > self.contract_utilization * (1.0 - self.h)
                or q > self.contract_queue_occupancy * (1.0 - self.h)
            )
        return (
            latency_ms > self.contract_latency_ratio * self.l_target_ms
            or u > self.contract_utilization
            or q > self.contract_queue_occupancy
        )

    def _gate(self, latency_ms: float, u: float, q: float) -> tuple[bool, bool]:
        expand = self._expand_gate(latency_ms, u, q)
        contract = self._contract_gate(latency_ms, u, q)
        if expand and contract:
            expand = False  # contraction wins
        self.expanding = bool(expand)
        self.contracting = bool(contract)
        return expand, contract

    def control_step(
        self,
        *,
        now_s: float,
        prover_utilization: float,
        aggregation_queue_depth: int,
    ) -> ControllerDecision:
        """Execute one control evaluation at simulation time now_s."""
        now_s = float(now_s)
        previous_w = self.current_window_ms
        obs = self.observe(
            prover_utilization=prover_utilization,
            aggregation_queue_depth=aggregation_queue_depth,
        )

        # Algorithm 1 line 1: T_adj guard.
        if (now_s - self.last_adjust_s) < self.min_adjustment_interval_s:
            decision = ControllerDecision(
                now_s, previous_w, self.current_window_ms, None,
                self.integral_ms_s, None, 0.0,
                self.expanding, self.contracting, False, False,
                False, True,
                obs.mean_completed_batch_latency_ms,
                obs.prover_utilization,
                obs.aggregation_queue_occupancy,
            )
            self.decision_history.append(decision)
            return decision

        # Algorithm 1 lines 2-3: startup guard.
        l_bar = obs.mean_completed_batch_latency_ms
        if l_bar is None or l_bar <= 0.0 or not math.isfinite(l_bar):
            decision = ControllerDecision(
                now_s, previous_w, self.current_window_ms, None,
                self.integral_ms_s, None, 0.0,
                False, False, False, False,
                True, False,
                l_bar, obs.prover_utilization, obs.aggregation_queue_occupancy,
            )
            self.decision_history.append(decision)
            return decision

        u = obs.prover_utilization
        q = obs.aggregation_queue_occupancy
        error_ms = self.l_target_ms - l_bar

        # Algorithm 1 lines 7-9.
        expand, contract = self._gate(l_bar, u, q)
        acting = expand or contract

        # Algorithm 1 line 10.
        at_limit = (
            (previous_w >= self.w_max_ms and error_ms > 0.0)
            or (previous_w <= self.w_min_ms and error_ms <= 0.0)
        )

        # Algorithm 1 lines 11-13: conditional integration.
        if acting and not at_limit:
            self.integral_ms_s = clamp(
                self.integral_ms_s + error_ms * self.control_period_s,
                self.i_min_ms_s,
                self.i_max_ms_s,
            )

        # Algorithm 1 line 14.
        dW_pi_ms = self.k_p * error_ms + self.k_i_per_s * self.integral_ms_s

        # Algorithm 1 lines 15-17.
        if contract:
            applied_dW_ms = -min(self.delta_dec_ms, abs(dW_pi_ms))
        elif expand:
            applied_dW_ms = min((self.beta - 1.0) * previous_w, abs(dW_pi_ms))
        else:
            applied_dW_ms = 0.0

        # Algorithm 1 line 18.
        self.current_window_ms = clamp(
            previous_w + applied_dW_ms,
            self.w_min_ms,
            self.w_max_ms,
        )

        # Algorithm 1 line 19.
        self.last_adjust_s = now_s

        decision = ControllerDecision(
            now_s=now_s,
            previous_window_ms=previous_w,
            new_window_ms=self.current_window_ms,
            error_ms=error_ms,
            integral_ms_s=self.integral_ms_s,
            dW_pi_ms=dW_pi_ms,
            applied_dW_ms=applied_dW_ms,
            expand=expand,
            contract=contract,
            acting=acting,
            at_limit=at_limit,
            startup_guard=False,
            adjustment_interval_guard=False,
            mean_latency_ms=l_bar,
            prover_utilization=u,
            queue_occupancy=q,
        )
        self.decision_history.append(decision)
        return decision

    def create_window(self, *, now_s: float) -> ProofWindow:
        now_s = float(now_s)
        self.current_window = ProofWindow(
            t_start=now_s,
            t_end=now_s + self.current_window_ms / 1000.0,
            p_max=self.p_max,
            l_target_ms=self.l_target_ms,
        )
        return self.current_window

    def should_close_window(self, *, now_s: float) -> bool:
        if self.current_window is None:
            return False
        return float(now_s) >= self.current_window.t_end or self.current_window.is_full

    def add_to_current_window(self, transaction: object) -> None:
        if self.current_window is None:
            raise RuntimeError("No current window. Call create_window() first.")
        self.current_window.transactions.append(transaction)

    def reset(
        self,
        *,
        w_init_ms: float = 100.0,
        clear_latency_history: bool = True,
        clear_decision_history: bool = True,
    ) -> None:
        if not (self.w_min_ms <= w_init_ms <= self.w_max_ms):
            raise ValueError("w_init_ms is outside actuator limits.")
        self.current_window_ms = float(w_init_ms)
        self.integral_ms_s = 0.0
        self.expanding = False
        self.contracting = False
        self.last_adjust_s = -math.inf
        self.current_window = None
        if clear_latency_history:
            self.completed_batch_latencies_ms.clear()
        if clear_decision_history:
            self.decision_history.clear()

    def get_state(self) -> dict:
        return {
            "window_duration_ms": self.current_window_ms,
            "integral_ms_s": self.integral_ms_s,
            "expanding": self.expanding,
            "contracting": self.contracting,
            "last_adjust_s": self.last_adjust_s,
            "mean_completed_batch_latency_ms": self.mean_completed_batch_latency_ms(),
            "l_target_ms": self.l_target_ms,
            "k_p": self.k_p,
            "k_i_per_s": self.k_i_per_s,
            "beta": self.beta,
            "delta_dec_ms": self.delta_dec_ms,
            "w_min_ms": self.w_min_ms,
            "w_max_ms": self.w_max_ms,
            "control_period_s": self.control_period_s,
            "min_adjustment_interval_s": self.min_adjustment_interval_s,
            "q_max": self.q_max,
            "p_max": self.p_max,
        }


class FixedWindowScheduler:
    """Static-window baseline with the same P_max early-closure rule."""

    def __init__(
        self,
        *,
        window_duration_ms: float = 100.0,
        p_max: int = 100,
        l_target_ms: float = 260.0,
    ) -> None:
        if window_duration_ms <= 0:
            raise ValueError("window_duration_ms must be positive.")
        if p_max <= 0:
            raise ValueError("p_max must be positive.")
        self.window_duration_ms = float(window_duration_ms)
        self.p_max = int(p_max)
        self.l_target_ms = float(l_target_ms)
        self.current_window: Optional[ProofWindow] = None

    def create_window(self, *, now_s: float) -> ProofWindow:
        now_s = float(now_s)
        self.current_window = ProofWindow(
            t_start=now_s,
            t_end=now_s + self.window_duration_ms / 1000.0,
            p_max=self.p_max,
            l_target_ms=self.l_target_ms,
        )
        return self.current_window

    def should_close_window(self, *, now_s: float) -> bool:
        if self.current_window is None:
            return False
        return float(now_s) >= self.current_window.t_end or self.current_window.is_full

    def add_to_current_window(self, transaction: object) -> None:
        if self.current_window is None:
            raise RuntimeError("No current window. Call create_window() first.")
        self.current_window.transactions.append(transaction)


if __name__ == "__main__":
    scheduler = AdaptiveScheduler()

    # Startup guard: no completed-batch latency yet.
    print(scheduler.control_step(
        now_s=0.0,
        prover_utilization=0.25,
        aggregation_queue_depth=0,
    ))

    # Supply N_b valid completed-batch observations.
    for _ in range(20):
        scheduler.record_completed_batch_latency(180.0)

    print(scheduler.control_step(
        now_s=0.5,
        prover_utilization=0.30,
        aggregation_queue_depth=100,
    ))
    print(scheduler.get_state())
