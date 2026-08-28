"""Long-Range runtime wiring (ADR 0017) — lab arm, WS service, honesty snapshot."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

_LOG = logging.getLogger("abs.long_range.runtime")


def _env_flag_true(name: str) -> bool:
    flag = str(os.environ.get(name, "") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def long_range_feature_armed(config: Any | None = None) -> bool:
    """True when ADR 0017 WS gate may attach (never on prod deployment)."""
    if config is not None:
        mode = str(getattr(config, "deployment_mode", "") or "").strip().lower()
        if mode == "prod":
            return False
        if bool(getattr(config, "feature_long_range", False)):
            return True
    return _env_flag_true("FEATURE_LONG_RANGE")


def build_ws_service(config: Any | None = None) -> Optional[Any]:
    """Build ``WeakSubjectivityService`` from persist/env when Long-Range is armed."""
    if not long_range_feature_armed(config):
        return None
    try:
        from consensus.long_range.checkpoint_store import bind_persisted_ws

        return bind_persisted_ws(
            path=str(os.environ.get("ABS_WS_CHECKPOINT_PATH", "") or "").strip() or None,
            env_height=str(os.environ.get("ABS_WS_ANCHOR_HEIGHT", "") or "").strip(),
            env_hash=str(os.environ.get("ABS_WS_ANCHOR_HASH", "") or "").strip(),
        )
    except Exception as exc:
        _LOG.warning("Long-Range WS service init failed (fail-closed empty): %s", exc)
        from consensus.long_range import WeakSubjectivityService

        return WeakSubjectivityService()


def ws_anchor_snapshot(config: Any | None = None) -> Dict[str, Any]:
    """Checkpoint anchor height/hash when armed; empty dict when off or no anchor."""
    svc = build_ws_service(config)
    if svc is None:
        return {}
    anchor = svc.get_anchor()
    if anchor is None:
        return {"armed": True, "has_anchor": False}
    return {
        "armed": True,
        "has_anchor": True,
        "height": int(getattr(anchor, "height", 0) or 0),
        "block_hash": str(getattr(anchor, "block_hash", "") or ""),
    }


def weak_subjectivity_honesty_snapshot(config: Any | None = None) -> Dict[str, Any]:
    """Honesty surface for consensus status (prod always reports defense off)."""
    mode = str(getattr(config, "deployment_mode", "") or "").strip().lower() if config else ""
    armed = long_range_feature_armed(config)
    snap = ws_anchor_snapshot(config) if armed else {}
    has_anchor = bool(snap.get("has_anchor"))
    long_range_defense = armed and has_anchor and mode != "prod"
    if mode == "prod":
        detail = "prod_profile: feature_long_range hard-off (ADR 0017 lab-only)"
    elif not armed:
        detail = "long_range_off: bounded AncestryWindow only (ADR 0001 stage-1.5)"
    elif not has_anchor:
        detail = "long_range_armed_no_anchor: tip-import refuses (ws_no_anchor)"
    else:
        detail = (
            f"long_range_lab: WS anchor h={snap.get('height')} "
            "(digest-only; not BLS quorum; not mainnet proof)"
        )
    return {
        "long_range_defense": bool(long_range_defense),
        "weak_subjectivity_checkpoints": bool(long_range_defense),
        "long_range_armed": bool(armed and mode != "prod"),
        "ws_anchor_height": int(snap.get("height") or 0) if has_anchor else 0,
        "ws_anchor_hash": str(snap.get("block_hash") or "") if has_anchor else "",
        "tip_ancestry_window": True,
        "tip_ancestry_window_note": (
            "Bounded ancestor rollback (ADR 0001 stage-1.5); "
            "Long-Range WS gate is separate (ADR 0017 lab-only)."
        ),
        "finality_quorum_live": bool(
            getattr(config, "finality_quorum_live", False) if config else False
        ),
        "detail": detail,
    }
