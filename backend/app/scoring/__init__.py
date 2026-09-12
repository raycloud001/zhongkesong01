"""Deterministic, evidence-first scoring helpers.

The package intentionally does not calculate a numeric aptitude score or a
talent type.  It normalizes user supplied evidence and exposes only the
deterministic coverage and audit information that is currently specified.
"""

from .service import (
    build_core,
    compute_task_coverage,
    deduplicate_evidence,
    normalize_evidence,
    score_answers,
)

__all__ = [
    "build_core",
    "compute_task_coverage",
    "deduplicate_evidence",
    "normalize_evidence",
    "score_answers",
]
