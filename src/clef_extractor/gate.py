"""Strict gate: decide each field's status; required failures go to a human reviewer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .validator import FieldResult


@dataclass(frozen=True)
class Decision:
    action: Literal["accept", "correct", "skip"]
    raw: str | None = None
    value: str | float | None = None


Reviewer = Callable[[FieldResult], Decision]


def apply_gate(results: list[FieldResult], threshold: float, reviewer: Reviewer) -> bool:
    """Set every result's status. Returns True if no required field was left unresolved."""
    complete = True
    for r in results:
        if r.raw is not None and r.score >= threshold:
            r.status = "valid"
        elif not r.field.required:
            r.status = "missing" if r.raw is None else "needs_review"
        else:
            decision = reviewer(r)
            if decision.action == "accept":
                r.status = "user_confirmed"
            elif decision.action == "correct":
                r.raw, r.value, r.status = decision.raw, decision.value, "user_corrected"
            else:
                r.status = "missing" if r.raw is None else "needs_review"
                complete = False
    return complete
