#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consensus Adapter — live-node façade over ConsensusPort / ValidatorRegistryPort (ADR 0007).

Domain round state lives in ``_round_state`` (RoundStateMachine). Network I/O is
forbidden here: EventBus side-effects go only through ConsensusSideEffectPort /
Evidence / Lockdown ports. Legacy method names remain as thin shims for API/P2P.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from runtime.amount import money_abs

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from consensus_engine import ConsensusEngine
from finality_engine import FinalityEngine
from kernel.event_bus import EventBus
from runtime.config import Config
from storage.database import Database

from consensus.bft import (
    BlockRef,
    ConsensusMaliciousError,
    FinalityView,
    Proposal,
    QuorumCertificate,
    RoundId,
    RoundOutcome,
    RoundPhase,
    RoundStateMachine,
    Vote,
    VoteType,
    build_evidence,
)
from consensus.ports import ConsensusPort, ValidatorRegistryPort
from consensus.registry_adapter import (
    AdapterConsensusEvidence,
    AdapterConsensusLockdown,
    AdapterConsensusSideEffect,
    AdapterValidatorRegistry,
)

try:
    from consensus.engine_slashing import ConsensusEngineSlashing
    from consensus.validator_registry import ValidatorRegistry
    from consensus.pbs import PBSMarket, Builder, Proposer

    _SLASHING_AVAILABLE = True
except ImportError:
    _SLASHING_AVAILABLE = False

try:
    from consensus.engine_casper import ConsensusEngineCasper

    _CASPER_AVAILABLE = True
except ImportError:
    _CASPER_AVAILABLE = False

try:
    from consensus.engine_beacon import ConsensusEngineBeacon

    _BEACON_AVAILABLE = True
except ImportError:
    _BEACON_AVAILABLE = False

logger = logging.getLogger("abs.consensus")


class ConsensusAdapter:
    """Production façade implementing ``ConsensusPort`` over isolated round state.

    Engines (LMD-GHOST, FinalityEngine, optional parallel Casper/Beacon) remain
    for fork-choice / proposer rotation. Quorum round math and fail-closed
    Evidence live exclusively in ``_round_state``.
    """

    def __init__(self, config: Config, db: Database, bus: Optional[EventBus] = None):
        self.config = config
        self.db = db
        self.bus = bus
        self._consensus_mode = config.resolved_consensus_mode()
        self._unified_consensus = self._consensus_mode == "unified"
        self._deployment_mode = str(
            getattr(config, "deployment_mode", "dev") or "dev"
        ).lower()

        self.engine = ConsensusEngine()
        self.finality = FinalityEngine()

        if _SLASHING_AVAILABLE:
            epoch_size = getattr(config, "epoch_size", 32)
            self.slashing_engine = ConsensusEngineSlashing(epoch_size=epoch_size)
            self.validator_registry = ValidatorRegistry()
            if bool(getattr(config, "feature_mev", False)):
                self.pbs_market = PBSMarket()
                self.pbs_market.add_builder(Builder("default-builder"))
                self.pbs_market.add_proposer(Proposer("default-proposer"))
                print(
                    "[Consensus] LMD-GHOST + Slashing + ValidatorRegistry + PBS: "
                    "enabled (fee-bid simulation; mev_protection=false)"
                )
            else:
                self.pbs_market = None
                print(
                    "[Consensus] LMD-GHOST + Slashing + ValidatorRegistry: enabled (PBS off)"
                )
        else:
            self.slashing_engine = None
            self.validator_registry = None
            self.pbs_market = None
            print("[Consensus] Basic PoS mode (engine_slashing not available)")

        # staging/prod → unified: never construct parallel engines
        if _CASPER_AVAILABLE and not self._unified_consensus:
            epoch_sz = getattr(config, "epoch_size", 32)
            self.casper_engine = ConsensusEngineCasper(epoch_size=epoch_sz)
            print("[Consensus] CasperFFG two-step finality: enabled")
        else:
            self.casper_engine = None
            if _CASPER_AVAILABLE and self._unified_consensus:
                print("[Consensus] Casper parallel engine: disabled (unified mode)")

        if _BEACON_AVAILABLE and not self._unified_consensus:
            epoch_sz = getattr(config, "epoch_size", 32)
            self.beacon_engine = ConsensusEngineBeacon(epoch_size=epoch_sz)
            print("[Consensus] BeaconChain engine: enabled (parallel fork choice)")
        else:
            self.beacon_engine = None
            if _BEACON_AVAILABLE and self._unified_consensus:
                print("[Consensus] Beacon parallel engine: disabled (unified mode)")

        if self._unified_consensus:
            print(
                f"[Consensus] Unified path: LMD-GHOST + FinalityEngine "
                f"(deployment_mode={self._deployment_mode})"
            )

        self._last_block_time: float = 0.0
        self._casper_ingest_fail = 0
        self._beacon_ingest_fail = 0
        self._consensus_lockdown_reason: str = ""
        self._last_consensus_security_evidence = None
        self._lockdown_hook = None

        # Port surfaces (constructed before validator load so registry port works)
        self._registry_port: ValidatorRegistryPort = AdapterValidatorRegistry(self)
        self._evidence_port = AdapterConsensusEvidence(self)
        self._lockdown_port = AdapterConsensusLockdown(self)
        self._side_effect_port = AdapterConsensusSideEffect(self)
        # Compat aliases used by earlier Wave A–B wiring / tests
        self._port_registry = self._registry_port
        self._port_evidence = self._evidence_port
        self._port_lockdown = self._lockdown_port

        self._load_validators_from_db()
        self._sync_finality_validator_count()
        self._init_round_state()

        if self.bus:
            self.bus.on("block.new", self._on_new_block)

    # ── Round state isolation (ADR 0007) ───────────────────────────────────

    def _init_round_state(self) -> None:
        epoch_size = int(getattr(self.config, "epoch_size", 32) or 32)
        self._round_state = RoundStateMachine(
            self._registry_port,
            self._evidence_port,
            self._lockdown_port,
            side=self._side_effect_port,
            epoch_size=epoch_size,
        )

    @property
    def round_sm(self) -> RoundStateMachine:
        """Compat alias for ``_round_state`` (Wave A–B tests / ops)."""
        return self._round_state

    @property
    def round_state(self) -> RoundStateMachine:
        return self._round_state

    # ── Bootstrap ──────────────────────────────────────────────────────────

    def _load_validators_from_db(self) -> None:
        validators = self.db.get_validators(active_only=True)
        for v in validators:
            self._register_validator_all(v["address"], float(v["stake"]))
        if validators:
            print(f"[Consensus] Loaded {len(validators)} validators from DB")
        if self.slashing_engine:
            self.slashing_engine.slashing.register_slash_callback(
                self._on_validator_slashed
            )

    def _on_validator_slashed(
        self, address: str, reason: str, slot: int, penalty: int
    ) -> None:
        persist_err: Optional[BaseException] = None
        try:
            self.db.slash_validator(address)
        except Exception as e:
            persist_err = e
            print(f"[Consensus] FAIL: slash persist for {address[:16]}...: {e}")
        if self.validator_registry:
            try:
                self.validator_registry.slash_validator(address)
            except Exception as e:
                print(f"[Consensus] FAIL: slash registry for {address[:16]}...: {e}")
                if persist_err is None:
                    persist_err = e
        if persist_err is not None:
            raise RuntimeError(
                f"slash persist failed for {address}: {persist_err}"
            ) from persist_err

    def _register_validator_all(self, address: str, stake: float) -> None:
        stake_abs = money_abs(stake, field="stake")
        self.engine.add_validator(address, stake_abs)
        if self.slashing_engine:
            self.slashing_engine.add_validator(address, int(stake_abs))
        if self.validator_registry:
            self.validator_registry.register_validator(address, int(stake_abs))

    def _sync_finality_validator_count(self) -> None:
        count = 0
        try:
            count = len(self._registry_port.list_active())
        except Exception as exc:
            logger.warning("list_active for finality validator count failed: %s", exc)
            count = 0
        if count <= 0 and self.db and hasattr(self.db, "get_validators"):
            count = len(self.db.get_validators(active_only=True) or [])
        if count <= 0:
            count = len(self.engine.validators)
        self.finality.set_active_validator_count(max(1, count))

    def get_finalized_floor_height(self) -> int:
        floor = int(self._round_state.finality_status().finalized_height or 0)
        for epoch in self.finality.finalized_checkpoints:
            cp = self.finality.checkpoints.get(epoch)
            if cp and int(cp.block_number) > floor:
                floor = int(cp.block_number)
        return floor

    # ── ValidatorRegistryPort-backed management ────────────────────────────

    def add_validator(self, address: str, stake: float) -> bool:
        stake_abs = money_abs(stake, field="stake")
        ok = self.engine.add_validator(address, stake_abs)
        if ok:
            self.db.save_validator(address, stake_abs)
            if self.slashing_engine:
                self.slashing_engine.add_validator(address, int(stake_abs))
            if self.validator_registry:
                self.validator_registry.register_validator(address, int(stake_abs))
            self._sync_finality_validator_count()
            print(f"[Consensus] New validator: {address[:12]}... stake={stake_abs}")
        return ok

    def slash_validator(self, address: str) -> None:
        self._on_validator_slashed(address, reason="manual", slot=0, penalty=0)
        print(f"[Consensus] Validator slashed: {address[:12]}...")

    def get_validators(self) -> List[Dict]:
        infos = list(self._registry_port.list_active())
        # Include slashed for ops visibility when registry object exists
        if self.validator_registry:
            return [v.to_dict() for v in self.validator_registry.get_all_validators()]
        return [
            {
                "address": i.validator_id,
                "stake": i.stake,
                "is_active": i.active and not i.slashed,
                "attestations": 0,
                "blocks_proposed": 0,
            }
            for i in infos
        ] or [
            {
                "address": v.address,
                "stake": v.stake,
                "is_active": v.is_active,
                "attestations": v.attestations,
                "blocks_proposed": v.blocks_proposed,
            }
            for v in self.engine.validators.values()
        ]

    def get_total_stake(self) -> float:
        try:
            stake = money_abs(self._registry_port.total_active_stake(), field="stake")
            if stake > 0:
                return stake
        except Exception as exc:
            logger.warning("total_active_stake failed; engine fallback: %s", exc)
        return self.engine.get_total_stake()

    def select_proposer(self) -> Optional[str]:
        if not self.engine.validators:
            return self.config.miner_address or "genesis"
        validator = self.engine.select_proposer()
        return validator.address if validator else self.config.miner_address or "genesis"

    def should_produce_block(self) -> bool:
        now = time.time()
        return now - self._last_block_time >= self.config.block_time

    def mark_block_produced(self, proposer: str = None) -> None:
        self._last_block_time = time.time()
        self.engine.advance_slot()
        if proposer and self.validator_registry:
            self.validator_registry.record_produced_block(proposer)

    # ── ConsensusPort implementation ───────────────────────────────────────

    def submit_proposal(self, proposal: Proposal) -> RoundOutcome:
        try:
            return self._round_state.submit_proposal(proposal)
        except ConsensusMaliciousError as exc:
            return exc.outcome

    def submit_vote(self, vote: Vote) -> RoundOutcome:
        try:
            return self._round_state.submit_vote(vote)
        except ConsensusMaliciousError as exc:
            return exc.outcome

    def current_round(self) -> RoundId:
        return self._round_state.current_round()

    def round_phase(self, round_id: RoundId) -> RoundPhase:
        return self._round_state.round_phase(round_id)

    def canonical_head(self) -> Optional[BlockRef]:
        head = self._round_state.canonical_head()
        if head is not None:
            return head
        hh = self.get_canonical_head()
        if not hh:
            return None
        return BlockRef(height=0, block_hash=str(hh), parent_hash="")

    def finality_status(self) -> FinalityView:
        view = self._round_state.finality_status()
        allow_live = bool(getattr(self.config, "finality_quorum_live", False))
        if hasattr(self._round_state, "arm_quorum_live"):
            try:
                self._round_state.arm_quorum_live(allow_live)
                view = self._round_state.finality_status()
            except Exception as exc:
                logger.warning("arm_quorum_live failed: %s", exc)
        # Honesty: never claim live mesh quorum unless config arms it AND QC reached.
        live = bool(allow_live and getattr(view, "quorum_live", False))
        detail = str(getattr(view, "detail", "") or "local_path_only")
        if not allow_live:
            detail = "local_path_only"
        return FinalityView(
            finalized_height=max(
                int(view.finalized_height), int(self.get_finalized_floor_height())
            ),
            justified_height=int(view.justified_height),
            quorum_live=live,
            local_attestations_present=bool(
                view.local_attestations_present or self.get_attestations()
            ),
            detail=detail,
        )

    def weak_subjectivity_status(self) -> Dict[str, Any]:
        """Honesty surface: tip AncestryWindow vs Long-Range / weak-subjectivity."""
        from consensus.long_range.runtime import weak_subjectivity_honesty_snapshot

        return weak_subjectivity_honesty_snapshot(self.config)

    def quorum_certificate(
        self, round_id: RoundId, vote_type: VoteType
    ) -> Optional[QuorumCertificate]:
        return self._round_state.quorum_certificate(round_id, vote_type)

    def add_block(self, block_ref: BlockRef, parent_hash: str = "") -> None:
        parent = parent_hash or block_ref.parent_hash
        self._round_state.add_block(block_ref, parent_hash=parent)
        if self.slashing_engine:
            self.slashing_engine.add_block(
                {
                    "hash": block_ref.block_hash,
                    "parent_hash": parent,
                    "number": int(block_ref.height),
                }
            )

    def add_block_to_fork_choice(self, block: Dict) -> None:
        if self.slashing_engine:
            self.slashing_engine.add_block(block)
        try:
            ref = BlockRef(
                height=int(block.get("number", block.get("height", 0)) or 0),
                block_hash=str(block.get("hash") or block.get("block_hash") or ""),
                parent_hash=str(block.get("parent_hash") or ""),
            )
            if ref.block_hash:
                self._round_state.add_block(ref, parent_hash=ref.parent_hash)
        except Exception as exc:
            logger.warning("round_state add_block failed: %s", exc)

    # ── Legacy attestation shim → ConsensusPort.submit_vote ────────────────

    def attest(
        self, validator_addr: str, block_hash: str, slot: int | None = None
    ) -> bool:
        """Legacy API: LMD + slash check, then domain PREVOTE via ConsensusPort."""
        slot_n = int(self.engine.current_slot if slot is None else slot)

        if self.slashing_engine:
            ok = self.slashing_engine.on_attestation(validator_addr, block_hash, slot_n)
            if not ok:
                print(
                    f"[Consensus] Attestation rejected (slashing): {validator_addr[:12]}..."
                )
                self._fail_closed_double_vote(validator_addr, block_hash, slot_n)
                return False

        ok = self.engine.attest(validator_addr, slot_n, block_hash)
        if not ok:
            return False

        if self.validator_registry:
            self.validator_registry.record_vote(validator_addr)

        vote = self._build_prevote(validator_addr, block_hash, slot_n)
        # Side-effect port emits bus event (no direct bus / no P2P)
        self._side_effect_port.on_attestation(vote)
        outcome = self.submit_vote(vote)
        if outcome.status.value == "locked":
            return False
        return True

    def _build_prevote(
        self, validator_addr: str, block_hash: str, slot_n: int
    ) -> Vote:
        height = max(0, int(getattr(self.engine, "current_slot", slot_n) or slot_n))
        phase = self._round_state.round_phase(self._round_state.current_round())
        if (
            self._round_state.current_round().height != height
            or phase is RoundPhase.FINALIZE
            or phase is RoundPhase.LOCKED
        ):
            proposer = self.select_proposer() or ""
            self._round_state.open_round(height, expected_proposer=proposer)
        return Vote(
            validator_id=str(validator_addr or ""),
            vote_type=VoteType.PREVOTE,
            round_id=self._round_state.current_round(),
            block_hash=str(block_hash or ""),
            slot=int(slot_n),
            verified=True,
        )

    def _fail_closed_double_vote(
        self, validator_addr: str, block_hash: str, slot_n: int
    ) -> None:
        rid = self._round_state.current_round()
        if rid.height <= 0:
            self._round_state.open_round(max(1, int(slot_n or 1)))
            rid = self._round_state.current_round()
        vote = Vote(
            validator_id=str(validator_addr or ""),
            vote_type=VoteType.PREVOTE,
            round_id=rid,
            block_hash=str(block_hash or ""),
            slot=int(slot_n),
            verified=True,
        )
        attempts = self._evidence_port.note_malicious_attempt(
            str(validator_addr or ""), "double_vote"
        )
        evidence = build_evidence(
            reason_code="double_vote",
            validator_id=str(validator_addr or ""),
            round_id=rid,
            conflicting_votes=(vote,),
            attempt_count=attempts,
            detail="legacy_slashing_rejected",
        )
        self._evidence_port.emit(evidence)
        self._lockdown_port.request_lockdown("consensus_double_sign")
        self._round_state._phase = RoundPhase.LOCKED  # noqa: SLF001

    # Compat names used by earlier Wave B helpers
    def finality_status_view(self) -> FinalityView:
        return self.finality_status()

    def _domain_submit_prevote(
        self, validator_addr: str, block_hash: str, slot_n: int
    ) -> None:
        self.submit_vote(self._build_prevote(validator_addr, block_hash, slot_n))

    def _domain_prevote_fail_closed(
        self, validator_addr: str, block_hash: str, slot_n: int
    ) -> None:
        self._fail_closed_double_vote(validator_addr, block_hash, slot_n)

    # ── GHOST fork choice ──────────────────────────────────────────────────

    def get_canonical_head(self) -> Optional[str]:
        if self.slashing_engine:
            return self.slashing_engine.get_head()
        head = self._round_state.canonical_head()
        return head.block_hash if head else None

    def get_cumulative_weight(self, block_hash: str) -> int:
        if self.slashing_engine:
            return self.slashing_engine.get_cumulative_weight(block_hash)
        return 0

    def run_pbs_auction(self, pending_txs: List[Dict]) -> Optional[Dict]:
        if self.pbs_market and pending_txs:
            return self.pbs_market.run_auction(pending_txs)
        return None

    # ── Finality ───────────────────────────────────────────────────────────

    def process_block_finality(
        self, block_number: int, block_hash: str, proposer: str
    ) -> Dict:
        result = self.finality.process_block(block_number, block_hash, proposer)
        epoch = result["epoch"]
        justified = epoch in result["justified"]
        finalized = epoch in result["finalized"]
        self.db.save_checkpoint(epoch, block_hash, justified, finalized)

        try:
            self.add_block(
                BlockRef(
                    height=int(block_number),
                    block_hash=str(block_hash or ""),
                    parent_hash="",
                )
            )
        except Exception as exc:
            logger.warning("process_block_finality add_block failed: %s", exc)

        if finalized:
            # Domain side-effect port only (no direct P2P)
            self._side_effect_port.on_finalized(str(block_hash or ""), int(block_number))

        if self.slashing_engine:
            self.slashing_engine.finality.set_total_stake(
                self.slashing_engine.slashing.get_total_active_stake()
            )
        return result

    def is_finalized(self, block_hash_or_height: Union[str, int]) -> bool:
        """ConsensusPort + legacy: accept height (int) or block hash (str)."""
        if isinstance(block_hash_or_height, str):
            hh = block_hash_or_height.strip().lower()
            if hh and self._round_state.is_finalized(hh):
                return True
            if hh and self.slashing_engine and self.slashing_engine.is_finalized(hh):
                return True
            if self._unified_consensus:
                return False
            if hh and self.casper_engine:
                try:
                    return bool(self.casper_engine.is_finalized(hh))
                except Exception as exc:
                    logger.warning("casper is_finalized failed: %s", exc)
                    return False
            if hh and self.beacon_engine:
                try:
                    return bool(self.beacon_engine.is_finalized(hh))
                except Exception as exc:
                    logger.warning("beacon is_finalized failed: %s", exc)
                    return False
            return False

        block_number = int(block_hash_or_height)
        if self._round_state.is_finalized(block_number):
            return True
        epoch = self.finality.get_epoch(block_number)
        if epoch in self.finality.finalized_checkpoints:
            return True
        blk = self.db.get_block(block_number) if self.db else None
        block_hash = blk.get("hash", "") if blk else ""
        if block_hash and self.slashing_engine:
            if self.slashing_engine.is_finalized(block_hash):
                return True
        if self._unified_consensus:
            return False
        if block_hash and self.casper_engine:
            try:
                if self.casper_engine.is_finalized(block_hash):
                    return True
            except Exception as exc:
                print(f"[Consensus] casper is_finalized error: {exc}")
        if block_hash and self.beacon_engine:
            try:
                if self.beacon_engine.is_finalized(block_hash):
                    return True
            except Exception as exc:
                print(f"[Consensus] beacon is_finalized error: {exc}")
        return False

    def get_finality_status(self, block_number: int) -> Dict:
        return self.finality.get_finality_status(block_number)

    def _on_new_block(self, block_data: Dict) -> None:
        if not isinstance(block_data, dict):
            return
        proposer = block_data.get("miner", "")
        self.process_block_finality(
            block_number=block_data.get("height", 0),
            block_hash=block_data.get("hash", ""),
            proposer=proposer,
        )
        blk_for_fork = {
            "hash": block_data.get("hash", ""),
            "parent_hash": block_data.get("parent_hash", ""),
            "number": block_data.get("height", 0),
        }
        self.add_block_to_fork_choice(blk_for_fork)

        if not self._unified_consensus and self.casper_engine:
            try:
                self.casper_engine.add_block(blk_for_fork)
            except Exception as exc:
                self._casper_ingest_fail += 1
                print(f"[Consensus] casper add_block error: {exc}")

        if not self._unified_consensus and self.beacon_engine:
            try:
                self.beacon_engine.add_block(blk_for_fork)
            except Exception as exc:
                self._beacon_ingest_fail += 1
                print(f"[Consensus] beacon add_block error: {exc}")

        if proposer and self.validator_registry:
            self.validator_registry.record_produced_block(proposer)

    def get_casper_status(self) -> Dict:
        if not self.casper_engine:
            return {"enabled": False, "healthy": False}
        try:
            ingest_fail = int(self._casper_ingest_fail)
            return {
                "enabled": True,
                "healthy": ingest_fail == 0,
                "finality": self.casper_engine.get_finality_status(),
                "ingest_fail": ingest_fail,
            }
        except Exception as e:
            return {
                "enabled": True,
                "healthy": False,
                "error": str(e),
                "ingest_fail": int(self._casper_ingest_fail),
            }

    def get_beacon_status(self) -> Dict:
        if not self.beacon_engine:
            return {"enabled": False, "healthy": False}
        try:
            ingest_fail = int(self._beacon_ingest_fail)
            return {
                "enabled": True,
                "healthy": ingest_fail == 0,
                "stats": self.beacon_engine.get_stats(),
                "ingest_fail": ingest_fail,
            }
        except Exception as e:
            return {
                "enabled": True,
                "healthy": False,
                "error": str(e),
                "ingest_fail": int(self._beacon_ingest_fail),
            }

    def get_stats(self) -> Dict:
        engine_stats = self.engine.get_stats()
        finality_stats = self.finality.get_stats()
        lmd_on = self.slashing_engine is not None
        casper_on = self.casper_engine is not None or self.finality is not None
        slashing_on = self.slashing_engine is not None
        pbs_on = self.pbs_market is not None
        registry_on = self.validator_registry is not None
        view = self.finality_status()
        stats = {
            **engine_stats,
            **finality_stats,
            "enabled": True,
            "consensus_mode": self._consensus_mode,
            "deployment_mode": self._deployment_mode,
            "unified_consensus_path": self._unified_consensus,
            "block_time": self.config.block_time,
            "min_stake": self.config.min_stake,
            "lmd_ghost_enabled": lmd_on,
            "casper_ffg": casper_on,
            "casper_ffg_enabled": self.casper_engine is not None,
            "finality_engine_enabled": self.finality is not None,
            "slashing_enabled": slashing_on,
            "slashing_persistence": "local_bookkeeping",
            "slashing_economic_burn": False,
            "slashing_note": (
                "Double-vote detection is local; stake burn / cross-peer evidence "
                "gossip is not production-complete"
            ),
            "pbs_enabled": pbs_on,
            "pbs_mev_protection": False,
            "pbs_ordering_applied": False,
            "pbs_simulation_only": True,
            "pbs_note": "fee-bid PBS simulation; not MEV protection",
            "validator_registry": registry_on,
            "beacon_enabled": self.beacon_engine is not None,
            "casper_ingest_fail": int(self._casper_ingest_fail),
            "beacon_ingest_fail": int(self._beacon_ingest_fail),
            "consensus_ports_enabled": True,
            "bft_round_phase": self._round_state.round_phase(
                self._round_state.current_round()
            ).value,
            "finality_quorum_live": bool(view.quorum_live),
            "finality_detail": str(view.detail or ""),
            "weak_subjectivity": self.weak_subjectivity_status(),
            "local_attestations_present": bool(view.local_attestations_present),
            "consensus_lockdown_reason": str(self._consensus_lockdown_reason or ""),
            "healthy": (
                int(self._casper_ingest_fail) == 0
                and int(self._beacon_ingest_fail) == 0
                and not bool(self._consensus_lockdown_reason)
            ),
            "systems": {
                "lmd_ghost": lmd_on,
                "casper_ffg": casper_on,
                "slashing": slashing_on,
                "pbs": pbs_on,
                "validator_registry": registry_on,
                "beacon": self.beacon_engine is not None,
                "round_sm": True,
                "consensus_port": True,
            },
        }
        if self.slashing_engine:
            try:
                slashing_stats = self.slashing_engine.get_stats()
                stats["slashed_validators"] = slashing_stats.get("slashed_validators", 0)
                stats["slashed_stake"] = slashing_stats.get("slashed_stake", 0)
                stats["canonical_head"] = slashing_stats.get("head_hash")
                stats["attestation_count"] = slashing_stats.get("active_votes", 0)
                stats["active_votes"] = slashing_stats.get("active_votes", 0)
                stats["head_height"] = slashing_stats.get("head_height")
            except Exception as e:
                stats["head_stats_error"] = str(e)
        if self.validator_registry:
            try:
                stats.update(self.validator_registry.get_stats())
            except Exception as e:
                stats["registry_stats_error"] = str(e)
        return stats

    def get_attestations(self) -> List[Dict]:
        if not self.slashing_engine:
            return []
        out = []
        lmd = getattr(self.slashing_engine, "lmd", None)
        if not lmd:
            return []
        weights = lmd.get_weights()
        for validator, (block_hash, slot) in lmd.latest_vote.items():
            out.append(
                {
                    "validator": validator,
                    "block_hash": block_hash,
                    "slot": int(slot),
                    "stake": int(lmd.validator_stake.get(validator, 0)),
                    "block_weight": int(weights.get(block_hash, 0)),
                }
            )
        out.sort(key=lambda x: (-x["slot"], x["validator"]))
        return out

    def get_attestations_by_block(self) -> List[Dict]:
        grouped: Dict[str, Dict] = {}
        for vote in self.get_attestations():
            block_hash = vote.get("block_hash", "")
            if not block_hash:
                continue
            entry = grouped.get(block_hash)
            if not entry:
                entry = {
                    "block_hash": block_hash,
                    "votes": 0,
                    "total_stake": 0,
                    "validators": [],
                }
                grouped[block_hash] = entry
            entry["votes"] += 1
            entry["total_stake"] += int(vote.get("stake", 0))
            entry["validators"].append(vote.get("validator", ""))
        rows = list(grouped.values())
        rows.sort(key=lambda x: (-x["votes"], -x["total_stake"]))
        return rows

    def get_attestations_for_block(self, block_hash: str) -> List[Dict]:
        """API-facing list of dicts (JSON-serializable). Domain Votes stay internal."""
        target = (block_hash or "").strip().lower()
        if not target:
            return []
        # Prefer LMD wire view for explorer compatibility
        legacy = [
            v
            for v in self.get_attestations()
            if str(v.get("block_hash", "")).lower().startswith(target)
            or target in str(v.get("block_hash", "")).lower()
        ]
        if legacy:
            return legacy
        # Fall back to domain round-state votes
        domain_votes: Sequence[Vote] = self._round_state.get_attestations_for_block(
            target
        )
        return [
            {
                "validator": v.validator_id,
                "block_hash": v.block_hash,
                "slot": int(v.slot),
                "vote_type": v.vote_type.value,
                "stake": 0,
            }
            for v in domain_votes
        ]


# Structural marker for isinstance(..., ConsensusPort) checks in units.
assert hasattr(ConsensusAdapter, "submit_proposal")
assert hasattr(ConsensusAdapter, "submit_vote")
