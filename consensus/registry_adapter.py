"""ValidatorRegistryPort adapter over live registry / engine (ADR 0007)."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

from consensus.bft.types import (
    ConsensusSecurityEvidence,
    ValidatorInfo,
    ValidatorSetSnapshot,
)

logger = logging.getLogger("abs.consensus")


class AdapterValidatorRegistry:
    """Thin façade: ConsensusAdapter engines → ValidatorRegistryPort."""

    __slots__ = ("_adapter",)

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def list_active(self) -> Sequence[ValidatorInfo]:
        return tuple(v for v in self._iter_infos() if v.active and not v.slashed)

    def get(self, validator_id: str) -> Optional[ValidatorInfo]:
        want = str(validator_id or "").strip()
        for v in self._iter_infos():
            if v.validator_id == want:
                return v
        return None

    def total_active_stake(self) -> float:
        return float(sum(float(v.stake) for v in self.list_active()))

    def is_active(self, validator_id: str) -> bool:
        v = self.get(validator_id)
        return bool(v and v.active and not v.slashed)

    def mark_slashed(
        self,
        validator_id: str,
        reason: str,
        evidence: Optional[ConsensusSecurityEvidence] = None,
    ) -> None:
        vid = str(validator_id or "").strip()
        if not vid:
            return
        try:
            self._adapter.slash_validator(vid)
        except Exception as exc:
            logger.warning("slash_validator via adapter failed: %s", exc)
            # Best-effort; Round SM already emitted Evidence.
            reg = getattr(self._adapter, "validator_registry", None)
            if reg is not None and hasattr(reg, "slash_validator"):
                try:
                    reg.slash_validator(vid)
                except Exception as exc2:
                    logger.warning("slash_validator via registry failed: %s", exc2)

    def snapshot(self) -> ValidatorSetSnapshot:
        return ValidatorSetSnapshot(validators=tuple(self._iter_infos()))

    def _iter_infos(self) -> List[ValidatorInfo]:
        out: List[ValidatorInfo] = []
        seen = set()
        reg = getattr(self._adapter, "validator_registry", None)
        if reg is not None and hasattr(reg, "get_all_validators"):
            try:
                for raw in reg.get_all_validators() or []:
                    info = self._from_registry_obj(raw)
                    if info and info.validator_id not in seen:
                        seen.add(info.validator_id)
                        out.append(info)
            except Exception as exc:
                logger.warning("get_all_validators failed; engine fallback: %s", exc)
        engine = getattr(self._adapter, "engine", None)
        validators = getattr(engine, "validators", None) or {}
        if isinstance(validators, dict):
            for addr, v in validators.items():
                vid = str(getattr(v, "address", addr) or addr)
                if vid in seen:
                    continue
                seen.add(vid)
                out.append(
                    ValidatorInfo(
                        validator_id=vid,
                        stake=float(getattr(v, "stake", 0) or 0),
                        active=bool(getattr(v, "is_active", True)),
                        slashed=False,
                    )
                )
        return out

    @staticmethod
    def _from_registry_obj(raw: Any) -> Optional[ValidatorInfo]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            vid = str(raw.get("address") or raw.get("validator_id") or "")
            if not vid:
                return None
            return ValidatorInfo(
                validator_id=vid,
                stake=float(raw.get("stake", 0) or 0),
                pubkey=str(raw.get("public_key") or raw.get("pubkey") or ""),
                active=bool(raw.get("is_active", raw.get("active", True))),
                slashed=bool(raw.get("slashed", False)),
            )
        vid = str(getattr(raw, "address", "") or "")
        if not vid:
            return None
        return ValidatorInfo(
            validator_id=vid,
            stake=float(getattr(raw, "stake", 0) or 0),
            pubkey=str(getattr(raw, "public_key", "") or ""),
            active=bool(getattr(raw, "is_active", True)),
            slashed=bool(getattr(raw, "slashed", False)),
        )


class AdapterConsensusEvidence:
    """Evidence sink → EventBus ``security.consensus_refuse``."""

    __slots__ = ("_adapter", "_attempts", "last")

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._attempts: dict = {}
        self.last: Optional[ConsensusSecurityEvidence] = None

    def emit(self, evidence: ConsensusSecurityEvidence) -> None:
        self.last = evidence
        try:
            self._adapter._last_consensus_security_evidence = evidence.to_bus_payload()
        except Exception as exc:
            logger.warning("consensus evidence adapter field write failed: %s", exc)
        bus = getattr(self._adapter, "bus", None)
        if bus is not None and hasattr(bus, "emit"):
            try:
                bus.emit("security.consensus_refuse", evidence.to_bus_payload())
            except Exception as exc:
                logger.warning("security.consensus_refuse emit failed: %s", exc)

    def note_malicious_attempt(self, validator_id: str, reason: str) -> int:
        key = f"{validator_id}:{reason}"
        n = int(self._attempts.get(key, 0) or 0) + 1
        self._attempts[key] = n
        return n


class AdapterConsensusLockdown:
    """Lockdown sink → consistency flag / optional ConsistencyService."""

    __slots__ = ("_adapter",)

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def request_lockdown(self, reason: str) -> None:
        r = str(reason or "consensus_double_sign")
        try:
            self._adapter._consensus_lockdown_reason = r
        except Exception as exc:
            logger.warning("consensus lockdown reason write failed: %s", exc)
        bus = getattr(self._adapter, "bus", None)
        if bus is not None and hasattr(bus, "emit"):
            try:
                bus.emit("security.consensus_lockdown", {"reason": r})
            except Exception as exc:
                logger.warning("security.consensus_lockdown emit failed: %s", exc)
        hook = getattr(self._adapter, "_lockdown_hook", None)
        if callable(hook):
            try:
                hook(r)
            except Exception as exc:
                logger.warning("consensus lockdown hook failed: %s", exc)


class AdapterConsensusSideEffect:
    """ConsensusSideEffectPort — EventBus only; never touches P2P sockets."""

    __slots__ = ("_adapter",)

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def on_attestation(self, vote: Any) -> None:
        bus = getattr(self._adapter, "bus", None)
        if bus is None or not hasattr(bus, "emit"):
            return
        try:
            bus.emit(
                "consensus.attestation",
                {
                    "validator": getattr(vote, "validator_id", ""),
                    "slot": int(getattr(vote, "slot", 0) or 0),
                    "block_hash": getattr(vote, "block_hash", ""),
                    "vote_type": str(
                        getattr(getattr(vote, "vote_type", None), "value", "") or ""
                    ),
                },
            )
        except Exception as exc:
            logger.warning("consensus.attestation emit failed: %s", exc)

    def on_finalized(self, block_hash: str, height: int) -> None:
        bus = getattr(self._adapter, "bus", None)
        if bus is None or not hasattr(bus, "emit"):
            return
        try:
            bus.emit(
                "consensus.finalized",
                {"block": int(height), "block_hash": str(block_hash or "")},
            )
        except Exception as exc:
            logger.warning("consensus.finalized emit failed: %s", exc)
