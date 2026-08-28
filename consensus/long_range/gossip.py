"""WS checkpoint gossip merge (ADR 0017 wave-14). Lab-only; digest-only certs."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore
from consensus.long_range.runtime import long_range_feature_armed

_LOG = logging.getLogger("abs.long_range.gossip")

# Outcomes returned by merge helpers (honesty / metrics).
OUTCOME_ADOPTED = "adopted"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_STALE_HEIGHT = "stale_height"
OUTCOME_DIGEST_INVALID = "digest_invalid"
OUTCOME_PARSE_ERROR = "parse_error"
OUTCOME_UNARMED = "unarmed"
OUTCOME_NO_PERSIST = "no_persist_path"


def validate_ws_checkpoint_payload(data: Any) -> Optional[CheckpointCertificate]:
    """Parse and verify a peer WS certificate payload; None when malformed."""
    if not isinstance(data, Mapping):
        return None
    try:
        cert = CheckpointCertificate.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None
    if not cert.verify_digest():
        return None
    return cert


def adopt_peer_certificate(
    store: CheckpointStore,
    cert: CheckpointCertificate,
) -> str:
    """Merge ``cert`` when anchor is not regressive. Returns outcome token."""
    if not cert.verify_digest():
        return OUTCOME_DIGEST_INVALID
    latest = store.latest()
    if latest is not None:
        if int(cert.anchor.height) < int(latest.anchor.height):
            return OUTCOME_STALE_HEIGHT
        if (
            int(cert.anchor.height) == int(latest.anchor.height)
            and str(cert.digest) == str(latest.digest)
        ):
            return OUTCOME_DUPLICATE
    store.push(cert)
    return OUTCOME_ADOPTED


def merge_peer_certificate_dict(
    store: CheckpointStore,
    data: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge one peer certificate dict into ``store`` (fail-closed parse)."""
    cert = validate_ws_checkpoint_payload(data)
    if cert is None:
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False}
    outcome = adopt_peer_certificate(store, cert)
    return {
        "outcome": outcome,
        "adopted": outcome == OUTCOME_ADOPTED,
        "height": int(cert.anchor.height),
        "digest": str(cert.digest),
    }


def ws_checkpoint_persist_path(config: Any | None = None) -> Optional[str]:
    """Persist path from env when Long-Range is armed."""
    if not long_range_feature_armed(config):
        return None
    raw = str(os.environ.get("ABS_WS_CHECKPOINT_PATH", "") or "").strip()
    return raw or None


def ingest_peer_ws_checkpoint(
    *,
    config: Any | None,
    data: Any,
    store: CheckpointStore | None = None,
) -> Dict[str, Any]:
    """Apply peer WS gossip: merge, optional persist, return honesty outcome."""
    if not long_range_feature_armed(config):
        return {"outcome": OUTCOME_UNARMED, "adopted": False}

    if not isinstance(data, Mapping):
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False}

    path = ws_checkpoint_persist_path(config)
    local = store if store is not None else CheckpointStore.load_or_empty(path)
    result = merge_peer_certificate_dict(local, data)
    if result.get("adopted") and path:
        try:
            local.save(path)
        except OSError as exc:
            _LOG.warning("WS checkpoint persist failed after gossip adopt: %s", exc)
            result["persist_error"] = str(exc)
    elif result.get("adopted") and not path:
        result["outcome"] = OUTCOME_NO_PERSIST
    result["store_len"] = len(local)
    return result
