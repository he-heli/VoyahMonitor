from __future__ import annotations

import random


def next_poll_delay_seconds(base_interval: int, jitter_fraction: float) -> float:
    """Return a randomized delay around base_interval (uniform ±jitter_fraction)."""
    if base_interval <= 0:
        return 60.0

    fraction = max(0.0, min(jitter_fraction, 0.5))
    spread = base_interval * fraction
    delay = base_interval + random.uniform(-spread, spread)
    return max(60.0, delay)
