"""Threshold calibration math: false accepts (wrong value passes) vs false flags (true value fails)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

THRESHOLDS: tuple[float, ...] = tuple(round(0.1 * i, 1) for i in range(1, 10))


@dataclass(frozen=True)
class Trial:
    sample: str
    field: str
    raw: str
    truthful: bool
    score: float
    located: bool


@dataclass(frozen=True)
class ThresholdStats:
    threshold: float
    false_accepts: int
    false_flags: int
    wrong_total: int
    true_total: int

    @property
    def false_accept_rate(self) -> float:
        return self.false_accepts / self.wrong_total if self.wrong_total else 0.0

    @property
    def false_flag_rate(self) -> float:
        return self.false_flags / self.true_total if self.true_total else 0.0


def summarize(trials: Iterable[Trial], thresholds: Sequence[float] = THRESHOLDS) -> list[ThresholdStats]:
    trials = list(trials)
    wrong = [t for t in trials if not t.truthful]
    true = [t for t in trials if t.truthful]
    return [
        ThresholdStats(
            threshold=th,
            false_accepts=sum(t.score >= th for t in wrong),
            false_flags=sum(t.score < th for t in true),
            wrong_total=len(wrong),
            true_total=len(true),
        )
        for th in thresholds
    ]


def recommend(stats: Sequence[ThresholdStats]) -> ThresholdStats:
    """Zero false accepts first; then fewest false flags; ties → the higher (safer) threshold."""
    safe = [s for s in stats if s.false_accepts == 0]
    if safe:
        return min(safe, key=lambda s: (s.false_flags, -s.threshold))
    return min(stats, key=lambda s: (s.false_accepts, s.false_flags))
