"""Long-Range / weak-subjectivity research (ADR 0017). Lab-only when FEATURE_LONG_RANGE."""

from consensus.long_range.ancestry_bridge import evaluate_with_window, shares_ancestor_with_anchor
from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore, bind_persisted_ws
from consensus.long_range.gossip import (
    ingest_peer_ws_checkpoint,
    latest_ws_checkpoint_payload,
    merge_peer_certificate_dict,
    validate_ws_checkpoint_payload,
)
from consensus.long_range.committee import (
    CommitteeConfig,
    CommitteeSignature,
    generate_keypair,
    sign_with_keys,
    threshold_for,
    verify_committee_quorum,
)
from consensus.long_range.ports import WeakSubjectivityPort, StaleForkDecision
from consensus.long_range.runtime import (
    build_ws_service,
    long_range_feature_armed,
    weak_subjectivity_honesty_snapshot,
    ws_anchor_snapshot,
)
from consensus.long_range.service import WeakSubjectivityService

__all__ = [
    "WeakSubjectivityPort",
    "StaleForkDecision",
    "WeakSubjectivityService",
    "CheckpointCertificate",
    "CheckpointStore",
    "bind_persisted_ws",
    "evaluate_with_window",
    "shares_ancestor_with_anchor",
    "build_ws_service",
    "long_range_feature_armed",
    "weak_subjectivity_honesty_snapshot",
    "ws_anchor_snapshot",
    "validate_ws_checkpoint_payload",
    "merge_peer_certificate_dict",
    "ingest_peer_ws_checkpoint",
    "latest_ws_checkpoint_payload",
    "CommitteeConfig",
    "CommitteeSignature",
    "generate_keypair",
    "sign_with_keys",
    "threshold_for",
    "verify_committee_quorum",
]
