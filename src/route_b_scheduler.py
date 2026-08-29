"""Route B controller wrapper.

The base scheduler treats an absent latency sample as zero.  In a closed-loop
experiment that would make the controller expand before any batch has completed,
which is not a measurement-driven control action.  This wrapper preserves every
controller parameter and gate rule but suppresses control until at least one
positive completion-latency sample exists.
"""

from schedulers import AdaptiveWindowScheduler


class FeedbackReadyAdaptiveWindowScheduler(AdaptiveWindowScheduler):
    """Adaptive window controller that waits for measured feedback."""

    def tick(self, now, s, q_max=10000):
        if s.observed_latency_ms <= 0.0:
            return
        return super().tick(now, s, q_max=q_max)
