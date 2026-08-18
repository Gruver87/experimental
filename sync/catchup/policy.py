"""Pure catch-up refuse / bind helpers (no P2P I/O)."""

from __future__ import annotations

from typing import Any, Mapping, Optional


class CatchUpPolicy:
    """Implements ``SyncCatchUpPolicyPort`` with pure functions."""

    def ahead_refuse_reason(
        self,
        *,
        local_height: int,
        peer_height: int,
        peer_head: str,
        local_block_for_head: Any = None,
        require_head: bool = True,
    ) -> str:
        if not require_head:
            return ""
        try:
            our_h = int(local_height or 0)
            peer_h = int(peer_height or 0)
        except (TypeError, ValueError):
            return ""
        if peer_h <= our_h:
            return ""
        head = str(peer_head or "").strip()
        if not head:
            return "catch_up_no_head"
        blk = local_block_for_head
        if isinstance(blk, Mapping):
            try:
                raw = blk.get("height", blk.get("number", None))
                local_h = int(raw) if raw is not None else -1
            except (TypeError, ValueError):
                local_h = -1
            if local_h >= 0 and local_h != peer_h:
                return "catch_up_head_height_mismatch"
        return ""

    def height_continuity_refuse_reason(
        self,
        block_data: Mapping[str, Any],
        expected_height: int,
        *,
        enabled: bool = True,
    ) -> str:
        if not enabled:
            return ""
        if not isinstance(block_data, Mapping):
            return ""
        try:
            raw = block_data.get("height", block_data.get("number", None))
            if raw is None:
                return ""
            got = int(raw)
            exp = int(expected_height)
        except (TypeError, ValueError):
            return "catch_up_height_continuity_mismatch"
        if got < 0 or exp < 0:
            return ""
        if got != exp:
            return "catch_up_height_continuity_mismatch"
        return ""

    def contiguous_parent_refuse_reason(
        self,
        block_data: Mapping[str, Any],
        expected_parent: str,
        *,
        enabled: bool = True,
    ) -> str:
        if not enabled:
            return ""
        if not isinstance(block_data, Mapping):
            return ""
        expect = str(expected_parent or "").strip().lower()
        if not expect:
            return ""
        got = str(block_data.get("parent_hash") or "").strip().lower()
        if got and got != expect:
            return "catch_up_contiguous_parent_mismatch"
        return ""

    def tip_head_refuse_reason(
        self,
        *,
        local_head: str,
        peer_head: str,
        enabled: bool = True,
    ) -> str:
        if not enabled:
            return ""
        local = str(local_head or "").strip().lower()
        peer = str(peer_head or "").strip().lower()
        if not peer:
            return ""
        if local and peer and local != peer:
            return "catch_up_tip_head_mismatch"
        return ""


def default_catch_up_policy() -> CatchUpPolicy:
    return CatchUpPolicy()
