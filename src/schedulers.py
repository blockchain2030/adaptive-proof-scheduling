"""
Window schedulers for the aggregation buffer.

Three are implemented:

  AdaptiveWindowScheduler   window duration is the controlled variable,
                            regulated by a supervisory-gated PI law
  FixedWindowScheduler      window duration is a constant (sweepable)
  AdaptiveBatchScheduler    batch size is the controlled variable (AIMD),
                            window duration derived

Every scheduler exposes the same interface so the pipeline is agnostic:

    should_close(now, buffer_len)  -> bool
    on_window_opened(now)
    on_window_closed(now, batch_size)
    tick(now, signals)             -> None      (control cycle; adaptive only)

`signals` is a Signals instance sampled by the pipeline.
"""

from dataclasses import dataclass


@dataclass
class Signals:
    observed_latency_ms: float   # L_observed, mean over last N_b closed batches
    cpu_utilization: float       # U_cpu in [0, 1]
    queue_depth: int             # Q_depth, proofs in the aggregation buffer
    arrival_rate: float          # lambda-hat, exponentially smoothed, tx/s


class BaseScheduler:
    name = "base"

    def __init__(self, p_max, l_target_ms):
        self.p_max = p_max
        self.l_target_ms = l_target_ms
        self.window_ms = None
        self.window_open_at = None

    def on_window_opened(self, now):
        self.window_open_at = now

    def on_window_closed(self, now, batch_size):
        pass

    def should_close(self, now, buffer_len):
        if self.window_open_at is None or buffer_len == 0:
            return False
        elapsed_ms = (now - self.window_open_at) * 1000.0
        return elapsed_ms >= self.window_ms or buffer_len >= self.p_max

    def tick(self, now, signals, q_max=10000):
        pass

    def state(self):
        return {"window_ms": self.window_ms, "p_max": self.p_max}


class FixedWindowScheduler(BaseScheduler):
    """
    Static temporal boundary. The duration is a constructor argument so it can
    be swept; sweeping it is what turns this from an arbitrary baseline into a
    per-rate tuned one.
    """
    name = "fixed"

    def __init__(self, window_ms=100.0, p_max=100, l_target_ms=150.0):
        super().__init__(p_max, l_target_ms)
        self.window_ms = float(window_ms)


class AdaptiveWindowScheduler(BaseScheduler):
    """
    Supervisory-gated proportional-integral control of window duration.

    One control cycle, in the order the manuscript specifies:

      1  sample the three signals
      2  e <- L_target - L_observed
      3  if the actuator is not saturated in the direction of e and the gate
         will act, I <- clamp(I + e*dt, I_min, I_max)          (conditional
         integration; otherwise I is frozen)
      4  u <- Kp*e + Ki*I
      5  evaluate the supervisory gate with hysteresis; contraction wins ties
      6  resolve direction and bound the magnitude by the discipline constants
         (multiplicative increase capped at |u|; additive decrease capped
         at |u|)
      7  W <- clamp(W + dW, W_min, W_max)
      8  record saturation for the next cycle's integration decision

    The minimum adjustment interval T_adj gates the whole cycle.
    """
    name = "adaptive"

    def __init__(self, kp=0.8, ki=0.2, w_min_ms=20.0, w_max_ms=500.0,
                 w_init_ms=100.0, l_target_ms=150.0, p_max=100,
                 beta=1.25, decrement_ms=50.0, t_adj_ms=500.0,
                 hysteresis=0.10, integral_clamp_ms_s=(-500.0, 500.0),
                 control_period_ms=100.0):
        super().__init__(p_max, l_target_ms)
        self.kp, self.ki = kp, ki
        self.w_min, self.w_max = w_min_ms, w_max_ms
        self.window_ms = w_init_ms
        self.beta = beta
        self.decrement_ms = decrement_ms
        self.t_adj_ms = t_adj_ms
        self.h = hysteresis
        self.i_min, self.i_max = integral_clamp_ms_s
        self.control_period_ms = control_period_ms

        self.integral = 0.0
        self.saturated = False
        self.last_adjust = None
        self.expanding = False      # hysteresis memory
        self.contracting = False
        self.history = []           # (t, window_ms, u, integral)

    # ---- supervisory gate ------------------------------------------------
    def _gate(self, s, q_max):
        """
        Expansion needs all three conditions; contraction needs any one.
        The hysteresis band widens the entry threshold and narrows the exit
        threshold, so a signal sitting on a boundary cannot chatter.
        """
        h = self.h
        lo, hi = (1.0 - h), (1.0 + h)
        lt = self.l_target_ms

        exp_entry = (s.observed_latency_ms < 0.7 * lt * lo and
                     s.cpu_utilization < 0.6 * lo and
                     s.queue_depth < 0.5 * q_max * lo)
        exp_hold = (s.observed_latency_ms < 0.7 * lt * hi and
                    s.cpu_utilization < 0.6 * hi and
                    s.queue_depth < 0.5 * q_max * hi)
        expand = exp_hold if self.expanding else exp_entry

        con_entry = (s.observed_latency_ms > 1.2 * lt * hi or
                     s.cpu_utilization > 0.85 * hi or
                     s.queue_depth > 0.8 * q_max * hi)
        con_hold = (s.observed_latency_ms > 1.2 * lt * lo or
                    s.cpu_utilization > 0.85 * lo or
                    s.queue_depth > 0.8 * q_max * lo)
        contract = con_hold if self.contracting else con_entry

        if contract:                      # contraction takes precedence
            expand = False
        self.expanding, self.contracting = expand, contract
        return expand, contract

    # ---- control cycle ---------------------------------------------------
    def tick(self, now, s, q_max=10000):
        if self.last_adjust is not None and \
                (now - self.last_adjust) * 1000.0 < self.t_adj_ms:
            return
        dt = self.control_period_ms / 1000.0
        e = self.l_target_ms - s.observed_latency_ms

        expand, contract = self._gate(s, q_max)
        acting = expand or contract

        # Conditional integration: freeze while the actuator is at a limit in
        # the direction the error is pushing, or while the gate declines to act.
        push_up = e > 0
        at_limit = (self.window_ms >= self.w_max - 1e-9 and push_up) or \
                   (self.window_ms <= self.w_min + 1e-9 and not push_up)
        if acting and not at_limit:
            self.integral = min(max(self.integral + e * dt,
                                    self.i_min), self.i_max)

        u = self.kp * e + self.ki * self.integral

        if contract:
            dw = -min(self.decrement_ms, abs(u))
        elif expand:
            dw = min(self.window_ms * (self.beta - 1.0), abs(u))
        else:
            self.last_adjust = now
            self.history.append((now, self.window_ms, u, self.integral))
            return

        self.window_ms = min(max(self.window_ms + dw, self.w_min), self.w_max)
        self.saturated = self.window_ms in (self.w_min, self.w_max)
        self.last_adjust = now
        self.history.append((now, self.window_ms, u, self.integral))

    def state(self):
        d = super().state()
        d.update(integral=self.integral, saturated=self.saturated)
        return d


class AdaptiveBatchScheduler(BaseScheduler):
    """
    Adaptive batch-size baseline, the actuator used by model-serving systems.

    Batch size is regulated by additive-increase / multiplicative-decrease
    against the same latency target: grow by one while the objective is met,
    halve on violation. Window duration is not controlled; a generous timeout
    keeps a partial batch from stalling indefinitely, exactly as in the
    systems this baseline represents.

    This is the baseline the editor and Reviewer 1 asked for. It makes the
    interval-versus-size comparison a measurement rather than an argument.
    """
    name = "adaptive_batch"

    def __init__(self, p_init=100, p_min=1, p_max_cap=1000,
                 l_target_ms=150.0, timeout_ms=500.0, t_adj_ms=500.0,
                 additive=8, multiplicative=0.5):
        super().__init__(p_init, l_target_ms)
        self.p_min, self.p_cap = p_min, p_max_cap
        self.window_ms = timeout_ms
        self.t_adj_ms = t_adj_ms
        self.additive = additive
        self.multiplicative = multiplicative
        self.last_adjust = None
        self.history = []

    def tick(self, now, s, q_max=10000):
        if self.last_adjust is not None and \
                (now - self.last_adjust) * 1000.0 < self.t_adj_ms:
            return
        if s.observed_latency_ms > self.l_target_ms:
            self.p_max = max(self.p_min,
                             int(self.p_max * self.multiplicative))
        else:
            self.p_max = min(self.p_cap, self.p_max + self.additive)
        self.last_adjust = now
        self.history.append((now, self.p_max, s.observed_latency_ms))


def build(name, **kw):
    if name == "adaptive":
        return AdaptiveWindowScheduler(**kw)
    if name == "fixed":
        return FixedWindowScheduler(**kw)
    if name == "adaptive_batch":
        return AdaptiveBatchScheduler(**kw)
    raise ValueError(f"unknown scheduler: {name}")
