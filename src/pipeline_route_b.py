"""
Route B discrete-event model: batch-dependent proving service.

This model is deliberately separate from ``pipeline.py`` so the Route A
boundary-condition experiment remains reproducible.  The structural change is:

    Sender -> aggregation window -> batch prover -> verifier -> confirmation

A closed window is proved once as a batch.  The batch-proving service time is

    T_prove(k) = c0 + c1 * k * mean_complexity

with a small multiplicative jitter.  This is a modelling assumption intended to
represent fixed setup work amortised across a batch.  It is NOT fitted to real
Groth16/BN254 measurements and must be described that way in the manuscript.

The default constants are chosen only to create an explicit, testable service
trade-off in the simulated system.  They are not claimed as hardware
measurements:

    batch_prover_slots = 8
    c0 = 180 ms
    c1 = 0.60 ms / transaction
    verifier = 5 ms + 0.05 ms / transaction
    P_max = 100 transactions

With these constants the largest batch has an analytical proving ceiling of
about 3.33 ktx/s.  The experiment therefore includes both sub-saturation and
overload regimes and locates the boundary directly rather than assuming it.
"""

import heapq
from collections import deque
from dataclasses import dataclass, field

import numpy as np

import workload as wl
from schedulers import Signals

ARRIVAL, WINDOW_CLOSE, PROVE_DONE, VERIFY_DONE, CONTROL, SAMPLE = range(6)


@dataclass
class RouteBResult:
    scheduler: str
    arrival_rate: float
    workload: str
    trial_id: int
    l_target_ms: float
    window_ms_setting: float = float("nan")

    offered: int = 0
    admitted: int = 0
    dropped: int = 0
    verified: int = 0
    verified_during_measurement: int = 0

    measurement_start: float = float("nan")
    measurement_end: float = float("nan")
    final_time: float = 0.0

    latencies: list = field(default_factory=list)
    cpu_samples: list = field(default_factory=list)
    memory_samples: list = field(default_factory=list)
    queue_samples: list = field(default_factory=list)
    queue_trajectory: list = field(default_factory=list)
    window_trajectory: list = field(default_factory=list)
    batch_sizes: list = field(default_factory=list)
    batch_prove_times_ms: list = field(default_factory=list)
    idc: float = float("nan")

    @property
    def measurement_seconds(self):
        if np.isfinite(self.measurement_start) and np.isfinite(self.measurement_end):
            return max(0.0, self.measurement_end - self.measurement_start)
        return 0.0

    def summary(self):
        lat = np.asarray(self.latencies, float)
        cpu = np.asarray(self.cpu_samples, float)
        mem = np.asarray(self.memory_samples, float)
        q = np.asarray(self.queue_samples, float)
        bs = np.asarray(self.batch_sizes, float)
        pt = np.asarray(self.batch_prove_times_ms, float)
        ms = self.measurement_seconds
        served = self.verified_during_measurement / ms if ms > 0 else float("nan")
        return {
            "scheduler": self.scheduler,
            "arrival_rate_txs": self.arrival_rate,
            "workload": self.workload,
            "trial_id": self.trial_id,
            "l_target_ms": self.l_target_ms,
            "window_ms_setting": self.window_ms_setting,
            "offered": self.offered,
            "admitted": self.admitted,
            "dropped": self.dropped,
            "verified": self.verified,
            "drop_fraction": self.dropped / self.offered if self.offered else 0.0,
            "completion_fraction": self.verified / self.offered if self.offered else 0.0,
            "served_rate_proofs_s": served,
            "served_fraction": served / self.arrival_rate if self.arrival_rate and np.isfinite(served) else float("nan"),
            "mean_latency_ms": float(lat.mean()) if lat.size else float("nan"),
            "median_latency_ms": float(np.median(lat)) if lat.size else float("nan"),
            "p95_latency_ms": float(np.percentile(lat, 95)) if lat.size else float("nan"),
            "p99_latency_ms": float(np.percentile(lat, 99)) if lat.size else float("nan"),
            "std_latency_ms": float(lat.std(ddof=1)) if lat.size > 1 else float("nan"),
            "coeff_variation": float(lat.std(ddof=1) / lat.mean()) if lat.size > 1 and lat.mean() else float("nan"),
            "mean_cpu_pct": float(cpu.mean() * 100) if cpu.size else float("nan"),
            "peak_cpu_pct": float(cpu.max() * 100) if cpu.size else float("nan"),
            "mean_memory_gb": float(mem.mean()) if mem.size else float("nan"),
            "mean_queue_occupancy_pct": float(q.mean() * 100) if q.size else float("nan"),
            "max_queue_occupancy_pct": float(q.max() * 100) if q.size else float("nan"),
            "mean_batch_size": float(bs.mean()) if bs.size else float("nan"),
            "mean_batch_prove_ms": float(pt.mean()) if pt.size else float("nan"),
            "final_waiting": int(self.queue_trajectory[-1][1]) if self.queue_trajectory else 0,
            "idc": self.idc,
            "measurement_seconds": ms,
            "final_time_s": self.final_time,
        }


class RouteBPipeline:
    def __init__(self, scheduler, arrival_rate, trial_id,
                 workload="poisson", n_transactions=50_000, warmup=5_000,
                 batch_prover_slots=8, verifier_slots=8,
                 prove_fixed_ms=180.0, prove_marginal_ms=0.60,
                 verify_fixed_ms=5.0, verify_marginal_ms=0.05,
                 q_max=10_000, control_period_ms=100.0,
                 sample_period_ms=100.0, n_batches_window=20,
                 net_mean_ms=10.0, net_max_ms=50.0,
                 base_memory_gb=8.0):
        self.sch = scheduler
        self.arrivals = wl.build(workload, arrival_rate, seed=trial_id)
        self.rng_prove = np.random.default_rng(trial_id + 1000)
        self.rng_verify = np.random.default_rng(trial_id + 2000)
        self.rng_net = np.random.default_rng(trial_id + 3000)

        self.n_tx = int(n_transactions)
        self.warmup = int(warmup)
        self.batch_prover_slots = int(batch_prover_slots)
        self.verifier_slots = int(verifier_slots)
        self.prove_fixed_ms = float(prove_fixed_ms)
        self.prove_marginal_ms = float(prove_marginal_ms)
        self.verify_fixed_ms = float(verify_fixed_ms)
        self.verify_marginal_ms = float(verify_marginal_ms)
        self.q_max = int(q_max)
        self.control_period = control_period_ms / 1000.0
        self.sample_period = sample_period_ms / 1000.0
        self.n_batches_window = int(n_batches_window)
        self.net_mean_ms = float(net_mean_ms)
        self.net_max_ms = float(net_max_ms)
        self.base_memory_gb = float(base_memory_gb)

        self.res = RouteBResult(
            scheduler=scheduler.name,
            arrival_rate=float(arrival_rate),
            workload=workload,
            trial_id=int(trial_id),
            l_target_ms=float(scheduler.l_target_ms),
            window_ms_setting=float(getattr(scheduler, "window_ms", float("nan"))),
        )

        self.buffer = []
        self.prove_queue = deque()
        self.verify_queue = deque()
        self.busy_provers = 0
        self.busy_verifiers = 0
        self.recent_batch_latency = deque(maxlen=self.n_batches_window)
        self.recent_arrivals = deque()

        self.window_seq = 0
        self._seq = 0
        self._heap = []
        self._arrival_times = []

    def _push(self, t, kind, payload=None):
        self._seq += 1
        heapq.heappush(self._heap, (float(t), self._seq, kind, payload))

    def _waiting_unproved(self):
        return len(self.buffer) + sum(len(b) for b in self.prove_queue)

    def _cpu(self):
        p = self.busy_provers / self.batch_prover_slots if self.batch_prover_slots else 0.0
        v = self.busy_verifiers / self.verifier_slots if self.verifier_slots else 0.0
        return min(1.0, 0.85 * p + 0.15 * v)

    def _net_delay(self):
        # Shifted, clipped exponential: approximately 10 ms mean, bounded at 50 ms.
        x = 1.0 + self.rng_net.exponential(max(1e-9, self.net_mean_ms - 1.0))
        return min(x, self.net_max_ms) / 1000.0

    def _prove_time(self, batch):
        k = len(batch)
        mean_complexity = float(np.mean([tx.complexity for tx in batch])) if batch else 1.0
        jitter = self.rng_prove.uniform(0.95, 1.05)
        ms = (self.prove_fixed_ms + self.prove_marginal_ms * k * mean_complexity) * jitter
        return ms / 1000.0, ms

    def _verify_time(self, k):
        jitter = self.rng_verify.uniform(0.95, 1.05)
        return (self.verify_fixed_ms + self.verify_marginal_ms * k) * jitter / 1000.0

    def _arrival_rate_estimate(self, now):
        while self.recent_arrivals and self.recent_arrivals[0] < now - 1.0:
            self.recent_arrivals.popleft()
        return float(len(self.recent_arrivals))

    def _open_window(self, now):
        self.window_seq += 1
        token = self.window_seq
        self.sch.on_window_opened(now)
        duration = max(0.001, float(self.sch.window_ms) / 1000.0)
        self._push(now + duration, WINDOW_CLOSE, token)
        self.res.window_trajectory.append((now, float(self.sch.window_ms)))

    def _close_one_window(self, now):
        if not self.buffer:
            self._open_window(now)
            return
        k = min(len(self.buffer), int(self.sch.p_max))
        batch = self.buffer[:k]
        del self.buffer[:k]
        self.sch.on_window_closed(now, k)
        self.res.batch_sizes.append(k)
        self.prove_queue.append(batch)
        self._dispatch_provers(now)
        self._open_window(now)
        # If arrivals have already filled more than one P_max, close repeatedly.
        while len(self.buffer) >= int(self.sch.p_max):
            k = int(self.sch.p_max)
            batch = self.buffer[:k]
            del self.buffer[:k]
            self.sch.on_window_closed(now, k)
            self.res.batch_sizes.append(k)
            self.prove_queue.append(batch)
            self._dispatch_provers(now)
            self._open_window(now)

    def _dispatch_provers(self, now):
        while self.prove_queue and self.busy_provers < self.batch_prover_slots:
            batch = self.prove_queue.popleft()
            self.busy_provers += 1
            dt, ms = self._prove_time(batch)
            self.res.batch_prove_times_ms.append(ms)
            self._push(now + dt, PROVE_DONE, batch)

    def _dispatch_verifiers(self, now):
        while self.verify_queue and self.busy_verifiers < self.verifier_slots:
            batch = self.verify_queue.popleft()
            self.busy_verifiers += 1
            self._push(now + self._net_delay() + self._verify_time(len(batch)), VERIFY_DONE, batch)

    def _still_active(self):
        return (self.res.offered < self.n_tx or self.buffer or self.prove_queue or
                self.verify_queue or self.busy_provers or self.busy_verifiers)

    def run(self):
        tx, t = self.arrivals.next(0.0)
        self._push(t, ARRIVAL, tx)
        self._push(self.control_period, CONTROL)
        self._push(self.sample_period, SAMPLE)
        self._open_window(0.0)
        now = 0.0

        while self._heap:
            now, _, kind, payload = heapq.heappop(self._heap)

            if kind == ARRIVAL:
                tx = payload
                self.res.offered += 1
                self._arrival_times.append(now)
                self.recent_arrivals.append(now)

                if self.res.offered == self.warmup + 1:
                    self.res.measurement_start = now
                if self.res.offered == self.n_tx:
                    self.res.measurement_end = now

                if self._waiting_unproved() < self.q_max:
                    self.buffer.append(tx)
                    self.res.admitted += 1
                else:
                    self.res.dropped += 1

                if self.res.offered < self.n_tx:
                    ntx, nt = self.arrivals.next(now)
                    self._push(nt, ARRIVAL, ntx)

                if len(self.buffer) >= int(self.sch.p_max):
                    # Count threshold is an early-close event.
                    self.window_seq += 1  # invalidate previously scheduled timeout
                    self._close_one_window(now)

            elif kind == WINDOW_CLOSE:
                if payload != self.window_seq:
                    continue  # stale timeout from a window closed early
                self._close_one_window(now)

            elif kind == PROVE_DONE:
                self.busy_provers -= 1
                self.verify_queue.append(payload)
                self._dispatch_provers(now)
                self._dispatch_verifiers(now)

            elif kind == VERIFY_DONE:
                self.busy_verifiers -= 1
                batch = payload
                for tx_obj in batch:
                    self.res.verified += 1
                    if (np.isfinite(self.res.measurement_start) and
                            tx_obj.id > self.warmup):
                        self.res.latencies.append((now - tx_obj.arrival_time) * 1000.0)
                    if (np.isfinite(self.res.measurement_start) and
                            np.isfinite(self.res.measurement_end) and
                            self.res.measurement_start <= now <= self.res.measurement_end):
                        self.res.verified_during_measurement += 1
                    elif (np.isfinite(self.res.measurement_start) and
                          not np.isfinite(self.res.measurement_end) and
                          now >= self.res.measurement_start):
                        self.res.verified_during_measurement += 1
                if batch:
                    self.recent_batch_latency.append(
                        float(np.mean([(now - tx.arrival_time) * 1000.0 for tx in batch])))
                self._dispatch_verifiers(now)

            elif kind == CONTROL:
                obs = float(np.mean(self.recent_batch_latency)) if self.recent_batch_latency else 0.0
                s = Signals(
                    observed_latency_ms=obs,
                    cpu_utilization=self._cpu(),
                    queue_depth=self._waiting_unproved(),
                    arrival_rate=self._arrival_rate_estimate(now),
                )
                self.sch.tick(now, s, q_max=self.q_max)
                if self._still_active():
                    self._push(now + self.control_period, CONTROL)

            elif kind == SAMPLE:
                if np.isfinite(self.res.measurement_start) and now >= self.res.measurement_start:
                    waiting = self._waiting_unproved()
                    self.res.cpu_samples.append(self._cpu())
                    self.res.memory_samples.append(self.base_memory_gb + waiting * 1e-4)
                    self.res.queue_samples.append(waiting / self.q_max)
                    self.res.queue_trajectory.append((now, waiting))
                if self._still_active():
                    self._push(now + self.sample_period, SAMPLE)

            if not self._still_active():
                break

        self.res.final_time = now
        if not np.isfinite(self.res.measurement_start):
            self.res.measurement_start = 0.0
        if not np.isfinite(self.res.measurement_end):
            self.res.measurement_end = now
        self.res.idc = wl.index_of_dispersion(self._arrival_times)
        return self.res
