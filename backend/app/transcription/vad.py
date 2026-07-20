"""Dependency-free energy voice activity detection."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike


class EnergyVoiceActivityDetector:
    """Classify a PCM frame using its root-mean-square energy.

    This intentionally simple detector is deterministic and suitable for the
    Phase 1 near-real-time buffer.  It is replaceable because callers depend on
    the small ``is_speech`` interface, not on a particular VAD package.
    """

    def __init__(self, threshold: float = 0.015) -> None:
        threshold = float(threshold)
        if not math.isfinite(threshold) or threshold <= 0.0:
            raise ValueError("threshold must be a positive finite number")
        self.threshold = threshold

    @staticmethod
    def rms(samples: ArrayLike) -> float:
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size == 0:
            return 0.0
        finite = np.nan_to_num(audio, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)
        # float64 accumulation avoids overflow and makes threshold behaviour
        # stable for both short callback frames and larger unit-test arrays.
        return float(np.sqrt(np.mean(np.square(finite, dtype=np.float64))))

    def is_speech(self, samples: ArrayLike) -> bool:
        return self.rms(samples) >= self.threshold

    def __call__(self, samples: ArrayLike) -> bool:
        return self.is_speech(samples)
