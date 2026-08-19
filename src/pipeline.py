"""
Discrete-event simulation of the proof-transfer pipeline.

    Sender -> [tx queue] -> Prover pool -> [aggregation buffer]
           -> Window closure -> Verifier pool -> completion

The simulation advances by events on a heap. There is no wall-clock sleeping
and no fixed time step: the simulated clock jumps to the next event, so the
arrival rate is not capped by a step size and a trial costs milliseconds of
real time rather than hours.

Why the window matters in this model
------------------------------------
Verification of a batch of k proofs costs

    T_verify(k) = ver_fixed_ms + ver_marginal_ms * k

so a per-proof fixed cost is amortised over the batch. Short windows produce
many small batches and the verifier pool saturates on the fixed term; long
windows amortise it but each proof waits longer before its batch closes. The
window duration therefore trades verifier capacity against queueing delay,
which is the trade-off the controller regulates.

Admission accounting
--------------------
Both queues are bounded by q_max. Anything arriving at a full queue is dropped
and counted. Every trial reports offered, admitted, dropped, verified and the
queue-depth trajectory, so the questions Reviewer 1 raised about survivorship
bias are answerable from the output rather than by inference.
"""

import heapq
from dataclasses import dataclass, field
import numpy as np

import workload as wl
from schedulers import Signals

ARRIVAL, PROOF_DONE, WINDOW_CHECK, VERIFY_DONE, CONTROL, SAMPLE = range(6)


@dataclass
class TrialResult:
    scheduler: str
    arrival_rate: float
    workload: str
    trial_id: int
    window_ms_setting: float = float("nan")

    offered: int = 0
    admitted: int = 0
    dropped_tx_queue: int = 0
    dropped_buffer: int = 0
    verified: int = 0
    verified_recorded: int = 0

    sim_seconds: float = 0.0
    latencies: list = field(default_factory=list)          # ms, completions
    throughput_samples: list = field(default_factory=list)  # proofs/s, 1 s bins
    cpu_samples: list = field(default_factory=list)
    mem_samples: list = field(default_factory=list)
    buffer_samples: list = field(default_factory=list)
    queue_trajectory: list = field(default_factory=list)    # (t, tx_q, buf)
    window_trajectory: list = field(default_factory=list)   # (t, window_ms)
    batch_sizes: list = field(default_factory=list)
    idc: float = float("nan")

    @property
    def dropped(self):
        return self.dropped_tx_queue + self.dropped_buffer

    def summary(self):
        lat = np.asarray(self.latencies, float)
        thr = np.asarray(self.throughput_samples, float)
        cpu = np.asarray(self.cpu_samples, float)
        mem = np.asarray(self.mem_samples, float)
        buf = np.asarray(self.buffer_samples, float)
        served = self.verified_recorded / self.sim_seconds if self.sim_seconds else 0.0
        return {
            "scheduler": self.scheduler,
            "arrival_rate_txs": self.arrival_rate,
            "workload": self.workload,
            "trial_id": self.trial_id,
            "window_ms_setting": self.window_ms_setting,
            "offered": self.offered,
            "admitted": self.admitted,
            "dropped": self.dropped,
            "verified": self.verified,
            "verified_recorded": self.verified_recorded,
            "drop_fraction": self.dropped / self.offered if self.offered else 0.0,
            "served_rate_proofs_s": served,
            "served_fraction": served / self.arrival_rate if self.arrival_rate else 0.0,
            "mean_throughput_proofs_s": float(thr.mean()) if thr.size else 0.0,
            "std_throughput": float(thr.std(ddof=1)) if thr.size > 1 else 0.0,
            "mean_latency_ms": float(lat.mean()) if lat.size else float("nan"),
            "median_latency_ms": float(np.median(lat)) if lat.size else float("nan"),
            "p95_latency_ms": float(np.percentile(lat, 95)) if lat.size else float("nan"),
            "p99_latency_ms": float(np.percentile(lat, 99)) if lat.size else float("nan"),
            "std_latency_ms": float(lat.std(ddof=1)) if lat.size > 1 else float("nan"),
            "coeff_variation": float(lat.std(ddof=1) / lat.mean()) if lat.size > 1 and lat.mean() else float("nan"),
            "mean_cpu_pct": float(cpu.mean() * 100) if cpu.size else float("nan"),
            "peak_cpu_pct": float(cpu.max() * 100) if cpu.size else float("nan"),
            "mean_memory_gb": float(mem.mean()) if mem.size else float("nan"),
            "mean_buffer_occupancy_pct": float(buf.mean() * 100) if buf.size else float("nan"),
            "max_buffer_occupancy_pct": float(buf.max() * 100) if buf.size else float("nan"),
            "mean_batch_size": float(np.mean(self.batch_sizes)) if self.batch_sizes else float("nan"),
            "final_tx_queue": self.queue_trajectory[-1][1] if self.queue_trajectory else 0,
            "final_buffer": self.queue_trajectory[-1][2] if self.queue_trajectory else 0,
            "idc": self.idc,
            "sim_seconds": self.sim_seconds,
        }


class Pipeline:
    def __init__(self, scheduler, arrival_rate, trial_id,
                 workload="poisson",
                 n_transactions=50_000, warmup=5_000,
                 prover_slots=1024, verifier_slots=8,
                 gen_min_ms=50.0, gen_max_ms=500.0,
                 ver_fixed_ms=8.0, ver_marginal_ms=0.35,
                 net_min_ms=1.0, net_max_ms=50.0,
                 q_max=10_000, control_period_ms=100.0,
                 sample_period_ms=100.0, n_batches_window=20,
                 smoothing_alpha=0.15, base_memory_gb=8.0):
        self.sch = scheduler
        self.arrivals = wl.build(workload, arrival_rate, seed=trial_id)
        self.rng_gen = np.random.default_rng(trial_id + 1000)
        self.rng_ver = np.random.default_rng(trial_id + 2000)
        self.rng_net = np.random.default_rng(trial_id + 3000)

        self.n_tx, self.warmup = n_transactions, warmup
        self.prover_slots, self.verifier_slots = prover_slots, verifier_slots
        self.gen_min, self.gen_max = gen_min_ms, gen_max_ms
        self.ver_fixed, self.ver_marginal = ver_fixed_ms, ver_marginal_ms
        self.net_min, self.net_max = net_min_ms, net_max_ms
        self.q_max = q_max
        self.control_period = control_period_ms / 1000.0
        self.sample_period = sample_period_ms / 1000.0
        self.n_batches_window = n_batches_window
        self.alpha = smoothing_alpha
        self.base_memory_gb = base_memory_gb

        self.res = TrialResult(
            scheduler=scheduler.name, arrival_rate=arrival_rate,
            workload=workload, trial_id=trial_id,
            window_ms_setting=getattr(scheduler, "window_ms", float("nan")))

        self.tx_queue = []        # transactions waiting for a prover
        self.buffer = []          # proofs waiting for window closure
        self.busy_provers = 0
        self.busy_verifiers = 0
        self.recent_batch_latency = []
        self.lambda_hat = 0.0
        self._seq = 0
        self._heap = []
        self._arrival_times = []
        self._bin_start = 0.0
        self._bin_count = 0
        self._recording = False

    def _push(self, t, kind, payload=None):
        self._seq += 1
        heapq.heappush(self._heap, (t, self._seq, kind, payload))

    # ---- service-time draws ---------------------------------------------
    def _gen_time(self, complexity):
        base = self.rng_gen.uniform(self.gen_min, self.gen_max)
        return min(base * complexity, self.gen_max * 1.5) / 1000.0

    def _net_delay(self):
        return self.rng_net.uniform(self.net_min, self.net_max) / 1000.0

    def _verify_time(self, k):
        jitter = self.rng_ver.uniform(0.95, 1.05)
        return (self.ver_fixed + self.ver_marginal * k) * jitter / 1000.0

    def _cpu(self):
        return min(1.0, (self.busy_provers / self.prover_slots) * 0.75 +
                        (self.busy_verifiers / self.verifier_slots) * 0.25)

    # ---- dispatch --------------------------------------------------------
    def _dispatch_provers(self, now):
        while self.tx_queue and self.busy_provers < self.prover_slots:
            tx = self.tx_queue.pop(0)
            self.busy_provers += 1
            self._push(now + self._gen_time(tx.complexity), PROOF_DONE, tx)

    def _dispatch_verifier(self, now):
        if self.busy_verifiers >= self.verifier_slots or not self.buffer:
            return
        if not self.sch.should_close(now, len(self.buffer)):
            return
        k = min(len(self.buffer), self.sch.p_max)
        batch, self.buffer = self.buffer[:k], self.buffer[k:]
        self.busy_verifiers += 1
        self.res.batch_sizes.append(k)
        self._push(now + self._verify_time(k) + self._net_delay(),
                   VERIFY_DONE, batch)
        self.sch.on_window_opened(now)

    # ---- main loop -------------------------------------------------------
    def run(self):
        tx, t = self.arrivals.next(0.0)
        self._push(t, ARRIVAL, tx)
        self._push(self.control_period, CONTROL)
        self._push(self.sample_period, SAMPLE)
        self.sch.on_window_opened(0.0)
        now = 0.0

        while self._heap:
            now, _, kind, payload = heapq.heappop(self._heap)

            if kind == ARRIVAL:
                self.res.offered += 1
                self._arrival_times.append(now)
                if len(self.tx_queue) < self.q_max:
                    self.tx_queue.append(payload)
                    self.res.admitted += 1
                else:
                    self.res.dropped_tx_queue += 1
                if self.res.offered < self.n_tx:
                    ntx, nt = self.arrivals.next(now)
                    self._push(nt, ARRIVAL, ntx)
                self.lambda_hat = (self.alpha * self.arrivals.mean_rate +
                                   (1 - self.alpha) * self.lambda_hat)
                self._dispatch_provers(now)

            elif kind == PROOF_DONE:
                self.busy_provers -= 1
                if len(self.buffer) < self.q_max:
                    self.buffer.append((payload, now))
                else:
                    self.res.dropped_buffer += 1
                self._dispatch_provers(now)
                self._dispatch_verifier(now)

            elif kind == VERIFY_DONE:
                self.busy_verifiers -= 1
                batch = payload
                for tx_obj, _ in batch:
                    lat = (now - tx_obj.arrival_time) * 1000.0
                    if self._recording:
                        self.res.latencies.append(lat)
                    self.res.verified += 1
                    if self._recording:
                        self.res.verified_recorded += 1
                        self._bin_count += 1
                if batch:
                    self.recent_batch_latency.append(
                        (now - batch[0][0].arrival_time) * 1000.0)
                    del self.recent_batch_latency[:-self.n_batches_window]
                while now - self._bin_start >= 1.0:
                    if self._recording:
                        self.res.throughput_samples.append(self._bin_count)
                    self._bin_count = 0
                    self._bin_start += 1.0
                self.sch.on_window_closed(now, len(batch))
                self._dispatch_provers(now)
                self._dispatch_verifier(now)

            elif kind == CONTROL:
                obs = (float(np.mean(self.recent_batch_latency))
                       if self.recent_batch_latency else 0.0)
                self.sch.tick(now, Signals(obs, self._cpu(),
                                           len(self.buffer), self.lambda_hat),
                              q_max=self.q_max)
                self.res.window_trajectory.append((now, self.sch.window_ms))
                if self.res.offered < self.n_tx or self.tx_queue or self.buffer \
                        or self.busy_provers or self.busy_verifiers:
                    self._push(now + self.control_period, CONTROL)
                self._dispatch_verifier(now)

            elif kind == SAMPLE:
                if not self._recording and self.res.offered >= self.warmup:
                    self._recording = True
                    self._bin_start = now
                    self._bin_count = 0
                    self.res.sim_seconds = -now      # offset, closed below
                if self._recording:
                    self.res.cpu_samples.append(self._cpu())
                    self.res.mem_samples.append(
                        self.base_memory_gb +
                        1e-4 * (len(self.tx_queue) + len(self.buffer)))
                    self.res.buffer_samples.append(len(self.buffer) / self.q_max)
                    self.res.queue_trajectory.append(
                        (now, len(self.tx_queue), len(self.buffer)))
                if self.res.offered < self.n_tx or self.tx_queue or self.buffer \
                        or self.busy_provers or self.busy_verifiers:
                    self._push(now + self.sample_period, SAMPLE)

            # termination: everything offered, nothing left anywhere
            if (self.res.offered >= self.n_tx and not self.tx_queue
                    and not self.buffer and not self.busy_provers
                    and not self.busy_verifiers):
                break

        self.res.sim_seconds += now
        self.res.idc = wl.index_of_dispersion(self._arrival_times)
        return self.res
