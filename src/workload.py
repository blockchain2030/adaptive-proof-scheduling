"""
Arrival processes for the proof-transfer pipeline.

Three processes are provided. Poisson is the smooth reference case. MMPP and
on/off are bursty and exist because the motivating problem is demand
variability, which a homogeneous Poisson process does not produce.

Every process reports its index of dispersion for counts (IDC) over a fixed
observation interval, so the burstiness of a workload is a measured property of
the generated trace rather than an assertion.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class Transaction:
    id: int
    arrival_time: float          # seconds, simulated clock
    complexity: float            # multiplier on proof-generation time
    priority: int                # 0 = high, 1 = medium, 2 = low


class ArrivalProcess:
    """Base class. Subclasses implement next_interarrival()."""

    def __init__(self, mean_rate, seed, complexity_sigma=0.5,
                 complexity_clip=(0.5, 3.0), priority_p=(0.5, 0.3, 0.2)):
        self.mean_rate = float(mean_rate)
        self.rng = np.random.default_rng(seed)
        self.complexity_sigma = complexity_sigma
        self.complexity_clip = complexity_clip
        self.priority_p = priority_p
        self._counter = 0

    def next_interarrival(self):
        raise NotImplementedError

    def next(self, now):
        """Return (transaction, absolute_arrival_time)."""
        t = now + self.next_interarrival()
        self._counter += 1
        c = float(np.clip(self.rng.lognormal(0.0, self.complexity_sigma),
                          *self.complexity_clip))
        p = int(self.rng.choice([0, 1, 2], p=self.priority_p))
        return Transaction(self._counter, t, c, p), t

    def name(self):
        return type(self).__name__


class PoissonArrivals(ArrivalProcess):
    """Homogeneous Poisson. IDC = 1 by construction."""

    def next_interarrival(self):
        return self.rng.exponential(1.0 / self.mean_rate)


class MMPPArrivals(ArrivalProcess):
    """
    Two-state Markov-modulated Poisson process.

    The chain alternates between a low state at (1 - burst_depth) * mean_rate
    and a high state at burst_ratio * mean_rate. Sojourn times are exponential
    with the given means. Rates are renormalised so the long-run mean equals
    mean_rate, which keeps offered load comparable across workloads.
    """

    def __init__(self, mean_rate, seed, burst_ratio=4.0,
                 mean_low_s=0.50, mean_high_s=0.10, **kw):
        super().__init__(mean_rate, seed, **kw)
        f_high = mean_high_s / (mean_low_s + mean_high_s)
        # r_low * (1 - f_high) + r_low * burst_ratio * f_high = mean_rate
        r_low = mean_rate / (1.0 - f_high + burst_ratio * f_high)
        self.rates = (r_low, r_low * burst_ratio)
        self.means = (mean_low_s, mean_high_s)
        self.state = 0
        self.state_expiry = self.rng.exponential(self.means[0])
        self._clock = 0.0

    def next_interarrival(self):
        gap = self.rng.exponential(1.0 / self.rates[self.state])
        self._clock += gap
        while self._clock >= self.state_expiry:
            self.state ^= 1
            self.state_expiry += self.rng.exponential(self.means[self.state])
        return gap


class OnOffArrivals(ArrivalProcess):
    """
    Two-state on/off source: Poisson at on_rate while on, silent while off.
    Duty cycle is chosen so the long-run mean equals mean_rate.
    """

    def __init__(self, mean_rate, seed, duty=0.35,
                 mean_on_s=0.15, mean_off_s=None, **kw):
        super().__init__(mean_rate, seed, **kw)
        self.on_rate = mean_rate / duty
        self.mean_on = mean_on_s
        self.mean_off = mean_off_s if mean_off_s is not None else \
            mean_on_s * (1.0 - duty) / duty
        self.on = True
        self._clock = 0.0
        self.state_expiry = self.rng.exponential(self.mean_on)

    def next_interarrival(self):
        elapsed = 0.0
        while True:
            if self.on:
                gap = self.rng.exponential(1.0 / self.on_rate)
                if self._clock + gap < self.state_expiry:
                    self._clock += gap
                    return elapsed + gap
                elapsed += self.state_expiry - self._clock
                self._clock = self.state_expiry
                self.on = False
                self.state_expiry += self.rng.exponential(self.mean_off)
            else:
                elapsed += self.state_expiry - self._clock
                self._clock = self.state_expiry
                self.on = True
                self.state_expiry += self.rng.exponential(self.mean_on)


def index_of_dispersion(arrival_times, interval_s=0.05):
    """
    IDC = Var(N) / E(N) for counts in fixed intervals. IDC = 1 for Poisson;
    larger values indicate burstier arrivals. Reported per trial so the
    burstiness of each workload is measured, not assumed.
    """
    a = np.asarray(arrival_times, dtype=float)
    if a.size < 2:
        return float("nan")
    span = a[-1] - a[0]
    nbins = max(int(span / interval_s), 2)
    counts, _ = np.histogram(a, bins=nbins)
    m = counts.mean()
    return float(counts.var(ddof=1) / m) if m > 0 else float("nan")


def build(name, mean_rate, seed):
    if name == "poisson":
        return PoissonArrivals(mean_rate, seed)
    if name == "mmpp":
        return MMPPArrivals(mean_rate, seed)
    if name == "onoff":
        return OnOffArrivals(mean_rate, seed)
    raise ValueError(f"unknown arrival process: {name}")
