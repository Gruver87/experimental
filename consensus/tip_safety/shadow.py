"""Tip-safety import gate: shadow observation and optional enforce (stages 2–3).

Stage 2 (``enabled``, ``enforce=False``): evaluate candidates, never block import.
Stage 3 (``enforce=True``): policy reject or observer failure → refuse import
fail-closed. Exceptions inside the observer never escape into P2P as crashes;
under enforce they become refuse.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Mapping, MutableMapping, Optional

from consensus.tip_safety.errors import TipValidationError
from consensus.tip_safety.service import TipSafetyService
from consensus.tip_safety.tip_state import TipState
from consensus.tip_safety.types import ApplyDecision, BlockRef

_LOG = logging.getLogger("abs.tip_safety.shadow")

_GENESIS_HASH = "0" * 64


def _optional_ws_service(config: Any | None = None) -> Optional[Any]:
    """Attach ADR 0017 WS gate when ``feature_long_range`` or ``FEATURE_LONG_RANGE``."""
    from consensus.long_range.runtime import build_ws_service

    return build_ws_service(config)


def _optional_ws_service_from_env() -> Optional[Any]:
    """Backward-compatible alias (env-only callers / legacy tests)."""
    return _optional_ws_service(None)


def block_ref_from_mapping(data: Mapping[str, Any]) -> BlockRef:
    """Build a ``BlockRef`` from a block dict / announce body.

    Args:
        data: Mapping with ``height``/``number``, ``hash``, ``parent_hash``.

    Returns:
        Validated ``BlockRef``.

    Raises:
        TipValidationError: Missing or invalid fields.
    """
    if not isinstance(data, Mapping):
        raise TipValidationError(
            f"block data must be a mapping, got {type(data).__name__}"
        )
    try:
        height = int(data.get("height", data.get("number", -1)))
    except (TypeError, ValueError) as exc:
        raise TipValidationError(f"invalid block height: {exc}") from exc
    raw_hash = data.get("hash", data.get("block_hash", ""))
    parent = data.get("parent_hash", "")
    if height == 0 and not str(parent or "").strip():
        parent = ""
    return BlockRef(
        height=height,
        block_hash=str(raw_hash or ""),
        parent_hash=str(parent or ""),
    )


def tip_state_from_chain(blockchain: Any) -> TipState:
    """Construct ``TipState`` from a blockchain-like object.

    Args:
        blockchain: Object exposing ``get_height``, ``get_block``, optional
            ``GENESIS_HASH`` / ``get_last_block``.

    Returns:
        Tip state anchored at the current tip (finalized unset until adapter).

    Raises:
        TipValidationError: Chain tip cannot be represented as ``BlockRef``.
    """
    if blockchain is None:
        raise TipValidationError("blockchain is required to sync tip state")
    try:
        # Height 0 is a real genesis tip — do not coerce via ``or 0`` only.
        raw_h = blockchain.get_height()
        height = int(raw_h) if raw_h is not None else -1
    except Exception as exc:
        raise TipValidationError(f"get_height failed: {exc}") from exc

    genesis = str(getattr(blockchain, "GENESIS_HASH", _GENESIS_HASH) or _GENESIS_HASH)

    # Canonical tip is get_height(), not a stale get_last_block() that can sit
    # ahead of persisted height after a queued import or a failed catch-up.
    block: Optional[Mapping[str, Any]] = None
    try:
        if height >= 0 and hasattr(blockchain, "get_block"):
            block = blockchain.get_block(height)
        if not isinstance(block, Mapping) and hasattr(blockchain, "get_last_block"):
            last = blockchain.get_last_block()
            if isinstance(last, Mapping):
                try:
                    last_h = int(last.get("height", -1) or -1)
                except (TypeError, ValueError) as exc:
                    raise TipValidationError(
                        f"last_block height is not an int: {exc}"
                    ) from exc
                if height < 0 or last_h == height:
                    block = last
                else:
                    raise TipValidationError(
                        f"tip height mismatch get_height={height} last_block={last_h}"
                    )
    except TipValidationError:
        raise
    except Exception as exc:
        raise TipValidationError(f"tip block lookup failed: {exc}") from exc

    # Empty chain: no last block — anchor at the pre-genesis sentinel hash.
    if not isinstance(block, Mapping):
        if height > 0:
            raise TipValidationError(f"missing tip block at height {height}")
        return TipState(
            head=BlockRef(height=0, block_hash=genesis, parent_hash=""),
            finalized=None,
        )

    return TipState(head=block_ref_from_mapping(block), finalized=None)


class TipSafetyShadowObserver:
    """Tip-safety observer / gate for import candidates.

    Args:
        enabled: When True, evaluate every candidate (shadow metrics).
        enforce: When True, refuse import on policy reject or observer failure.
            Implies ``enabled``.
    """

    __slots__ = (
        "_enabled",
        "_enforce",
        "_config",
        "_lock",
        "_service",
        "_last_decision",
        "observe_total",
        "accept_total",
        "reject_total",
        "reject_by_code",
        "diverge_policy_reject_import_ok",
        "diverge_policy_accept_import_fail",
        "enforce_refuse_total",
        "observe_errors",
        "sync_errors",
        "last_local_forge_height",
    )

    def __init__(
        self,
        enabled: bool = False,
        enforce: bool = False,
        config: Any | None = None,
    ) -> None:
        self._enforce = bool(enforce)
        self._enabled = bool(enabled) or self._enforce
        self._config = config
        self._lock = threading.RLock()
        self._service: Optional[TipSafetyService] = None
        self._last_decision: Optional[ApplyDecision] = None
        self.observe_total = 0
        self.accept_total = 0
        self.reject_total = 0
        self.reject_by_code: Dict[str, int] = {}
        self.diverge_policy_reject_import_ok = 0
        self.diverge_policy_accept_import_fail = 0
        self.enforce_refuse_total = 0
        self.observe_errors = 0
        self.sync_errors = 0
        self.last_local_forge_height = 0

    def note_local_forge(self, height: int) -> None:
        """Record the height just applied on the local mining path.

        NEW_BLOCK echo of that height (or the next pipeline height) must not
        be treated as a skip-ahead / unknown parent against a stale window.
        """
        try:
            h = int(height or 0)
        except (TypeError, ValueError):
            return
        if h <= 0:
            return
        with self._lock:
            if h > int(self.last_local_forge_height or 0):
                self.last_local_forge_height = h

    @property
    def enabled(self) -> bool:
        """Whether observation is active."""
        return self._enabled

    @property
    def enforce(self) -> bool:
        """Whether policy rejects block the import path."""
        return self._enforce

    def status(self) -> Dict[str, Any]:
        """Export counters for ``/metrics`` / security status."""
        with self._lock:
            return {
                "tip_safety_shadow_enabled": self._enabled,
                "tip_safety_enforce": self._enforce,
                "tip_safety_shadow_observe_total": int(self.observe_total),
                "tip_safety_shadow_accept_total": int(self.accept_total),
                "tip_safety_shadow_reject_total": int(self.reject_total),
                "tip_safety_shadow_reject_by_code": dict(self.reject_by_code),
                "tip_safety_shadow_diverge_policy_reject_import_ok": int(
                    self.diverge_policy_reject_import_ok
                ),
                "tip_safety_shadow_diverge_policy_accept_import_fail": int(
                    self.diverge_policy_accept_import_fail
                ),
                "tip_safety_enforce_refuse_total": int(self.enforce_refuse_total),
                "tip_safety_shadow_observe_errors": int(self.observe_errors),
                "tip_safety_shadow_sync_errors": int(self.sync_errors),
                "tip_safety_shadow_head_height": (
                    int(self._service.state.head.height)
                    if self._service is not None
                    else -1
                ),
            }

    def sync_from_chain(self, blockchain: Any) -> bool:
        """Reset internal tip state from the live chain tip.

        Args:
            blockchain: Blockchain facade.

        Returns:
            True on success; False on failure (never raises).
        """
        if not self._enabled:
            return False
        try:
            state = tip_state_from_chain(blockchain)
            max_blocks = 256
            try:
                import os

                max_blocks = int(os.environ.get("TIP_ANCESTRY_WINDOW_MAX", "256") or 256)
            except (TypeError, ValueError):
                max_blocks = 256
            ws = _optional_ws_service(self._config)
            with self._lock:
                self._service = TipSafetyService(
                    state,
                    ancestry_max_blocks=max(1, max_blocks),
                    ws_service=ws,
                )
            return True
        except Exception as exc:
            with self._lock:
                self.sync_errors += 1
            _LOG.warning("tip_safety sync failed: %s", exc)
            return False

    def observe_before_import(
        self,
        block_data: Mapping[str, Any],
        blockchain: Any,
    ) -> Optional[ApplyDecision]:
        """Evaluate a candidate before legacy import.

        Args:
            block_data: Peer / queue block mapping.
            blockchain: Used to lazy-sync tip state when unset.

        Returns:
            Decision or ``None`` if disabled / observer error.
        """
        if not self._enabled:
            return None
        try:
            if self._service is None:
                self.sync_from_chain(blockchain)
            else:
                # Bind the window to live get_height() before evaluate. A stale
                # head (341) while the chain is at 339 turns catch-up of #340
                # into a false "deep reorg" and wedges /health/ready (503).
                try:
                    raw_h = blockchain.get_height()
                    chain_h = int(raw_h) if raw_h is not None else -1
                except (TypeError, ValueError) as exc:
                    _LOG.warning("[TipSafety] get_height parse failed: %s", exc)
                    chain_h = -1
                except Exception as exc:
                    _LOG.warning("[TipSafety] get_height failed: %s", exc)
                    chain_h = -1
                if chain_h >= 0:
                    self.sync_from_chain(blockchain)
            if self._service is None:
                with self._lock:
                    self.observe_errors += 1
                return None

            candidate = block_ref_from_mapping(block_data)
            decision = self._service.evaluate_candidate(candidate)
            with self._lock:
                self.observe_total += 1
                self._last_decision = decision
                if decision.accepted:
                    self.accept_total += 1
                else:
                    self.reject_total += 1
                    code = str(decision.reason_code or "unknown")
                    self.reject_by_code[code] = int(
                        self.reject_by_code.get(code, 0)
                    ) + 1
            _LOG.debug(
                "tip_safety observe outcome=%s code=%s height=%s enforce=%s",
                decision.outcome.value,
                decision.reason_code,
                candidate.height,
                self._enforce,
            )
            return decision
        except Exception as exc:
            with self._lock:
                self.observe_errors += 1
                self._last_decision = None
            _LOG.warning("tip_safety observe failed: %s", exc)
            return None

    def allows_import(self, decision: Optional[ApplyDecision]) -> bool:
        """Return whether import may proceed under current mode.

        Shadow-only: always True.
        Enforce: True only when ``decision`` is an accepted apply.
        Observer errors (``decision is None``) refuse under enforce.
        """
        if not self._enforce:
            return True
        if decision is None:
            return False
        return bool(decision.accepted)

    def record_enforce_refuse(self, decision: Optional[ApplyDecision]) -> str:
        """Count an enforce refusal and clear the pending decision.

        Args:
            decision: Last observe result (may be ``None`` on observer error).

        Returns:
            Stable reason code for logs.
        """
        code = "tip_safety_observe_error"
        if decision is not None:
            code = str(decision.reason_code or decision.outcome.value)
        with self._lock:
            self.enforce_refuse_total += 1
            self._last_decision = None
        _LOG.warning("tip_safety enforce refused import code=%s", code)
        return code

    def note_import_result(self, imported_ok: bool, blockchain: Any) -> None:
        """Compare last decision with legacy import result; resync tip on success.

        Under enforce, refused imports never reach this method. Divergence
        counters remain meaningful for shadow-only mode.

        Args:
            imported_ok: Whether legacy ``import_block`` succeeded.
            blockchain: Chain facade for tip resync after success.
        """
        if not self._enabled:
            return
        try:
            with self._lock:
                decision = self._last_decision
                self._last_decision = None
                if decision is not None and not self._enforce:
                    if (not decision.accepted) and imported_ok:
                        self.diverge_policy_reject_import_ok += 1
                        _LOG.info(
                            "shadow diverge: policy=%s but import ok",
                            decision.reason_code,
                        )
                    elif decision.accepted and (not imported_ok):
                        self.diverge_policy_accept_import_fail += 1
                        _LOG.info(
                            "shadow diverge: policy accept but import failed"
                        )
            if imported_ok:
                self.sync_from_chain(blockchain)
        except Exception as exc:
            with self._lock:
                self.observe_errors += 1
            _LOG.warning("tip_safety note_import_result failed: %s", exc)

    def merge_into_status(self, target: MutableMapping[str, Any]) -> None:
        """Merge counters into a security-status mapping."""
        target.update(self.status())
