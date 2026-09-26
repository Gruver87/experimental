"""WS checkpoint gossip merge (ADR 0017). Lab-only; digest + optional Ed25519 committee."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore
from consensus.long_range.committee import CommitteeConfig, committee_required
from consensus.long_range.runtime import long_range_feature_armed

_LOG = logging.getLogger("abs.long_range.gossip")

OUTCOME_ADOPTED = "adopted"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_STALE_HEIGHT = "stale_height"
OUTCOME_DIGEST_INVALID = "digest_invalid"
OUTCOME_COMMITTEE_INVALID = "committee_invalid"
OUTCOME_PARSE_ERROR = "parse_error"
OUTCOME_UNARMED = "unarmed"
OUTCOME_NO_PERSIST = "no_persist_path"
OUTCOME_AHEAD_OF_TIP = "ahead_of_tip"
OUTCOME_EQUIVOCATION = "equivocation"
OUTCOME_ANCHOR_HASH_MISMATCH = "anchor_hash_mismatch"
OUTCOME_LOCAL_CONFIG = "local_config_error"


def validate_ws_checkpoint_payload(data: Any) -> Optional[CheckpointCertificate]:
    """Parse and verify a peer WS certificate payload; None when malformed.

    Distinguishes payload failure from local committee config failure via
    raising ``RuntimeError`` with outcome ``local_config_error`` so callers
    do not strike honest peers for a broken local mount.
    """
    if not isinstance(data, Mapping):
        return None
    try:
        cert = CheckpointCertificate.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None
    if not cert.verify_digest():
        return None
    try:
        committee = CommitteeConfig.from_env()
    except ValueError as exc:
        raise RuntimeError(OUTCOME_LOCAL_CONFIG) from exc
    if committee is not None or committee_required():
        if not cert.verify_committee(committee):
            return None
    # Sanity: refuse empty / short / overlong hashes that would brick set_anchor.
    bh = str(cert.anchor.block_hash or "").strip()
    if len(bh) != 64:
        return None
    try:
        int(bh, 16)
    except ValueError:
        return None
    if int(cert.anchor.height) < 0:
        return None
    return cert


def adopt_peer_certificate(
    store: CheckpointStore,
    cert: CheckpointCertificate,
    *,
    local_tip_height: Optional[int] = None,
    local_block_hash_at_anchor: Optional[str] = None,
) -> str:
    """Merge ``cert`` when non-regressive, non-equivocating, and tip-safe.

    ``local_tip_height``: when set, refuse anchors above the local tip so a
    lagging follower cannot brick catch-up with ``ws_below_ws_anchor``.
    ``local_block_hash_at_anchor``: when set and tip already past the anchor
    height, refuse if the local canonical hash differs (poison / fork).
    """
    if not cert.verify_digest():
        return OUTCOME_DIGEST_INVALID
    try:
        committee = CommitteeConfig.from_env()
    except ValueError:
        return OUTCOME_LOCAL_CONFIG
    if committee is not None or committee_required():
        if not cert.verify_committee(committee):
            return OUTCOME_COMMITTEE_INVALID

    ah = int(cert.anchor.height)
    if local_tip_height is not None and ah > int(local_tip_height):
        return OUTCOME_AHEAD_OF_TIP

    if local_block_hash_at_anchor is not None:
        want = str(cert.anchor.block_hash or "").strip().lower().replace("0x", "")
        have = str(local_block_hash_at_anchor or "").strip().lower().replace("0x", "")
        if have and want and have != want:
            return OUTCOME_ANCHOR_HASH_MISMATCH

    latest = store.latest()
    if latest is not None:
        if ah < int(latest.anchor.height):
            return OUTCOME_STALE_HEIGHT
        if ah == int(latest.anchor.height):
            if str(cert.digest) == str(latest.digest):
                return OUTCOME_DUPLICATE
            # Same height, different digest = equivocation / issuer churn.
            return OUTCOME_EQUIVOCATION
    store.push(cert)
    return OUTCOME_ADOPTED


def merge_peer_certificate_dict(
    store: CheckpointStore,
    data: Mapping[str, Any],
    *,
    local_tip_height: Optional[int] = None,
    local_block_hash_at_anchor: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge one peer certificate dict into ``store`` (fail-closed parse)."""
    try:
        cert = validate_ws_checkpoint_payload(data)
    except RuntimeError as exc:
        if str(exc) == OUTCOME_LOCAL_CONFIG:
            return {"outcome": OUTCOME_LOCAL_CONFIG, "adopted": False}
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False}
    if cert is None:
        try:
            probe = CheckpointCertificate.from_dict(data)
            if probe.verify_digest():
                return {"outcome": OUTCOME_COMMITTEE_INVALID, "adopted": False}
        except (KeyError, TypeError, ValueError):
            pass
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False}
    outcome = adopt_peer_certificate(
        store,
        cert,
        local_tip_height=local_tip_height,
        local_block_hash_at_anchor=local_block_hash_at_anchor,
    )
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
    local_tip_height: Optional[int] = None,
    local_block_hash_at_anchor: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply peer WS gossip: merge, optional persist, return honesty outcome.

    Pass ``local_tip_height`` (and optionally the local canonical hash at the
    cert height) so lagging nodes defer future anchors instead of bricking
    catch-up under tip-safety enforce.
    """
    if not long_range_feature_armed(config):
        return {"outcome": OUTCOME_UNARMED, "adopted": False}

    if not isinstance(data, Mapping):
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False}

    path = ws_checkpoint_persist_path(config)
    try:
        local = store if store is not None else CheckpointStore.load_or_empty(path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _LOG.warning("WS checkpoint store load failed: %s", exc)
        return {"outcome": OUTCOME_PARSE_ERROR, "adopted": False, "error": str(exc)}
    result = merge_peer_certificate_dict(
        local,
        data,
        local_tip_height=local_tip_height,
        local_block_hash_at_anchor=local_block_hash_at_anchor,
    )
    if result.get("adopted") and path:
        try:
            local.save(path)
        except OSError as exc:
            _LOG.warning("WS checkpoint persist failed after gossip adopt: %s", exc)
            result["persist_error"] = str(exc)
            result["adopted"] = False
            result["outcome"] = "persist_error"
    elif result.get("adopted") and not path:
        # In-memory only — do not claim a durable adopt.
        result["outcome"] = OUTCOME_NO_PERSIST
        result["adopted"] = False
    result["store_len"] = len(local)
    return result


def latest_ws_checkpoint_payload(config: Any | None = None) -> Optional[Dict[str, Any]]:
    """Serialize the local latest WS cert for outbound gossip (None if none)."""
    if not long_range_feature_armed(config):
        return None
    path = ws_checkpoint_persist_path(config)
    if not path:
        return None
    store = CheckpointStore.load_or_empty(path)
    cert = store.latest()
    if cert is None:
        return None
    return dict(cert.to_dict())
