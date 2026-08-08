"""Long-Range / weak-subjectivity research (ADR 0017). Lab-only when FEATURE_LONG_RANGE."""

from consensus.long_range.ancestry_bridge import evaluate_with_window, shares_ancestor_with_anchor
from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.ports import WeakSubjectivityPort, StaleForkDecision
from consensus.long_range.service import WeakSubjectivityService

__all__ = [
    "WeakSubjectivityPort",
    "StaleForkDecision",
    "WeakSubjectivityService",
    "CheckpointCertificate",
    "evaluate_with_window",
    "shares_ancestor_with_anchor",
]
