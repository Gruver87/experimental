"""Long-Range / weak-subjectivity research (ADR 0017). Lab-only when FEATURE_LONG_RANGE."""

from consensus.long_range.ports import WeakSubjectivityPort, StaleForkDecision
from consensus.long_range.service import WeakSubjectivityService

__all__ = [
    "WeakSubjectivityPort",
    "StaleForkDecision",
    "WeakSubjectivityService",
]
