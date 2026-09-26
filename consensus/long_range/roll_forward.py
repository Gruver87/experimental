"""Autonomous lab WS checkpoint roll-forward (ADR 0017).

Seed-only checkpoints leave the WS floor frozen while tip grows. After a long
soak or mid-run restart, tip−anchor can exceed ``TIP_ANCESTRY_WINDOW_MAX``,
so ancestry walks and deep catch-up lose the path tip→anchor. Rolling the
checkpoint forward (digest + optional Ed25519 committee) keeps Long-Range
defense honest and backfill cheap.

Lab-only. Never arms on prod (``long_range_feature_armed`` gate). Miner-only
issuance: followers adopt via gossip so a lagging tip cannot publish a bad floor.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore
from consensus.long_range.committee import (
    CommitteeConfig,
    committee_required,
    sign_with_keys,
    threshold_for,
)
from consensus.long_range.gossip import ws_checkpoint_persist_path
from consensus.long_range.runtime import long_range_feature_armed

_LOG = logging.getLogger("abs.long_range.roll_forward")

OUTCOME_UNARMED = "unarmed"
OUTCOME_NO_PERSIST = "no_persist_path"
OUTCOME_NO_SEED = "no_seed"
OUTCOME_NOT_MINER = "not_miner"
OUTCOME_NOT_DUE = "not_due"
OUTCOME_BAD_TIP = "bad_tip"
OUTCOME_COMMITTEE_UNSIGNED = "committee_unsigned"
OUTCOME_ISSUED = "issued"

_ISSUER = "lab_ws_roll_forward"


def roll_forward_gap_threshold() -> int:
    """Blocks tip may lead the WS floor before a roll is due.

    Default: half of ``TIP_ANCESTRY_WINDOW_MAX``, clamped to [64, 4096].
    Override with ``ABS_WS_ROLL_GAP``.
    """
    raw = str(os.environ.get("ABS_WS_ROLL_GAP", "") or "").strip()
    if raw:
        try:
            v = int(raw)
            if v >= 1:
                return v
        except (TypeError, ValueError):
            pass
    try:
        win = int(os.environ.get("TIP_ANCESTRY_WINDOW_MAX", "256") or 256)
    except (TypeError, ValueError):
        win = 256
    return max(64, min(4096, max(1, win) // 2))


def committee_secrets_path() -> Optional[str]:
    """Resolve lab committee secrets (explicit env or sibling of pubkeys file)."""
    explicit = str(os.environ.get("ABS_WS_COMMITTEE_SECRETS_FILE", "") or "").strip()
    if explicit:
        return explicit
    pub = str(os.environ.get("ABS_WS_COMMITTEE_PUBKEYS_FILE", "") or "").strip()
    if not pub:
        return None
    sibling = Path(pub).with_name("secrets.json")
    if sibling.is_file():
        return str(sibling)
    return None


def _committee_private_keys_for_quorum() -> List[str]:
    """Load enough private keys to meet the configured threshold (lab mount)."""
    path = committee_secrets_path()
    if not path or not Path(path).is_file():
        return []
    import json

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    members = list(raw.get("members") or [])
    thr = int(raw.get("threshold") or 0)
    if thr < 1:
        thr = threshold_for(len(members))
    privs: List[str] = []
    for m in members:
        if not isinstance(m, dict):
            continue
        pk = str(m.get("private_key") or "").strip()
        if pk:
            privs.append(pk)
        if len(privs) >= thr:
            break
    return privs


def _sign_cert(cert: CheckpointCertificate) -> CheckpointCertificate:
    """Attach Ed25519 quorum when secrets exist; leave digest-only otherwise."""
    privs = _committee_private_keys_for_quorum()
    if not privs:
        return cert
    sigs = sign_with_keys(digest=cert.digest, private_keys_hex=privs)
    return cert.with_signatures(sigs)


def maybe_roll_ws_checkpoint(
    *,
    config: Any | None,
    tip_height: int,
    tip_hash: str,
    gap_threshold: Optional[int] = None,
    mining_enabled: Optional[bool] = None,
    confirm_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """Issue and persist a new WS cert at tip−confirm when the gap is due.

    Pins a confirmed ancestor (not the live tip) so a tip reorg cannot orphan
    the WS floor. Returns an honesty dict with ``outcome`` and optional
    ``payload`` for gossip.
    """
    if not long_range_feature_armed(config):
        return {"outcome": OUTCOME_UNARMED, "issued": False}

    miner = mining_enabled
    if miner is None and config is not None:
        miner = bool(getattr(config, "mining_enabled", False))
    if not miner:
        return {"outcome": OUTCOME_NOT_MINER, "issued": False}

    path = ws_checkpoint_persist_path(config)
    if not path:
        return {"outcome": OUTCOME_NO_PERSIST, "issued": False}

    tip_h = int(tip_height)
    tip_bh = str(tip_hash or "").strip().lower().replace("0x", "")
    if tip_h < 0 or not tip_bh or len(tip_bh) != 64:
        return {"outcome": OUTCOME_BAD_TIP, "issued": False}
    try:
        int(tip_bh, 16)
    except ValueError:
        return {"outcome": OUTCOME_BAD_TIP, "issued": False}

    conf = confirm_depth
    if conf is None:
        raw_c = str(os.environ.get("ABS_WS_ROLL_CONFIRM", "16") or "16").strip()
        try:
            conf = int(raw_c)
        except (TypeError, ValueError):
            conf = 16
    conf = max(0, int(conf))
    # Anchor at confirmed height; tip_hash must be the hash *at that height*
    # when confirm_depth > 0 (caller supplies the confirmed block hash).
    anchor_h = tip_h - conf
    if anchor_h < 0:
        return {
            "outcome": OUTCOME_NOT_DUE,
            "issued": False,
            "gap": 0,
            "threshold": 0,
            "anchor_height": -1,
        }

    store = CheckpointStore.load_or_empty(path)
    latest = store.latest()
    if latest is None:
        return {"outcome": OUTCOME_NO_SEED, "issued": False}

    floor = int(latest.anchor.height)
    gap = anchor_h - floor
    thr = int(gap_threshold) if gap_threshold is not None else roll_forward_gap_threshold()
    if gap < thr:
        return {
            "outcome": OUTCOME_NOT_DUE,
            "issued": False,
            "gap": gap,
            "threshold": thr,
            "anchor_height": floor,
        }

    cert = CheckpointCertificate.issue(
        height=anchor_h,
        block_hash=tip_bh,
        issuer=_ISSUER,
        issued_at_height=tip_h,
    )
    try:
        cert = _sign_cert(cert)
    except (ValueError, TypeError) as exc:
        _LOG.warning("WS roll-forward sign failed: %s", exc)
        return {"outcome": OUTCOME_COMMITTEE_UNSIGNED, "issued": False, "error": str(exc)}

    try:
        committee = CommitteeConfig.from_env()
    except ValueError as exc:
        _LOG.warning("WS roll-forward committee config invalid: %s", exc)
        return {"outcome": OUTCOME_COMMITTEE_UNSIGNED, "issued": False, "error": str(exc)}

    if committee is not None or committee_required():
        if not cert.verify_committee(committee):
            _LOG.warning(
                "WS roll-forward committee unsigned (secrets/pubkeys mismatch?) "
                "tip=%s floor=%s",
                tip_h,
                floor,
            )
            return {
                "outcome": OUTCOME_COMMITTEE_UNSIGNED,
                "issued": False,
                "anchor_height": floor,
                "tip_height": tip_h,
            }

    store.push(cert)
    try:
        store.save(path)
    except OSError as exc:
        _LOG.warning("WS roll-forward persist failed: %s", exc)
        return {
            "outcome": "persist_error",
            "issued": False,
            "error": str(exc),
        }

    payload = dict(cert.to_dict())
    _LOG.info(
        "WS roll-forward issued h=%s (was %s) tip=%s gap=%s thr=%s confirm=%s",
        anchor_h,
        floor,
        tip_h,
        gap,
        thr,
        conf,
    )
    return {
        "outcome": OUTCOME_ISSUED,
        "issued": True,
        "gap": gap,
        "threshold": thr,
        "anchor_height": anchor_h,
        "prev_anchor_height": floor,
        "digest": str(cert.digest),
        "payload": payload,
    }
