#!/usr/bin/env python3
"""Verify industrial hardening waves v1.3.65–v1.3.206 (plan checklist).

Runs static needle checks, targeted unit tests, and industrial_gate.

Usage (repo root):
  python scripts/verify_industrial_waves.py
  python scripts/verify_industrial_waves.py --skip-gate
  python scripts/verify_industrial_waves.py --json data/verify_industrial_waves.json

Honesty: green here ≠ public mainnet. Ceremony pin / external audit remain org blockers.
Bridge stays OFF on live mesh.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WAVE_TESTS = [
    "tests/unit/test_v1365_fail_closed.py",
    "tests/unit/test_v1366_load_backpressure.py",
    "tests/unit/test_v1367_1368_journal_bridge.py",
    "tests/unit/test_v1369_block_session.py",
    "tests/unit/test_v1370_recursive_native_frames.py",
    "tests/unit/test_v1371_inline_leaf_frame.py",
    "tests/unit/test_v1372_p2p_admission.py",
    "tests/unit/test_v1373_apply_priority.py",
    "tests/unit/test_v1374_value0_call.py",
    "tests/unit/test_v1375_multidepth_call.py",
    "tests/unit/test_v1376_value_call.py",
    "tests/unit/test_v1377_p2p_ingress.py",
    "tests/unit/test_v1378_p2p_bandwidth.py",
    "tests/unit/test_v1379_callcode_value.py",
    "tests/unit/test_v1380_simple_create.py",
    "tests/unit/test_v1381_create2.py",
    "tests/unit/test_v1382_create_runtime.py",
    "tests/unit/test_v1383_writeback_journal.py",
    "tests/unit/test_v1384_create_writeback.py",
    "tests/unit/test_v1385_p2p_egress.py",
    "tests/unit/test_v1386_p2p_framer.py",
    "tests/unit/test_v1387_p2p_egress_prepare.py",
    "tests/unit/test_v1388_native_fuzz.py",
    "tests/unit/test_v1389_p2p_sybil_eclipse.py",
    "tests/unit/test_v1390_p2p_native_transport.py",
    "tests/unit/test_v1391_p2p_native_tls.py",
    "tests/unit/test_v1392_p2p_native_read_message.py",
    "tests/unit/test_v1393_p2p_native_write_message.py",
    "tests/unit/test_v1394_p2p_native_read_messages.py",
    "tests/unit/test_v1395_p2p_native_write_messages.py",
    "tests/unit/test_v1396_p2p_native_handshake.py",
    "tests/unit/test_v1397_p2p_native_peer_identities.py",
    "tests/unit/test_v1398_p2p_native_auto_pong.py",
    "tests/unit/test_v1399_p2p_native_keepalive.py",
    "tests/unit/test_v13100_p2p_native_housekeeping.py",
    "tests/unit/test_v13101_p2p_native_batch_config.py",
    "tests/unit/test_v13102_p2p_native_io_timeout.py",
    "tests/unit/test_v13103_p2p_native_mid_session.py",
    "tests/unit/test_v13104_p2p_native_status_gate.py",
    "tests/unit/test_v13105_p2p_native_attestation_gate.py",
    "tests/unit/test_v13106_p2p_native_block_sync_gate.py",
    "tests/unit/test_v13107_p2p_native_block_fetch_gate.py",
    "tests/unit/test_v13108_p2p_native_tx_gossip_gate.py",
    "tests/unit/test_v13109_p2p_native_block_payload_gate.py",
    "tests/unit/test_v13110_p2p_native_peer_discovery_gate.py",
    "tests/unit/test_v13111_p2p_native_state_root_gate.py",
    "tests/unit/test_v13112_p2p_native_cross_shard_gate.py",
    "tests/unit/test_v13113_p2p_native_handshake_payload_gate.py",
    "tests/unit/test_v13114_p2p_native_transport_prod.py",
    "tests/unit/test_v13115_p2p_native_handshake_policy.py",
    "tests/unit/test_v13116_p2p_native_message_loop_shell.py",
    "tests/unit/test_v13117_p2p_native_attestation_semantic_gate.py",
    "tests/unit/test_v13118_p2p_native_tx_semantic_gate.py",
    "tests/unit/test_v13119_p2p_native_mempool_semantic_gate.py",
    "tests/unit/test_v13120_p2p_native_block_semantic_gate.py",
    "tests/unit/test_v13121_p2p_native_blocks_batch_semantic_gate.py",
    "tests/unit/test_v13122_p2p_native_block_payload_semantic_gate.py",
    "tests/unit/test_v13123_p2p_native_state_root_response_semantic_gate.py",
    "tests/unit/test_v13124_p2p_native_status_semantic_gate.py",
    "tests/unit/test_v13125_p2p_blocks_response_semantic_gate.py",
    "tests/unit/test_v13126_p2p_block_response_semantic_gate.py",
    "tests/unit/test_v13127_p2p_state_root_response_request_gate.py",
    "tests/unit/test_v13128_p2p_discovery_and_head_binding.py",
    "tests/unit/test_v13129_p2p_state_root_outbound_honesty.py",
    "tests/unit/test_v13130_p2p_state_root_expected_head.py",
    "tests/unit/test_v13131_p2p_mempool_solicit_and_height_cap.py",
    "tests/unit/test_v13132_p2p_bootstrap_resilient.py",
    "tests/unit/test_v13133_p2p_bootstrap_pins.py",
    "tests/unit/test_v13134_p2p_new_block_height_cap.py",
    "tests/unit/test_v13135_p2p_tip_ownership_and_local_root.py",
    "tests/unit/test_v13136_p2p_attestation_slot_ahead.py",
    "tests/unit/test_v13137_p2p_attestation_local_and_block_solicit.py",
    "tests/unit/test_v13138_state_root_solicit_and_ceremony_status.py",
    "tests/unit/test_v13139_p2p_catch_up_require_head.py",
    "tests/unit/test_v13140_sync_heads_no_invent.py",
    "tests/unit/test_v13141_sync_state_wire_only.py",
    "tests/unit/test_silent_except_honesty.py",
    "tests/unit/test_v13143_mempool_cheap_refuse.py",
    "tests/unit/test_v13144_mempool_solicit_armed_shell.py",
    "tests/unit/test_v13145_peer_score_quality.py",
    "tests/unit/test_v13146_catch_up_tip_probe.py",
    "tests/unit/test_v13147_account_row_codec.py",
    "tests/unit/test_v13148_tx_row_codec.py",
    "tests/unit/test_v13149_block_row_codec.py",
    "tests/unit/test_v13150_standard_honesty_needles.py",
    "tests/unit/test_v13151_receipt_row_codec.py",
    "tests/unit/test_v13152_peers_solicit_only.py",
    "tests/unit/test_v13153_new_block_head_height_bind.py",
    "tests/unit/test_v13154_catch_up_peer_head_probe.py",
    "tests/unit/test_v13155_status_head_height_bind.py",
    "tests/unit/test_v13156_new_block_announce_body_bind.py",
    "tests/unit/test_v13157_catch_up_peer_head_parent_bind.py",
    "tests/unit/test_v13158_jwt_hs256_min_secret.py",
    "tests/unit/test_v13159_height_cap_clear_head.py",
    "tests/unit/test_v13160_new_block_contiguous_parent_bind.py",
    "tests/unit/test_v13161_status_head_requires_height.py",
    "tests/unit/test_v13162_fork_peer_head_probe.py",
    "tests/unit/test_v13163_reconcile_head_hash_bind.py",
    "tests/unit/test_v13164_ghost_head_probe.py",
    "tests/unit/test_v13165_reconcile_contiguous_parent_bind.py",
    "tests/unit/test_v13166_handshake_head_requires_height.py",
    "tests/unit/test_v13167_attestation_target_head_bind.py",
    "tests/unit/test_v13168_fork_peer_head_parent_bind.py",
    "tests/unit/test_v13169_ghost_head_parent_bind.py",
    "tests/unit/test_v13170_new_block_same_height_parent_bind.py",
    "tests/unit/test_v13171_reconcile_same_height_parent_bind.py",
    "tests/unit/test_v13172_catch_up_tip_head_bind.py",
    "tests/unit/test_v13173_reconcile_tip_head_bind.py",
    "tests/unit/test_v13174_new_block_tip_head_bind.py",
    "tests/unit/test_v13175_catch_up_contiguous_parent_bind.py",
    "tests/unit/test_v13176_catch_up_height_continuity_bind.py",
    "tests/unit/test_v13177_mempool_min_fee_refuse.py",
    "tests/unit/test_v13178_mempool_serve_tip_align.py",
    "tests/unit/test_v13179_mempool_max_gas_refuse.py",
    "tests/unit/test_v13180_get_blocks_future_refuse.py",
    "tests/unit/test_v13181_get_block_future_refuse.py",
    "tests/unit/test_v13182_get_blocks_past_tip_clamp.py",
    "tests/unit/test_v13183_mempool_max_calldata_refuse.py",
    "tests/unit/test_v13184_mempool_negative_value_refuse.py",
    "tests/unit/test_v13185_mempool_negative_nonce_refuse.py",
    "tests/unit/test_v13186_mempool_negative_fee_refuse.py",
    "tests/unit/test_v13187_mempool_negative_gas_refuse.py",
    "tests/unit/test_v13188_mempool_empty_from_refuse.py",
    "tests/unit/test_v13189_mempool_empty_sig_refuse.py",
    "tests/unit/test_v13190_mempool_empty_pubkey_refuse.py",
    "tests/unit/test_v13191_mempool_max_sig_refuse.py",
    "tests/unit/test_v13192_mempool_max_pubkey_refuse.py",
    "tests/unit/test_v13193_mempool_nonfinite_value_refuse.py",
    "tests/unit/test_v13194_mempool_nonfinite_fee_refuse.py",
    "tests/unit/test_v13195_mempool_empty_to_refuse.py",
    "tests/unit/test_v13196_mempool_empty_hash_refuse.py",
    "tests/unit/test_v13197_mempool_max_hash_refuse.py",
    "tests/unit/test_v13198_mempool_max_from_refuse.py",
    "tests/unit/test_v13199_mempool_max_to_refuse.py",
    "tests/unit/test_v13200_mempool_max_nonce_refuse.py",
    "tests/unit/test_v13201_mempool_max_fee_refuse.py",
    "tests/unit/test_v13202_mempool_max_value_refuse.py",
    "tests/unit/test_v13203_mempool_unparseable_gas_refuse.py",
    "tests/unit/test_v13204_mempool_unparseable_value_refuse.py",
    "tests/unit/test_v13205_mempool_unparseable_nonce_refuse.py",
    "tests/unit/test_v1364_writeback_preload.py",
    "tests/unit/test_v1363_writeback_bundle.py",
    "tests/unit/test_v1362_writeback_commit.py",
    "tests/unit/test_v1361_apply_writeback.py",
]

# (wave, path, must_contain_all)
NEEDLES: list[tuple[str, str, list[str]]] = [
    (
        "1.3.65",
        "crypto/validator_keys.py",
        ["derive_address", "verify_attestation"],
    ),
    (
        "1.3.65",
        "network/p2p_node.py",
        ["validator_register_disabled", "attestation_verifier_unavailable"],
    ),
    (
        "1.3.65",
        "core/blockchain.py",
        ["_native_apply_fail_closed"],
    ),
    (
        "1.3.65",
        "runtime/amount.py",
        ["ABS_REQUIRE_NATIVE_CRYPTO"],
    ),
    (
        "1.3.65",
        "storage/rocks_store.py",
        ["AccountCorruptError"],
    ),
    (
        "1.3.65",
        "api/http.py",
        ["_read_limited_body", "batch too large"],
    ),
    (
        "1.3.66",
        "core/chain_apply_queue.py",
        ["deadline_monotonic", "expired_total"],
    ),
    (
        "1.3.66",
        "network/p2p_node.py",
        [
            "drop mempool txs only after successful import",
            "_schedule_sync",
            "_schedule_connect",
            "_send_q",
        ],
    ),
    (
        "1.3.66",
        "storage/rocks_store.py",
        ['key_meta("chain_tip")', "prefix_last"],
    ),
    (
        "1.3.66",
        "native/abs_native/src/storage/mod.rs",
        ["fn prefix_last"],
    ),
    (
        "1.3.66",
        "observability/metrics.py",
        ["abs_chain_apply_expired_total"],
    ),
    (
        "1.3.67",
        "execution/evm_adapter.py",
        ["begin_writeback_journal", "commit_writeback_journal"],
    ),
    (
        "1.3.67",
        "native/abs_native/src/evm_pure_runner.rs",
        ["Rust-owned storage arena", "fn storage_load(arena:"],
    ),
    (
        "1.3.68",
        "runtime/amount.py",
        ["def try_debit_satoshi"],
    ),
    (
        "1.3.68",
        "storage/rocks_store.py",
        ["try_debit_satoshi"],
    ),
    (
        "1.3.68",
        "bridge/rust_bridge/src/main.rs",
        ["receipt_has_semantic_lock_log", "BRIDGE_L1_LOCK_TOPIC0"],
    ),
    (
        "1.3.69",
        "core/components/state_service.py",
        ["block-scoped sat session", "_writeback_accounts_sat(session)"],
    ),
    (
        "1.3.70",
        "native/abs_native/src/evm_pure_runner.rs",
        ["v1.3.70", "re-sync arena after DELEGATECALL"],
    ),
    (
        "1.3.70",
        "execution/evm_adapter.py",
        ["_abs_live_storage"],
    ),
    (
        "1.3.71",
        "native/abs_native/src/evm_pure_runner.rs",
        ["try_inline_leaf_delegate_call", "v1.3.71"],
    ),
    (
        "1.3.72",
        "runtime/config.py",
        ["p2p_max_sync_inflight", "p2p_exempt_messages_per_sec"],
    ),
    (
        "1.3.72",
        "network/p2p_node.py",
        ["sync admission reject", "_bump_outbound_drop", "_exempt_rate_ok"],
    ),
    (
        "1.3.72",
        "observability/metrics.py",
        ["abs_p2p_outbound_drops_total", "abs_p2p_sync_admission_rejects_total"],
    ),
    (
        "1.3.73",
        "core/chain_apply_queue.py",
        ["PriorityQueue", "_APPLY_PRIORITY", "v1.3.73"],
    ),
    (
        "1.3.73",
        "observability/metrics.py",
        ["abs_chain_apply_error_total", "abs_chain_apply_priority_lanes"],
    ),
    (
        "1.3.74",
        "native/abs_native/src/evm_pure_runner.rs",
        ["try_inline_leaf_value0_call", "v1.3.74"],
    ),
    (
        "1.3.75",
        "native/abs_native/src/evm_pure_runner.rs",
        [
            "bytecode_is_inline_call_frame_eligible",
            "MAX_INLINE_CALL_DEPTH",
            "_abs_inline_depth",
        ],
    ),
    (
        "1.3.76",
        "RELEASE_NOTES_v1.3.76.md",
        ["1.3.76-industrial", "fail-closed"],
    ),
    (
        "1.3.76",
        "native/abs_native/src/evm_pure_runner.rs",
        ["try_inline_value_transfer", "InlineValueTransfer", "v1.3.76"],
    ),
    (
        "1.3.77",
        "RELEASE_NOTES_v1.3.77.md",
        ["1.3.77-industrial", "p2p_ingress_admit"],
    ),
    (
        "1.3.77",
        "native/abs_native/src/p2p_ingress.rs",
        ["p2p_ingress_admit", "P2PConnectionGovernor"],
    ),
    (
        "1.3.77",
        "network/p2p_node.py",
        ["p2p_ingress_admit", "_use_native_ingress", "P2PConnectionGovernor"],
    ),
    (
        "1.3.78",
        "RELEASE_NOTES_v1.3.78.md",
        ["1.3.78-industrial", "bandwidth"],
    ),
    (
        "1.3.78",
        "native/abs_native/src/p2p_rate_limit.rs",
        ["bandwidth_exceeded", "ingress_cost_units", "byte_limit"],
    ),
    (
        "1.3.78",
        "observability/metrics.py",
        ["abs_p2p_bandwidth_rejects_total"],
    ),
    (
        "1.3.79",
        "RELEASE_NOTES_v1.3.79.md",
        ["1.3.79-industrial", "CALLCODE"],
    ),
    (
        "1.3.79",
        "native/abs_native/src/evm_pure_runner.rs",
        ["native_inline_callcode_value", "v1.3.79"],
    ),
    (
        "1.3.80",
        "RELEASE_NOTES_v1.3.80.md",
        ["1.3.80-industrial", "CREATE"],
    ),
    (
        "1.3.80",
        "native/abs_native/src/evm_pure_runner.rs",
        ["try_inline_simple_create", "native_inline_simple_create", "v1.3.80"],
    ),
    (
        "1.3.81",
        "RELEASE_NOTES_v1.3.81.md",
        ["1.3.81-industrial", "CREATE2"],
    ),
    (
        "1.3.81",
        "native/abs_native/src/evm_pure_runner.rs",
        ["native_inline_create2", "create2_eip1014_enabled", "v1.3.81"],
    ),
    (
        "1.3.82",
        "RELEASE_NOTES_v1.3.82.md",
        ["1.3.82-industrial"],
    ),
    (
        "1.3.82",
        "native/abs_native/src/evm_pure_runner.rs",
        ["run_inline_create_init", "native_inline_create_runtime", "v1.3.82"],
    ),
    (
        "1.3.83",
        "RELEASE_NOTES_v1.3.83.md",
        ["1.3.83-industrial"],
    ),
    (
        "1.3.83",
        "native/abs_native/src/evm_pure_runner.rs",
        [
            "push_pending_writeback_transfer",
            "pending_writeback_ops",
            "native_inline_writeback_value",
            "v1.3.83",
        ],
    ),
    (
        "1.3.83",
        "execution/evm_adapter.py",
        ["_take_bridge_pending_writeback", "native_inline_writeback"],
    ),
    (
        "1.3.84",
        "RELEASE_NOTES_v1.3.84.md",
        ["1.3.84-industrial"],
    ),
    (
        "1.3.84",
        "native/abs_native/src/evm_pure_runner.rs",
        [
            "push_pending_writeback_save_account",
            "native_inline_writeback_create",
            "v1.3.84",
        ],
    ),
    (
        "1.3.85",
        "RELEASE_NOTES_v1.3.85.md",
        ["1.3.85-industrial"],
    ),
    (
        "1.3.85",
        "native/abs_native/src/p2p_rate_limit.rs",
        [
            "admit_egress",
            "egress_bandwidth_exceeded",
            "p2p_egress_admit",
            "v1.3.85",
        ],
    ),
    (
        "1.3.85",
        "observability/metrics.py",
        ["abs_p2p_egress_rejects_total"],
    ),
    (
        "1.3.86",
        "RELEASE_NOTES_v1.3.86.md",
        ["1.3.86-industrial"],
    ),
    (
        "1.3.86",
        "native/abs_native/src/p2p_frame.rs",
        ["P2PLineFramer", "p2p_line_too_large", "v1.3.86"],
    ),
    (
        "1.3.86",
        "network/p2p_node.py",
        ["_read_wire_line", "P2PLineFramer"],
    ),
    (
        "1.3.87",
        "RELEASE_NOTES_v1.3.87.md",
        ["1.3.87-industrial"],
    ),
    (
        "1.3.87",
        "native/abs_native/src/p2p_ingress.rs",
        ["p2p_egress_prepare", "v1.3.87"],
    ),
    (
        "1.3.87",
        "network/p2p_node.py",
        ["_prepare_outbound", "p2p_egress_prepare"],
    ),
    (
        "1.3.88",
        "RELEASE_NOTES_v1.3.88.md",
        ["1.3.88-industrial"],
    ),
    (
        "1.3.88",
        "native/abs_native/src/fuzz_api.rs",
        ["fuzz_p2p_frame_feed", "fuzz_p2p_wire_parse", "fuzz_p2p_rate_limit_sequence"],
    ),
    (
        "1.3.88",
        "scripts/fuzz_native.ps1",
        ["fuzz_p2p_", "cargo fuzz"],
    ),
    (
        "1.3.88",
        ".github/workflows/fuzz-native.yml",
        ["cargo fuzz run", "fuzz_p2p_"],
    ),
    (
        "1.3.89",
        "RELEASE_NOTES_v1.3.89.md",
        ["1.3.89-industrial"],
    ),
    (
        "1.3.89",
        "native/abs_native/src/p2p_ingress.rs",
        ["p2p_subnet_key", "reserved_outbound_slots", "v1.3.89"],
    ),
    (
        "1.3.89",
        "network/p2p_node.py",
        ["_maybe_eclipse_prune"],
    ),
    (
        "1.3.89",
        "network/peer_manager.py",
        ["diversity_snapshot"],
    ),
    (
        "1.3.89",
        "observability/metrics.py",
        ["abs_p2p_subnet_rejects_total", "abs_p2p_eclipse_at_risk"],
    ),
    (
        "1.3.90",
        "RELEASE_NOTES_v1.3.90.md",
        ["1.3.90-industrial"],
    ),
    (
        "1.3.90",
        "native/abs_native/src/p2p_transport.rs",
        ["P2PNativeListener", "P2PNativeConn", "v1.3.90"],
    ),
    (
        "1.3.90",
        "network/p2p_node.py",
        ["_native_accept_loop", "_handle_native_incoming"],
    ),
    (
        "1.3.91",
        "RELEASE_NOTES_v1.3.91.md",
        ["1.3.91-industrial"],
    ),
    (
        "1.3.91",
        "native/abs_native/src/p2p_transport.rs",
        ["rustls", "p2p_native_tls_available", "WebPkiClientVerifier"],
    ),
    (
        "1.3.91",
        "network/p2p_node.py",
        ["_native_tls", "native-tls"],
    ),
    (
        "1.3.92",
        "RELEASE_NOTES_v1.3.92.md",
        ["1.3.92-industrial"],
    ),
    (
        "1.3.92",
        "native/abs_native/src/p2p_transport.rs",
        ["read_message", "v1.3.92"],
    ),
    (
        "1.3.92",
        "network/p2p_node.py",
        ["_native_read_message", "read_message"],
    ),
    (
        "1.3.92",
        "observability/metrics.py",
        ["abs_p2p_native_read_message"],
    ),
    (
        "1.3.93",
        "RELEASE_NOTES_v1.3.93.md",
        ["1.3.93-industrial"],
    ),
    (
        "1.3.93",
        "native/abs_native/src/p2p_transport.rs",
        ["write_message", "v1.3.93"],
    ),
    (
        "1.3.93",
        "network/p2p_node.py",
        ["_native_write_message", "_write_message"],
    ),
    (
        "1.3.93",
        "observability/metrics.py",
        ["abs_p2p_native_write_message"],
    ),
    (
        "1.3.94",
        "RELEASE_NOTES_v1.3.94.md",
        ["1.3.94-industrial"],
    ),
    (
        "1.3.94",
        "native/abs_native/src/p2p_transport.rs",
        ["read_messages", "v1.3.94"],
    ),
    (
        "1.3.94",
        "network/p2p_node.py",
        ["_native_read_messages", "_pending_msgs"],
    ),
    (
        "1.3.94",
        "observability/metrics.py",
        ["abs_p2p_native_read_messages"],
    ),
    (
        "1.3.95",
        "RELEASE_NOTES_v1.3.95.md",
        ["1.3.95-industrial"],
    ),
    (
        "1.3.95",
        "native/abs_native/src/p2p_transport.rs",
        ["write_messages", "write_payloads", "v1.3.95"],
    ),
    (
        "1.3.95",
        "network/p2p_node.py",
        ["_native_write_messages", "_write_messages_batch"],
    ),
    (
        "1.3.95",
        "observability/metrics.py",
        ["abs_p2p_native_write_messages"],
    ),
    (
        "1.3.96",
        "RELEASE_NOTES_v1.3.96.md",
        ["1.3.96-industrial"],
    ),
    (
        "1.3.96",
        "native/abs_native/src/p2p_transport.rs",
        ["handshake_roundtrip", "v1.3.96"],
    ),
    (
        "1.3.96",
        "network/p2p_node.py",
        ["_native_handshake", "handshake_roundtrip"],
    ),
    (
        "1.3.96",
        "observability/metrics.py",
        ["abs_p2p_native_handshake"],
    ),
    (
        "1.3.97",
        "RELEASE_NOTES_v1.3.97.md",
        ["1.3.97-industrial"],
    ),
    (
        "1.3.97",
        "native/abs_native/src/p2p_transport.rs",
        ["peer_cert_identities", "extract_cert_identities", "v1.3.97"],
    ),
    (
        "1.3.97",
        "network/p2p_node.py",
        ["_native_peer_identities", "peer_cert_identities"],
    ),
    (
        "1.3.97",
        "observability/metrics.py",
        ["abs_p2p_native_peer_identities"],
    ),
    (
        "1.3.98",
        "RELEASE_NOTES_v1.3.98.md",
        ["1.3.98-industrial", "p2p_native_auto_pong"],
    ),
    (
        "1.3.98",
        "native/abs_native/src/p2p_transport.rs",
        ["maybe_auto_pong", "auto_pong", "v1.3.98"],
    ),
    (
        "1.3.98",
        "network/p2p_node.py",
        ["_native_auto_pong"],
    ),
    (
        "1.3.98",
        "observability/metrics.py",
        ["abs_p2p_native_auto_pong"],
    ),
    (
        "1.3.99",
        "RELEASE_NOTES_v1.3.99.md",
        ["1.3.99-industrial", "keepalive_touches"],
    ),
    (
        "1.3.99",
        "native/abs_native/src/p2p_transport.rs",
        ["keepalive_touches", "auto_keeps", "v1.3.99"],
    ),
    (
        "1.3.99",
        "network/p2p_node.py",
        ["keepalive_touches", "native_keepalive"],
    ),
    (
        "1.3.99",
        "observability/metrics.py",
        ["abs_p2p_native_keepalive"],
    ),
    (
        "1.3.100",
        "RELEASE_NOTES_v1.3.100.md",
        ["1.3.100-industrial", "housekeeping"],
    ),
    (
        "1.3.100",
        "native/abs_native/src/p2p_transport.rs",
        ["housekeeping_payload_ok", "check_housekeeping", "v1.3.100"],
    ),
    (
        "1.3.100",
        "network/p2p_node.py",
        ["native_housekeeping_gate"],
    ),
    (
        "1.3.100",
        "observability/metrics.py",
        ["abs_p2p_native_housekeeping_gate"],
    ),
    (
        "1.3.101",
        "RELEASE_NOTES_v1.3.101.md",
        ["1.3.101-industrial", "clamp"],
    ),
    (
        "1.3.101",
        "native/abs_native/src/p2p_transport.rs",
        ["p2p_native_clamp_batch", "NATIVE_BATCH_MAX", "v1.3.101"],
    ),
    (
        "1.3.101",
        "runtime/config.py",
        ["p2p_native_read_batch", "p2p_native_write_batch", "p2p_native_read_chunk"],
    ),
    (
        "1.3.101",
        "network/p2p_node.py",
        ["_clamp_native_batch", "native_read_batch"],
    ),
    (
        "1.3.101",
        "observability/metrics.py",
        ["abs_p2p_native_read_batch", "abs_p2p_native_write_batch"],
    ),
    (
        "1.3.102",
        "RELEASE_NOTES_v1.3.102.md",
        ["1.3.102-industrial", "io_timeout"],
    ),
    (
        "1.3.102",
        "native/abs_native/src/p2p_transport.rs",
        ["p2p_native_clamp_timeout_ms", "NATIVE_IO_TIMEOUT_DEFAULT_MS", "v1.3.102"],
    ),
    (
        "1.3.102",
        "runtime/config.py",
        ["p2p_native_io_timeout_ms"],
    ),
    (
        "1.3.102",
        "network/p2p_node.py",
        ["_apply_native_io_timeout", "native_io_timeout_ms"],
    ),
    (
        "1.3.102",
        "observability/metrics.py",
        ["abs_p2p_native_io_timeout_ms"],
    ),
    (
        "1.3.103",
        "RELEASE_NOTES_v1.3.103.md",
        ["1.3.103-industrial", "mid_session"],
    ),
    (
        "1.3.103",
        "native/abs_native/src/p2p_transport.rs",
        ["check_mid_session_handshake", "set_session_established", "v1.3.103"],
    ),
    (
        "1.3.103",
        "network/p2p_node.py",
        ["set_session_established", "native_mid_session_gate"],
    ),
    (
        "1.3.103",
        "observability/metrics.py",
        ["abs_p2p_native_mid_session_gate"],
    ),
    (
        "1.3.104",
        "RELEASE_NOTES_v1.3.104.md",
        ["1.3.104-industrial", "status"],
    ),
    (
        "1.3.104",
        "native/abs_native/src/p2p_transport.rs",
        ["check_status_payload", "validate_status_inner", "v1.3.104"],
    ),
    (
        "1.3.104",
        "network/p2p_node.py",
        ["native_status_gate"],
    ),
    (
        "1.3.104",
        "observability/metrics.py",
        ["abs_p2p_native_status_gate"],
    ),
    (
        "1.3.105",
        "RELEASE_NOTES_v1.3.105.md",
        ["1.3.105-industrial", "attestation"],
    ),
    (
        "1.3.105",
        "native/abs_native/src/p2p_transport.rs",
        ["check_attestation_payload", "validate_attestation_shape_inner", "v1.3.105"],
    ),
    (
        "1.3.105",
        "network/p2p_node.py",
        ["native_attestation_gate"],
    ),
    (
        "1.3.105",
        "observability/metrics.py",
        ["abs_p2p_native_attestation_gate"],
    ),
    (
        "1.3.106",
        "RELEASE_NOTES_v1.3.106.md",
        ["1.3.106-industrial", "block"],
    ),
    (
        "1.3.106",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_block_announce_payload",
            "check_get_block_payload",
            "validate_block_announce_inner",
            "validate_get_block_inner",
            "v1.3.106",
        ],
    ),
    (
        "1.3.106",
        "network/p2p_node.py",
        ["native_block_sync_gate"],
    ),
    (
        "1.3.106",
        "observability/metrics.py",
        ["abs_p2p_native_block_sync_gate"],
    ),
    (
        "1.3.107",
        "RELEASE_NOTES_v1.3.107.md",
        ["1.3.107-industrial", "fetch"],
    ),
    (
        "1.3.107",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_get_blocks_payload",
            "check_get_block_by_hash_payload",
            "check_blocks_batch_payload",
            "v1.3.107",
        ],
    ),
    (
        "1.3.107",
        "network/p2p_node.py",
        ["native_block_fetch_gate"],
    ),
    (
        "1.3.107",
        "observability/metrics.py",
        ["abs_p2p_native_block_fetch_gate"],
    ),
    (
        "1.3.108",
        "RELEASE_NOTES_v1.3.108.md",
        ["1.3.108-industrial", "tx"],
    ),
    (
        "1.3.108",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_wire_tx_payload",
            "check_mempool_batch_payload",
            "check_ingress_shape_gates",
            "v1.3.108",
        ],
    ),
    (
        "1.3.108",
        "network/p2p_node.py",
        ["native_tx_gossip_gate"],
    ),
    (
        "1.3.108",
        "observability/metrics.py",
        ["abs_p2p_native_tx_gossip_gate"],
    ),
    (
        "1.3.109",
        "RELEASE_NOTES_v1.3.109.md",
        ["1.3.109-industrial", "block"],
    ),
    (
        "1.3.109",
        "native/abs_native/src/p2p_transport.rs",
        ["check_block_payload", "bad_block_payload", "v1.3.109"],
    ),
    (
        "1.3.109",
        "network/p2p_node.py",
        ["native_block_payload_gate"],
    ),
    (
        "1.3.109",
        "observability/metrics.py",
        ["abs_p2p_native_block_payload_gate"],
    ),
    (
        "1.3.110",
        "RELEASE_NOTES_v1.3.110.md",
        ["1.3.110-industrial", "peer"],
    ),
    (
        "1.3.110",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_peers_list_payload",
            "check_validator_register_payload",
            "v1.3.110",
        ],
    ),
    (
        "1.3.110",
        "network/p2p_node.py",
        ["native_peer_discovery_gate"],
    ),
    (
        "1.3.110",
        "observability/metrics.py",
        ["abs_p2p_native_peer_discovery_gate"],
    ),
    (
        "1.3.111",
        "RELEASE_NOTES_v1.3.111.md",
        ["1.3.111-industrial", "state_root"],
    ),
    (
        "1.3.111",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_state_root_request_payload",
            "check_state_root_response_payload",
            "v1.3.111",
        ],
    ),
    (
        "1.3.111",
        "network/p2p_node.py",
        ["native_state_root_gate"],
    ),
    (
        "1.3.111",
        "observability/metrics.py",
        ["abs_p2p_native_state_root_gate"],
    ),
    (
        "1.3.112",
        "RELEASE_NOTES_v1.3.112.md",
        ["1.3.112-industrial", "cross"],
    ),
    (
        "1.3.112",
        "native/abs_native/src/p2p_transport.rs",
        [
            "check_cross_shard_tx_payload",
            "check_cross_shard_ack_payload",
            "check_shard_migration_payload",
            "v1.3.112",
        ],
    ),
    (
        "1.3.112",
        "network/p2p_node.py",
        ["native_cross_shard_gate"],
    ),
    (
        "1.3.112",
        "observability/metrics.py",
        ["abs_p2p_native_cross_shard_gate"],
    ),
    (
        "1.3.113",
        "RELEASE_NOTES_v1.3.113.md",
        ["1.3.113-industrial", "handshake"],
    ),
    (
        "1.3.113",
        "native/abs_native/src/p2p_transport.rs",
        ["check_handshake_payload", "bad_handshake_payload", "v1.3.113"],
    ),
    (
        "1.3.113",
        "network/p2p_node.py",
        ["native_handshake_payload_gate"],
    ),
    (
        "1.3.113",
        "observability/metrics.py",
        ["abs_p2p_native_handshake_payload_gate"],
    ),
    (
        "1.3.114",
        "RELEASE_NOTES_v1.3.114.md",
        ["1.3.114-industrial", "transport"],
    ),
    (
        "1.3.114",
        "runtime/config.py",
        ["p2p_native_transport", "prod mode requires p2p_native_transport"],
    ),
    (
        "1.3.114",
        "scripts/prod_gate.py",
        ["p2p_native_transport"],
    ),
    (
        "1.3.114",
        "network/p2p_node.py",
        ["must_native_tx", "native_shape_revalidate", "check_ingress_shape_gates"],
    ),
    (
        "1.3.114",
        "observability/metrics.py",
        ["abs_p2p_native_shape_revalidate"],
    ),
    (
        "1.3.115",
        "RELEASE_NOTES_v1.3.115.md",
        ["1.3.115-industrial", "handshake policy"],
    ),
    (
        "1.3.115",
        "native/abs_native/src/p2p_transport.rs",
        ["check_handshake_policy", "chain_id_mismatch", "v1.3.115"],
    ),
    (
        "1.3.115",
        "network/p2p_node.py",
        ["native_policy_applied", "native_handshake_policy_gate"],
    ),
    (
        "1.3.115",
        "api/http.py",
        ["_native_listener", "native TCP+TLS uses ``_native_listener``"],
    ),
    (
        "1.3.115",
        "observability/metrics.py",
        ["abs_p2p_native_handshake_policy_gate"],
    ),
    (
        "1.3.116",
        "RELEASE_NOTES_v1.3.116.md",
        ["1.3.116-industrial", "message-loop"],
    ),
    (
        "1.3.116",
        "native/abs_native/src/p2p_transport.rs",
        ["read_message_loop_events", "LoopShellEvent", "v1.3.116"],
    ),
    (
        "1.3.116",
        "network/p2p_node.py",
        ["recv_loop_events", "native_message_loop_shell"],
    ),
    (
        "1.3.116",
        "observability/metrics.py",
        [
            "abs_p2p_native_message_loop_shell",
            "abs_p2p_native_message_loop_dispatch_total",
            "abs_p2p_native_message_loop_strikes_total",
        ],
    ),
    (
        "1.3.117",
        "RELEASE_NOTES_v1.3.117.md",
        ["1.3.117-industrial", "attestation semantic"],
    ),
    (
        "1.3.117",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_attestation_semantics_inner", "bad_attestation_identity"],
    ),
    (
        "1.3.117",
        "native/abs_native/src/p2p_transport.rs",
        ["check_attestation_semantics", "v1.3.117"],
    ),
    (
        "1.3.117",
        "network/p2p_node.py",
        ["native_attestation_semantic_gate", "attestation_semantic_rejects_total"],
    ),
    (
        "1.3.117",
        "observability/metrics.py",
        [
            "abs_p2p_native_attestation_semantic_gate",
            "abs_p2p_attestation_semantic_rejects_total",
        ],
    ),
    (
        "1.3.118",
        "RELEASE_NOTES_v1.3.118.md",
        ["1.3.118-industrial", "new_tx"],
    ),
    (
        "1.3.118",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_wire_tx_signature_inner", "missing_tx_signature", "bad_tx_signature"],
    ),
    (
        "1.3.118",
        "native/abs_native/src/p2p_transport.rs",
        ["check_wire_tx_semantics", "require_tx_signatures", "v1.3.118"],
    ),
    (
        "1.3.118",
        "network/p2p_node.py",
        ["native_tx_semantic_gate", "tx_semantic_rejects_total"],
    ),
    (
        "1.3.118",
        "observability/metrics.py",
        ["abs_p2p_native_tx_semantic_gate", "abs_p2p_tx_semantic_rejects_total"],
    ),
    (
        "1.3.119",
        "RELEASE_NOTES_v1.3.119.md",
        ["1.3.119-industrial", "mempool"],
    ),
    (
        "1.3.119",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_mempool_batch_signatures_inner"],
    ),
    (
        "1.3.119",
        "native/abs_native/src/p2p_transport.rs",
        ["check_mempool_batch_semantics", "v1.3.119"],
    ),
    (
        "1.3.119",
        "network/p2p_node.py",
        ["native_mempool_semantic_gate"],
    ),
    (
        "1.3.119",
        "observability/metrics.py",
        ["abs_p2p_native_mempool_semantic_gate"],
    ),
    (
        "1.3.120",
        "RELEASE_NOTES_v1.3.120.md",
        ["1.3.120-industrial", "new_block"],
    ),
    (
        "1.3.120",
        "native/abs_native/src/lib.rs",
        ["recomputed_canonical_block_hash"],
    ),
    (
        "1.3.120",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_block_announce_semantics_inner", "bad_block_hash"],
    ),
    (
        "1.3.120",
        "native/abs_native/src/p2p_transport.rs",
        ["check_block_announce_semantics", "v1.3.120"],
    ),
    (
        "1.3.120",
        "network/p2p_node.py",
        ["native_block_semantic_gate", "block_semantic_rejects_total"],
    ),
    (
        "1.3.120",
        "observability/metrics.py",
        ["abs_p2p_native_block_semantic_gate", "abs_p2p_block_semantic_rejects_total"],
    ),
    (
        "1.3.121",
        "RELEASE_NOTES_v1.3.121.md",
        ["1.3.121-industrial", "blocks"],
    ),
    (
        "1.3.121",
        "Makefile",
        ["test-quick", "build_native.sh", "mesh-up"],
    ),
    (
        "1.3.121",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_blocks_batch_semantics_inner"],
    ),
    (
        "1.3.121",
        "native/abs_native/src/p2p_transport.rs",
        ["check_blocks_batch_semantics", "v1.3.121"],
    ),
    (
        "1.3.121",
        "network/p2p_node.py",
        ["native_blocks_batch_semantic_gate"],
    ),
    (
        "1.3.121",
        "observability/metrics.py",
        ["abs_p2p_native_blocks_batch_semantic_gate"],
    ),
    (
        "1.3.122",
        "RELEASE_NOTES_v1.3.122.md",
        ["1.3.122-industrial", "block"],
    ),
    (
        "1.3.122",
        "native/abs_native/src/p2p_transport.rs",
        ["check_block_payload_semantics", "v1.3.122"],
    ),
    (
        "1.3.122",
        "network/p2p_node.py",
        ["native_block_payload_semantic_gate"],
    ),
    (
        "1.3.122",
        "observability/metrics.py",
        ["abs_p2p_native_block_payload_semantic_gate"],
    ),
    (
        "1.3.123",
        "RELEASE_NOTES_v1.3.123.md",
        ["1.3.123-industrial", "state_root"],
    ),
    (
        "1.3.123",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_state_root_response_semantics_inner", "bad_state_root_digest"],
    ),
    (
        "1.3.123",
        "native/abs_native/src/p2p_transport.rs",
        ["check_state_root_response_semantics", "v1.3.123"],
    ),
    (
        "1.3.123",
        "network/p2p_node.py",
        ["native_state_root_response_semantic_gate", "state_root_semantic_rejects_total"],
    ),
    (
        "1.3.123",
        "observability/metrics.py",
        [
            "abs_p2p_native_state_root_response_semantic_gate",
            "abs_p2p_state_root_semantic_rejects_total",
        ],
    ),
    (
        "1.3.124",
        "RELEASE_NOTES_v1.3.124.md",
        ["1.3.124-industrial", "status"],
    ),
    (
        "1.3.124",
        "native/abs_native/src/p2p_wire.rs",
        ["verify_status_head_hash_semantics_inner", "bad_status_head_digest"],
    ),
    (
        "1.3.124",
        "native/abs_native/src/p2p_transport.rs",
        ["check_status_head_hash_semantics", "v1.3.124"],
    ),
    (
        "1.3.124",
        "network/p2p_node.py",
        ["native_status_head_hash_semantic_gate", "status_semantic_rejects_total"],
    ),
    (
        "1.3.124",
        "observability/metrics.py",
        [
            "abs_p2p_native_status_head_hash_semantic_gate",
            "abs_p2p_status_semantic_rejects_total",
        ],
    ),
    (
        "1.3.125",
        "RELEASE_NOTES_v1.3.125.md",
        ["1.3.125-industrial", "blocks"],
    ),
    (
        "1.3.125",
        "native/abs_native/src/p2p_wire.rs",
        [
            "verify_blocks_response_semantics_inner",
            "bad_blocks_response_range",
            "empty_blocks_response",
        ],
    ),
    (
        "1.3.125",
        "network/p2p_node.py",
        [
            "verify_p2p_blocks_response_semantics",
            "request_ctx",
            "stale wheel is not prod-safe",
        ],
    ),
    (
        "1.3.125",
        "api/http.py",
        ["p2p_native_message_loop_shell"],
    ),
    (
        "1.3.125",
        "crypto/native.py",
        ["verify_p2p_blocks_response_semantics", "blocks_response_native_required"],
    ),
    (
        "1.3.125",
        "observability/metrics.py",
        [
            "abs_p2p_native_blocks_response_semantic_gate",
            "abs_p2p_blocks_response_semantic_rejects_total",
        ],
    ),
    (
        "1.3.126",
        "RELEASE_NOTES_v1.3.126.md",
        ["1.3.126-industrial", "block"],
    ),
    (
        "1.3.126",
        "native/abs_native/src/p2p_wire.rs",
        [
            "verify_block_response_semantics_inner",
            "bad_block_response_hash",
            "empty_block_response",
        ],
    ),
    (
        "1.3.126",
        "network/p2p_node.py",
        [
            "verify_p2p_block_response_semantics",
            "expected_hash",
            'kind": "block"',
        ],
    ),
    (
        "1.3.126",
        "crypto/native.py",
        ["verify_p2p_block_response_semantics", "block_response_native_required"],
    ),
    (
        "1.3.126",
        "observability/metrics.py",
        [
            "abs_p2p_native_block_response_semantic_gate",
            "abs_p2p_block_response_semantic_rejects_total",
        ],
    ),
    (
        "1.3.127",
        "RELEASE_NOTES_v1.3.127.md",
        ["1.3.127-industrial", "state_root"],
    ),
    (
        "1.3.127",
        "native/abs_native/src/p2p_wire.rs",
        [
            "verify_state_root_response_request_semantics_inner",
            "bad_state_root_response_height",
        ],
    ),
    (
        "1.3.127",
        "network/p2p_node.py",
        [
            "verify_p2p_state_root_response_request_semantics",
            'kind": "state_root"',
        ],
    ),
    (
        "1.3.127",
        "crypto/native.py",
        [
            "verify_p2p_state_root_response_request_semantics",
            "state_root_response_request_native_required",
        ],
    ),
    (
        "1.3.127",
        "observability/metrics.py",
        [
            "abs_p2p_native_state_root_response_request_gate",
            "abs_p2p_state_root_response_request_rejects_total",
        ],
    ),
    (
        "1.3.128",
        "RELEASE_NOTES_v1.3.128.md",
        ["1.3.128-industrial", "dialable"],
    ),
    (
        "1.3.128",
        "native/abs_native/src/p2p_ingress.rs",
        ["p2p_peer_addr_is_dialable_inner"],
    ),
    (
        "1.3.128",
        "native/abs_native/src/p2p_wire.rs",
        [
            "verify_status_height_head_binding_inner",
            "verify_handshake_head_semantics_inner",
            "bad_status_height_head",
        ],
    ),
    (
        "1.3.128",
        "network/p2p_node.py",
        [
            "p2p_peer_addr_is_dialable",
            "p2p_discovery_allow_private",
            "verify_p2p_handshake_head_semantics",
        ],
    ),
    (
        "1.3.128",
        "network/p2p_dispatch/handlers.py",
        ["verify_p2p_status_height_head_binding"],
    ),
    (
        "1.3.128",
        "runtime/config.py",
        ["p2p_discovery_allow_private"],
    ),
    (
        "1.3.128",
        "observability/metrics.py",
        [
            "abs_p2p_native_discovery_dialability_gate",
            "abs_p2p_native_handshake_head_semantic_gate",
            "abs_p2p_native_status_height_head_gate",
        ],
    ),
    (
        "1.3.129",
        "RELEASE_NOTES_v1.3.129.md",
        ["1.3.129-industrial", "outbound"],
    ),
    (
        "1.3.129",
        "network/p2p_node.py",
        [
            "_state_root_response_for_height",
            "state_root_outbound_refuse_total",
            "must not inflate peer tip",
        ],
    ),
    (
        "1.3.129",
        "observability/metrics.py",
        [
            "abs_p2p_native_state_root_outbound_honesty",
            "abs_p2p_state_root_outbound_refuse_total",
        ],
    ),
    (
        "1.3.130",
        "RELEASE_NOTES_v1.3.130.md",
        ["1.3.130-industrial", "expected_head"],
    ),
    (
        "1.3.130",
        "native/abs_native/src/p2p_wire.rs",
        ["bad_state_root_response_head", "expected_head"],
    ),
    (
        "1.3.130",
        "network/p2p_node.py",
        ["expected_head"],
    ),
    (
        "1.3.130",
        ".github/dependabot.yml",
        ["package-ecosystem", "pip", "cargo"],
    ),
    (
        "1.3.130",
        "docs/AUDITS.md",
        ["not completed", "Pending"],
    ),
    (
        "1.3.130",
        "SUPPORT.md",
        ["Support", "SECURITY.md"],
    ),
    (
        "1.3.130",
        "observability/metrics.py",
        ["abs_p2p_native_state_root_response_head_gate"],
    ),
    (
        "1.3.131",
        "RELEASE_NOTES_v1.3.131.md",
        ["1.3.131-industrial", "mempool"],
    ),
    (
        "1.3.131",
        "network/p2p_node.py",
        [
            'kind": "mempool"',
            "unsolicited_mempool",
            "p2p_max_peer_height_ahead",
        ],
    ),
    (
        "1.3.131",
        "runtime/config.py",
        ["p2p_max_peer_height_ahead"],
    ),
    (
        "1.3.131",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_solicit_only",
            "abs_p2p_unsolicited_mempool_rejects_total",
            "abs_p2p_status_height_cap_total",
        ],
    ),
    (
        "1.3.132",
        "RELEASE_NOTES_v1.3.132.md",
        ["1.3.132-industrial", "bootstrap"],
    ),
    (
        "1.3.132",
        "network/p2p_node.py",
        [
            "_missing_bootstrap_addrs",
            "_peer_covers_bootstrap",
            "native_bootstrap_resilient",
            "dial_target",
        ],
    ),
    (
        "1.3.132",
        "observability/metrics.py",
        [
            "abs_p2p_native_bootstrap_resilient",
            "abs_p2p_bootstrap_redial_total",
            "abs_p2p_bootstrap_missing_count",
        ],
    ),
    (
        "1.3.133",
        "RELEASE_NOTES_v1.3.133.md",
        ["1.3.133-industrial", "bootstrap"],
    ),
    (
        "1.3.133",
        "network/p2p_tls.py",
        ["bootstrap_pin_map", "P2P_BOOTSTRAP_PINS"],
    ),
    (
        "1.3.133",
        "network/p2p_node.py",
        [
            "_bootstrap_pin_reject_reason",
            "native_bootstrap_pin_gate",
            "bootstrap_pin_mismatch",
        ],
    ),
    (
        "1.3.133",
        "runtime/config.py",
        ["p2p_bootstrap_pins"],
    ),
    (
        "1.3.133",
        "observability/metrics.py",
        [
            "abs_p2p_native_bootstrap_pin_gate",
            "abs_p2p_bootstrap_pin_rejects_total",
            "abs_p2p_bootstrap_pins_configured",
        ],
    ),
    (
        "1.3.134",
        "RELEASE_NOTES_v1.3.134.md",
        ["1.3.134-industrial", "new_block"],
    ),
    (
        "1.3.134",
        "network/p2p_node.py",
        [
            "new_block_height_cap_total",
            "native_new_block_height_cap",
            "v1.3.134",
        ],
    ),
    (
        "1.3.134",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_height_cap",
            "abs_p2p_new_block_height_cap_total",
        ],
    ),
    (
        "1.3.135",
        "RELEASE_NOTES_v1.3.135.md",
        ["1.3.135-industrial", "local"],
    ),
    (
        "1.3.135",
        "network/p2p_node.py",
        [
            "_state_root_request_ctx",
            "native_handshake_height_cap",
            "_cap_claimed_peer_height",
        ],
    ),
    (
        "1.3.135",
        "sync/solicit.py",
        ["bad_state_root_response_local_root"],
    ),
    (
        "1.3.135",
        "observability/metrics.py",
        [
            "abs_p2p_native_handshake_height_cap",
            "abs_p2p_state_root_local_rejects_total",
            "abs_p2p_native_status_capped_head_refuse",
        ],
    ),
    (
        "1.3.136",
        "RELEASE_NOTES_v1.3.136.md",
        ["1.3.136-industrial", "attestation"],
    ),
    (
        "1.3.136",
        "network/p2p_node.py",
        [
            "_attestation_ahead_reject_reason",
            "attestation_slot_ahead",
            "native_attestation_slot_ahead",
        ],
    ),
    (
        "1.3.136",
        "runtime/config.py",
        ["p2p_max_attestation_slot_ahead"],
    ),
    (
        "1.3.136",
        "observability/metrics.py",
        [
            "abs_p2p_native_attestation_slot_ahead",
            "abs_p2p_attestation_slot_ahead_rejects_total",
        ],
    ),
    (
        "1.3.137",
        "RELEASE_NOTES_v1.3.137.md",
        ["1.3.137-industrial", "solicit"],
    ),
    (
        "1.3.137",
        "network/p2p_node.py",
        [
            "_attestation_local_head_reject_reason",
            "attestation_local_height_mismatch",
            "native_block_solicit_only",
        ],
    ),
    (
        "1.3.137",
        "network/p2p_dispatch/handlers.py",
        ["unsolicited_blocks"],
    ),
    (
        "1.3.137",
        "observability/metrics.py",
        [
            "abs_p2p_native_attestation_local_head",
            "abs_p2p_unsolicited_block_rejects_total",
            "abs_p2p_native_block_solicit_only",
        ],
    ),
    (
        "1.3.138",
        "RELEASE_NOTES_v1.3.138.md",
        ["1.3.138-industrial", "ceremony_status"],
    ),
    (
        "1.3.138",
        "network/p2p_node.py",
        [
            "native_state_root_solicit_only",
        ],
    ),
    (
        "1.3.138",
        "network/p2p_dispatch/handlers.py",
        ["unsolicited_state_root_response"],
    ),
    (
        "1.3.138",
        "scripts/ceremony_status.py",
        ["never invents", "GENESIS_CEREMONY_HASH"],
    ),
    (
        "1.3.138",
        "scripts/check_all.ps1",
        ["ceremony_status"],
    ),
    (
        "1.3.138",
        "observability/metrics.py",
        [
            "abs_p2p_native_state_root_solicit_only",
            "abs_p2p_unsolicited_state_root_rejects_total",
        ],
    ),
    (
        "1.3.139",
        "RELEASE_NOTES_v1.3.139.md",
        ["1.3.139-industrial", "catch-up"],
    ),
    (
        "1.3.139",
        "network/p2p_node.py",
        [
            "_catch_up_ahead_refuse_reason",
            "catch_up_no_head",
            "native_catch_up_require_head",
        ],
    ),
    (
        "1.3.139",
        "runtime/config.py",
        ["p2p_catch_up_require_head"],
    ),
    (
        "1.3.139",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_require_head",
            "abs_p2p_catch_up_no_head_refuse_total",
        ],
    ),
    (
        "1.3.140",
        "RELEASE_NOTES_v1.3.140.md",
        ["1.3.140-industrial", "invent"],
    ),
    (
        "1.3.140",
        "sync/sync_engine.py",
        [
            "never invent peer.head",
            "heads_skipped_no_head",
            "native_sync_heads_no_invent",
        ],
    ),
    (
        "1.3.140",
        "observability/metrics.py",
        [
            "abs_p2p_native_sync_heads_no_invent",
            "abs_p2p_heads_skipped_no_head",
        ],
    ),
    (
        "1.3.141",
        "RELEASE_NOTES_v1.3.141.md",
        ["1.3.141-industrial", "wire"],
    ),
    (
        "1.3.141",
        "sync/sync_engine.py",
        [
            "same-height consistency only from wire roots",
            "native_sync_state_wire_only",
        ],
    ),
    (
        "1.3.141",
        "observability/metrics.py",
        ["abs_p2p_native_sync_state_wire_only"],
    ),
    (
        "1.3.142",
        "RELEASE_NOTES_v1.3.142.md",
        ["1.3.142-industrial", "solicit"],
    ),
    (
        "1.3.142",
        "tests/unit/test_silent_except_honesty.py",
        ["unsolicited_state_root_response", "solicit-only"],
    ),
    (
        "1.3.143",
        "RELEASE_NOTES_v1.3.143.md",
        ["1.3.143-industrial", "cheap"],
    ),
    (
        "1.3.143",
        "network/p2p_node.py",
        [
            "native_mempool_cheap_refuse",
            "native_mempool_new_tx_rate_primary",
            "duplicate_tx",
        ],
    ),
    (
        "1.3.143",
        "core/components/tx_pipeline.py",
        ["nonce/balance DB lookups"],
    ),
    (
        "1.3.143",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_cheap_refuse",
            "abs_p2p_mempool_dup_refuse_total",
        ],
    ),
    (
        "1.3.144",
        "RELEASE_NOTES_v1.3.144.md",
        ["1.3.144-industrial", "solicit"],
    ),
    (
        "1.3.144",
        "native/abs_native/src/p2p_transport.rs",
        ["mempool_solicit_armed", "unsolicited_mempool"],
    ),
    (
        "1.3.144",
        "network/p2p_node.py",
        ["_mempool_solicit_armed_for", "native_mempool_solicit_armed_shell"],
    ),
    (
        "1.3.144",
        "observability/metrics.py",
        ["abs_p2p_native_mempool_solicit_armed_shell"],
    ),
    (
        "1.3.145",
        "RELEASE_NOTES_v1.3.145.md",
        ["1.3.145-industrial", "score"],
    ),
    (
        "1.3.145",
        "network/p2p_node.py",
        [
            "native_peer_score_quality",
            "_score_peer",
            "_note_peer_import_fail",
            "quality_import_fails",
        ],
    ),
    (
        "1.3.145",
        "observability/metrics.py",
        ["abs_p2p_native_peer_score_quality"],
    ),
    (
        "1.3.146",
        "RELEASE_NOTES_v1.3.146.md",
        ["1.3.146-industrial", "tip"],
    ),
    (
        "1.3.146",
        "network/p2p_node.py",
        [
            "catch_up_head_height_mismatch",
            "_catch_up_local_tip_probe_refuse_reason",
            "native_catch_up_tip_probe",
        ],
    ),
    (
        "1.3.146",
        "runtime/config.py",
        ["p2p_catch_up_tip_probe"],
    ),
    (
        "1.3.146",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_tip_probe",
            "abs_p2p_catch_up_tip_probe_refuse_total",
        ],
    ),
    (
        "1.3.147",
        "RELEASE_NOTES_v1.3.147.md",
        ["1.3.147-industrial", "ABAR"],
    ),
    (
        "1.3.147",
        "native/abs_native/src/account_row.rs",
        ["pack_account_row_value", "account_blob_to_value", "ABAR"],
    ),
    (
        "1.3.147",
        "storage/rocks_store.py",
        ["_pack_account_blob", "_loads_account_blob_or_none", "ABAR"],
    ),
    (
        "1.3.148",
        "RELEASE_NOTES_v1.3.148.md",
        ["1.3.148-industrial", "ATXV"],
    ),
    (
        "1.3.148",
        "native/abs_native/src/tx_row.rs",
        ["pack_tx_row_value", "tx_blob_to_value", "ATXV"],
    ),
    (
        "1.3.148",
        "storage/rocks_store.py",
        ["_pack_tx_blob", "_loads_tx_blob_or_none", "ATXV"],
    ),
    (
        "1.3.149",
        "RELEASE_NOTES_v1.3.149.md",
        ["1.3.149-industrial", "ABLK"],
    ),
    (
        "1.3.149",
        "native/abs_native/src/block_row.rs",
        ["pack_block_row_value", "block_blob_to_value", "ABLK"],
    ),
    (
        "1.3.149",
        "storage/rocks_store.py",
        ["_pack_block_blob", "_loads_block_blob_or_none", "ABLK"],
    ),
    (
        "1.3.150",
        "RELEASE_NOTES_v1.3.150.md",
        ["1.3.150-industrial", "new_tx"],
    ),
    (
        "1.3.150",
        "tests/unit/test_p2p_industrial.py",
        ["MSG_NEW_TX not in RATE_LIMIT_EXEMPT_TYPES"],
    ),
    (
        "1.3.150",
        "tests/unit/test_supply_broadcast_honesty.py",
        ["_loads_tx_blob_or_none", "_loads_block_blob_or_none"],
    ),
    (
        "1.3.151",
        "RELEASE_NOTES_v1.3.151.md",
        ["1.3.151-industrial", "ATXR"],
    ),
    (
        "1.3.151",
        "native/abs_native/src/receipt_row.rs",
        ["pack_receipt_row_value", "receipt_blob_to_value", "ATXR"],
    ),
    (
        "1.3.151",
        "storage/rocks_store.py",
        ["_pack_receipt_blob", "_loads_receipt_blob_or_none", "ATXR"],
    ),
    (
        "1.3.152",
        "RELEASE_NOTES_v1.3.152.md",
        ["1.3.152-industrial", "unsolicited_peers"],
    ),
    (
        "1.3.152",
        "network/p2p_node.py",
        [
            "unsolicited_peers",
            "native_peers_solicit_only",
            "_ingest_discovered_peers",
        ],
    ),
    (
        "1.3.152",
        "runtime/config.py",
        ["p2p_peers_solicit_only"],
    ),
    (
        "1.3.152",
        "observability/metrics.py",
        [
            "abs_p2p_native_peers_solicit_only",
            "abs_p2p_unsolicited_peers_rejects_total",
        ],
    ),
    (
        "1.3.153",
        "RELEASE_NOTES_v1.3.153.md",
        ["1.3.153-industrial", "new_block_head_height_mismatch"],
    ),
    (
        "1.3.153",
        "network/p2p_node.py",
        [
            "new_block_head_height_mismatch",
            "_new_block_head_height_refuse_reason",
            "native_new_block_head_height_bind",
        ],
    ),
    (
        "1.3.153",
        "runtime/config.py",
        ["p2p_new_block_head_height_bind"],
    ),
    (
        "1.3.153",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_head_height_bind",
            "abs_p2p_new_block_head_height_mismatch_total",
        ],
    ),
    (
        "1.3.154",
        "RELEASE_NOTES_v1.3.154.md",
        ["1.3.154-industrial", "catch_up_peer_head_probe_failed"],
    ),
    (
        "1.3.154",
        "network/p2p_node.py",
        [
            "catch_up_peer_head_probe_failed",
            "_catch_up_peer_head_probe_refuse_reason",
            "native_catch_up_peer_head_probe",
        ],
    ),
    (
        "1.3.154",
        "runtime/config.py",
        ["p2p_catch_up_peer_head_probe"],
    ),
    (
        "1.3.154",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_peer_head_probe",
            "abs_p2p_catch_up_peer_head_probe_refuse_total",
        ],
    ),
    (
        "1.3.155",
        "RELEASE_NOTES_v1.3.155.md",
        ["1.3.155-industrial", "status_head_height_mismatch"],
    ),
    (
        "1.3.155",
        "network/p2p_node.py",
        [
            "status_head_height_mismatch",
            "handshake_head_height_mismatch",
            "_status_head_height_refuse_reason",
            "native_status_head_height_bind",
        ],
    ),
    (
        "1.3.155",
        "runtime/config.py",
        ["p2p_status_head_height_bind"],
    ),
    (
        "1.3.155",
        "observability/metrics.py",
        [
            "abs_p2p_native_status_head_height_bind",
            "abs_p2p_status_head_height_mismatch_total",
        ],
    ),
    (
        "1.3.156",
        "RELEASE_NOTES_v1.3.156.md",
        ["1.3.156-industrial", "new_block_announce_hash_mismatch"],
    ),
    (
        "1.3.156",
        "network/p2p_node.py",
        [
            "new_block_announce_hash_mismatch",
            "_new_block_announce_body_refuse_reason",
            "native_new_block_defer_tip",
        ],
    ),
    (
        "1.3.156",
        "runtime/config.py",
        ["p2p_new_block_announce_body_bind"],
    ),
    (
        "1.3.156",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_announce_body_bind",
            "abs_p2p_new_block_announce_body_refuse_total",
        ],
    ),
    (
        "1.3.157",
        "RELEASE_NOTES_v1.3.157.md",
        ["1.3.157-industrial", "catch_up_peer_head_parent_mismatch"],
    ),
    (
        "1.3.157",
        "network/p2p_node.py",
        [
            "catch_up_peer_head_parent_mismatch",
            "native_catch_up_peer_head_parent_bind",
        ],
    ),
    (
        "1.3.157",
        "runtime/config.py",
        ["p2p_catch_up_peer_head_parent_bind"],
    ),
    (
        "1.3.157",
        "observability/metrics.py",
        ["abs_p2p_native_catch_up_peer_head_parent_bind"],
    ),
    (
        "1.3.158",
        "RELEASE_NOTES_v1.3.158.md",
        ["1.3.158-industrial", "HS256"],
    ),
    (
        "1.3.158",
        "middleware/jwt_auth.py",
        ["MIN_HS256_SECRET_BYTES", "_assert_hs256_secret"],
    ),
    (
        "1.3.158",
        "runtime/config.py",
        ["HS256 requires >= 32 bytes"],
    ),
    (
        "1.3.159",
        "RELEASE_NOTES_v1.3.159.md",
        ["1.3.159-industrial", "clear fantasy head"],
    ),
    (
        "1.3.159",
        "network/p2p_node.py",
        [
            "p2p_height_cap_clear_head",
            "native_height_cap_clear_head",
            "clear fantasy head with capped height",
        ],
    ),
    (
        "1.3.159",
        "runtime/config.py",
        ["p2p_height_cap_clear_head"],
    ),
    (
        "1.3.159",
        "observability/metrics.py",
        ["abs_p2p_native_height_cap_clear_head"],
    ),
    (
        "1.3.160",
        "RELEASE_NOTES_v1.3.160.md",
        ["1.3.160-industrial", "new_block_contiguous_parent_mismatch"],
    ),
    (
        "1.3.160",
        "network/p2p_node.py",
        [
            "new_block_contiguous_parent_mismatch",
            "_new_block_contiguous_parent_refuse_reason",
            "native_new_block_contiguous_parent_bind",
        ],
    ),
    (
        "1.3.160",
        "runtime/config.py",
        ["p2p_new_block_contiguous_parent_bind"],
    ),
    (
        "1.3.160",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_contiguous_parent_bind",
            "abs_p2p_new_block_contiguous_parent_mismatch_total",
        ],
    ),
    (
        "1.3.161",
        "RELEASE_NOTES_v1.3.161.md",
        ["1.3.161-industrial", "status_head_without_height"],
    ),
    (
        "1.3.161",
        "network/p2p_node.py",
        [
            "status_head_without_height",
            "native_status_head_requires_height",
        ],
    ),
    (
        "1.3.161",
        "runtime/config.py",
        ["p2p_status_head_requires_height"],
    ),
    (
        "1.3.161",
        "observability/metrics.py",
        [
            "abs_p2p_native_status_head_requires_height",
            "abs_p2p_status_head_without_height_total",
        ],
    ),
    (
        "1.3.162",
        "RELEASE_NOTES_v1.3.162.md",
        ["1.3.162-industrial", "fork_peer_head_probe_failed"],
    ),
    (
        "1.3.162",
        "network/p2p_node.py",
        [
            "fork_peer_head_probe_failed",
            "_fork_peer_head_probe_refuse_reason",
            "native_fork_peer_head_probe",
        ],
    ),
    (
        "1.3.162",
        "runtime/config.py",
        ["p2p_fork_peer_head_probe"],
    ),
    (
        "1.3.162",
        "observability/metrics.py",
        [
            "abs_p2p_native_fork_peer_head_probe",
            "abs_p2p_fork_peer_head_probe_refuse_total",
        ],
    ),
    (
        "1.3.163",
        "RELEASE_NOTES_v1.3.163.md",
        ["1.3.163-industrial", "reconcile_head_hash_mismatch"],
    ),
    (
        "1.3.163",
        "network/p2p_node.py",
        [
            "reconcile_head_hash_mismatch",
            "_reconcile_fetched_head_refuse_reason",
            "native_reconcile_head_hash_bind",
        ],
    ),
    (
        "1.3.163",
        "runtime/config.py",
        ["p2p_reconcile_head_hash_bind"],
    ),
    (
        "1.3.163",
        "observability/metrics.py",
        [
            "abs_p2p_native_reconcile_head_hash_bind",
            "abs_p2p_reconcile_head_hash_mismatch_total",
        ],
    ),
    (
        "1.3.164",
        "RELEASE_NOTES_v1.3.164.md",
        ["1.3.164-industrial", "ghost_head_probe_failed"],
    ),
    (
        "1.3.164",
        "network/p2p_node.py",
        [
            "ghost_head_probe_failed",
            "_ghost_head_probe_refuse_reason",
            "native_ghost_head_probe",
        ],
    ),
    (
        "1.3.164",
        "runtime/config.py",
        ["p2p_ghost_head_probe"],
    ),
    (
        "1.3.164",
        "observability/metrics.py",
        [
            "abs_p2p_native_ghost_head_probe",
            "abs_p2p_ghost_head_probe_refuse_total",
        ],
    ),
    (
        "1.3.165",
        "RELEASE_NOTES_v1.3.165.md",
        ["1.3.165-industrial", "reconcile_contiguous_parent_mismatch"],
    ),
    (
        "1.3.165",
        "network/p2p_node.py",
        [
            "reconcile_contiguous_parent_mismatch",
            "_reconcile_contiguous_parent_refuse_reason",
            "native_reconcile_contiguous_parent_bind",
        ],
    ),
    (
        "1.3.165",
        "runtime/config.py",
        ["p2p_reconcile_contiguous_parent_bind"],
    ),
    (
        "1.3.165",
        "observability/metrics.py",
        [
            "abs_p2p_native_reconcile_contiguous_parent_bind",
            "abs_p2p_reconcile_contiguous_parent_mismatch_total",
        ],
    ),
    (
        "1.3.166",
        "RELEASE_NOTES_v1.3.166.md",
        ["1.3.166-industrial", "handshake_head_without_height"],
    ),
    (
        "1.3.166",
        "network/p2p_node.py",
        [
            "handshake_head_without_height",
            "_handshake_head_without_height_refuse_reason",
            "native_handshake_head_requires_height",
        ],
    ),
    (
        "1.3.166",
        "runtime/config.py",
        ["p2p_handshake_head_requires_height"],
    ),
    (
        "1.3.166",
        "observability/metrics.py",
        [
            "abs_p2p_native_handshake_head_requires_height",
            "abs_p2p_handshake_head_without_height_total",
        ],
    ),
    (
        "1.3.167",
        "RELEASE_NOTES_v1.3.167.md",
        ["1.3.167-industrial", "attestation_target_head_mismatch"],
    ),
    (
        "1.3.167",
        "network/p2p_node.py",
        [
            "attestation_target_head_mismatch",
            "_attestation_target_head_refuse_reason",
            "native_attestation_target_head_bind",
        ],
    ),
    (
        "1.3.167",
        "runtime/config.py",
        ["p2p_attestation_target_head_bind"],
    ),
    (
        "1.3.167",
        "observability/metrics.py",
        [
            "abs_p2p_native_attestation_target_head_bind",
            "abs_p2p_attestation_target_head_rejects_total",
        ],
    ),
    (
        "1.3.168",
        "RELEASE_NOTES_v1.3.168.md",
        ["1.3.168-industrial", "fork_peer_head_parent_mismatch"],
    ),
    (
        "1.3.168",
        "network/p2p_node.py",
        [
            "fork_peer_head_parent_mismatch",
            "native_fork_peer_head_parent_bind",
            "p2p_fork_peer_head_parent_bind",
        ],
    ),
    (
        "1.3.168",
        "runtime/config.py",
        ["p2p_fork_peer_head_parent_bind"],
    ),
    (
        "1.3.168",
        "observability/metrics.py",
        ["abs_p2p_native_fork_peer_head_parent_bind"],
    ),
    (
        "1.3.169",
        "RELEASE_NOTES_v1.3.169.md",
        ["1.3.169-industrial", "ghost_head_parent_mismatch"],
    ),
    (
        "1.3.169",
        "network/p2p_node.py",
        [
            "ghost_head_parent_mismatch",
            "native_ghost_head_parent_bind",
            "p2p_ghost_head_parent_bind",
        ],
    ),
    (
        "1.3.169",
        "runtime/config.py",
        ["p2p_ghost_head_parent_bind"],
    ),
    (
        "1.3.169",
        "observability/metrics.py",
        ["abs_p2p_native_ghost_head_parent_bind"],
    ),
    (
        "1.3.170",
        "RELEASE_NOTES_v1.3.170.md",
        ["1.3.170-industrial", "new_block_same_height_parent_mismatch"],
    ),
    (
        "1.3.170",
        "network/p2p_node.py",
        [
            "new_block_same_height_parent_mismatch",
            "_new_block_same_height_parent_refuse_reason",
            "native_new_block_same_height_parent_bind",
        ],
    ),
    (
        "1.3.170",
        "runtime/config.py",
        ["p2p_new_block_same_height_parent_bind"],
    ),
    (
        "1.3.170",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_same_height_parent_bind",
            "abs_p2p_new_block_same_height_parent_mismatch_total",
        ],
    ),
    (
        "1.3.171",
        "RELEASE_NOTES_v1.3.171.md",
        ["1.3.171-industrial", "reconcile_same_height_parent_mismatch"],
    ),
    (
        "1.3.171",
        "network/p2p_node.py",
        [
            "reconcile_same_height_parent_mismatch",
            "_reconcile_same_height_parent_refuse_reason",
            "native_reconcile_same_height_parent_bind",
        ],
    ),
    (
        "1.3.171",
        "runtime/config.py",
        ["p2p_reconcile_same_height_parent_bind"],
    ),
    (
        "1.3.171",
        "observability/metrics.py",
        [
            "abs_p2p_native_reconcile_same_height_parent_bind",
            "abs_p2p_reconcile_same_height_parent_mismatch_total",
        ],
    ),
    (
        "1.3.172",
        "RELEASE_NOTES_v1.3.172.md",
        ["1.3.172-industrial", "catch_up_tip_head_mismatch"],
    ),
    (
        "1.3.172",
        "network/p2p_node.py",
        [
            "catch_up_tip_head_mismatch",
            "_catch_up_tip_head_refuse_reason",
            "native_catch_up_tip_head_bind",
        ],
    ),
    (
        "1.3.172",
        "runtime/config.py",
        ["p2p_catch_up_tip_head_bind"],
    ),
    (
        "1.3.172",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_tip_head_bind",
            "abs_p2p_catch_up_tip_head_mismatch_total",
        ],
    ),
    (
        "1.3.173",
        "RELEASE_NOTES_v1.3.173.md",
        ["1.3.173-industrial", "reconcile_tip_head_mismatch"],
    ),
    (
        "1.3.173",
        "network/p2p_node.py",
        [
            "reconcile_tip_head_mismatch",
            "_reconcile_tip_head_refuse_reason",
            "native_reconcile_tip_head_bind",
        ],
    ),
    (
        "1.3.173",
        "runtime/config.py",
        ["p2p_reconcile_tip_head_bind"],
    ),
    (
        "1.3.173",
        "observability/metrics.py",
        [
            "abs_p2p_native_reconcile_tip_head_bind",
            "abs_p2p_reconcile_tip_head_mismatch_total",
        ],
    ),
    (
        "1.3.174",
        "RELEASE_NOTES_v1.3.174.md",
        ["1.3.174-industrial", "new_block_tip_head_mismatch"],
    ),
    (
        "1.3.174",
        "network/p2p_node.py",
        [
            "new_block_tip_head_mismatch",
            "_new_block_tip_head_refuse_reason",
            "native_new_block_tip_head_bind",
        ],
    ),
    (
        "1.3.174",
        "runtime/config.py",
        ["p2p_new_block_tip_head_bind"],
    ),
    (
        "1.3.174",
        "observability/metrics.py",
        [
            "abs_p2p_native_new_block_tip_head_bind",
            "abs_p2p_new_block_tip_head_mismatch_total",
        ],
    ),
    (
        "1.3.175",
        "RELEASE_NOTES_v1.3.175.md",
        ["1.3.175-industrial", "catch_up_contiguous_parent_mismatch"],
    ),
    (
        "1.3.175",
        "network/p2p_node.py",
        [
            "catch_up_contiguous_parent_mismatch",
            "_catch_up_contiguous_parent_refuse_reason",
            "native_catch_up_contiguous_parent_bind",
        ],
    ),
    (
        "1.3.175",
        "runtime/config.py",
        ["p2p_catch_up_contiguous_parent_bind"],
    ),
    (
        "1.3.175",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_contiguous_parent_bind",
            "abs_p2p_catch_up_contiguous_parent_mismatch_total",
        ],
    ),
    (
        "1.3.176",
        "RELEASE_NOTES_v1.3.176.md",
        ["1.3.176-industrial", "catch_up_height_continuity_mismatch"],
    ),
    (
        "1.3.176",
        "network/p2p_node.py",
        [
            "catch_up_height_continuity_mismatch",
            "_catch_up_height_continuity_refuse_reason",
            "native_catch_up_height_continuity_bind",
        ],
    ),
    (
        "1.3.176",
        "runtime/config.py",
        ["p2p_catch_up_height_continuity_bind"],
    ),
    (
        "1.3.176",
        "observability/metrics.py",
        [
            "abs_p2p_native_catch_up_height_continuity_bind",
            "abs_p2p_catch_up_height_continuity_mismatch_total",
        ],
    ),
    (
        "1.3.177",
        "RELEASE_NOTES_v1.3.177.md",
        ["1.3.177-industrial", "fee_too_low"],
    ),
    (
        "1.3.177",
        "network/p2p_node.py",
        [
            "fee_too_low",
            "p2p_mempool_min_fee_refuse",
            "native_mempool_min_fee_refuse",
        ],
    ),
    (
        "1.3.177",
        "runtime/config.py",
        ["p2p_mempool_min_fee_refuse"],
    ),
    (
        "1.3.177",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_min_fee_refuse",
            "abs_p2p_mempool_fee_refuse_total",
        ],
    ),
    (
        "1.3.178",
        "RELEASE_NOTES_v1.3.178.md",
        ["1.3.178-industrial", "get_mempool_tip_misaligned"],
    ),
    (
        "1.3.178",
        "network/p2p_node.py",
        [
            "get_mempool_tip_misaligned",
            "_get_mempool_tip_align_refuse_reason",
            "native_mempool_serve_tip_align",
        ],
    ),
    (
        "1.3.178",
        "runtime/config.py",
        ["p2p_mempool_serve_tip_align"],
    ),
    (
        "1.3.178",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_serve_tip_align",
            "abs_p2p_get_mempool_tip_misaligned_total",
        ],
    ),
    (
        "1.3.179",
        "RELEASE_NOTES_v1.3.179.md",
        ["1.3.179-industrial", "gas_too_high"],
    ),
    (
        "1.3.179",
        "network/p2p_node.py",
        [
            "gas_too_high",
            "p2p_mempool_max_gas_refuse",
            "native_mempool_max_gas_refuse",
        ],
    ),
    (
        "1.3.179",
        "runtime/config.py",
        ["p2p_mempool_max_gas_refuse"],
    ),
    (
        "1.3.179",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_gas_refuse",
            "abs_p2p_mempool_gas_refuse_total",
        ],
    ),
    (
        "1.3.180",
        "RELEASE_NOTES_v1.3.180.md",
        ["1.3.180-industrial", "get_blocks_future_height"],
    ),
    (
        "1.3.180",
        "network/p2p_node.py",
        [
            "get_blocks_future_height",
            "_get_blocks_future_refuse_reason",
            "native_get_blocks_future_refuse",
        ],
    ),
    (
        "1.3.180",
        "runtime/config.py",
        ["p2p_get_blocks_future_refuse"],
    ),
    (
        "1.3.180",
        "observability/metrics.py",
        [
            "abs_p2p_native_get_blocks_future_refuse",
            "abs_p2p_get_blocks_future_refuse_total",
        ],
    ),
    (
        "1.3.181",
        "RELEASE_NOTES_v1.3.181.md",
        ["1.3.181-industrial", "get_block_future_height"],
    ),
    (
        "1.3.181",
        "network/p2p_node.py",
        [
            "get_block_future_height",
            "_get_block_future_refuse_reason",
            "native_get_block_future_refuse",
        ],
    ),
    (
        "1.3.181",
        "runtime/config.py",
        ["p2p_get_block_future_refuse"],
    ),
    (
        "1.3.181",
        "observability/metrics.py",
        [
            "abs_p2p_native_get_block_future_refuse",
            "abs_p2p_get_block_future_refuse_total",
        ],
    ),
    (
        "1.3.182",
        "RELEASE_NOTES_v1.3.182.md",
        ["1.3.182-industrial", "get_blocks_past_tip_clamp"],
    ),
    (
        "1.3.182",
        "network/p2p_node.py",
        [
            "get_blocks_past_tip_clamp",
            "_get_blocks_past_tip_clamp_end",
            "native_get_blocks_past_tip_clamp",
        ],
    ),
    (
        "1.3.182",
        "runtime/config.py",
        ["p2p_get_blocks_past_tip_clamp"],
    ),
    (
        "1.3.182",
        "observability/metrics.py",
        [
            "abs_p2p_native_get_blocks_past_tip_clamp",
            "abs_p2p_get_blocks_past_tip_clamp_total",
        ],
    ),
    (
        "1.3.183",
        "RELEASE_NOTES_v1.3.183.md",
        ["1.3.183-industrial", "calldata_too_large"],
    ),
    (
        "1.3.183",
        "network/p2p_node.py",
        [
            "calldata_too_large",
            "_wire_calldata_byte_len",
            "native_mempool_max_calldata_refuse",
        ],
    ),
    (
        "1.3.183",
        "runtime/config.py",
        ["p2p_mempool_max_calldata_refuse", "p2p_mempool_max_calldata_bytes"],
    ),
    (
        "1.3.183",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_calldata_refuse",
            "abs_p2p_mempool_calldata_refuse_total",
        ],
    ),
    (
        "1.3.184",
        "RELEASE_NOTES_v1.3.184.md",
        ["1.3.184-industrial", "value_negative"],
    ),
    (
        "1.3.184",
        "network/p2p_node.py",
        [
            "value_negative",
            "p2p_mempool_negative_value_refuse",
            "native_mempool_negative_value_refuse",
        ],
    ),
    (
        "1.3.184",
        "runtime/config.py",
        ["p2p_mempool_negative_value_refuse"],
    ),
    (
        "1.3.184",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_negative_value_refuse",
            "abs_p2p_mempool_value_refuse_total",
        ],
    ),
    (
        "1.3.185",
        "RELEASE_NOTES_v1.3.185.md",
        ["1.3.185-industrial", "nonce_negative"],
    ),
    (
        "1.3.185",
        "network/p2p_node.py",
        [
            "nonce_negative",
            "p2p_mempool_negative_nonce_refuse",
            "native_mempool_negative_nonce_refuse",
        ],
    ),
    (
        "1.3.185",
        "runtime/config.py",
        ["p2p_mempool_negative_nonce_refuse"],
    ),
    (
        "1.3.185",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_negative_nonce_refuse",
            "abs_p2p_mempool_nonce_refuse_total",
        ],
    ),
    (
        "1.3.186",
        "RELEASE_NOTES_v1.3.186.md",
        ["1.3.186-industrial", "fee_negative"],
    ),
    (
        "1.3.186",
        "network/p2p_node.py",
        [
            "fee_negative",
            "p2p_mempool_negative_fee_refuse",
            "native_mempool_negative_fee_refuse",
        ],
    ),
    (
        "1.3.186",
        "runtime/config.py",
        ["p2p_mempool_negative_fee_refuse"],
    ),
    (
        "1.3.186",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_negative_fee_refuse",
            "abs_p2p_mempool_fee_negative_refuse_total",
        ],
    ),
    (
        "1.3.187",
        "RELEASE_NOTES_v1.3.187.md",
        ["1.3.187-industrial", "gas_negative"],
    ),
    (
        "1.3.187",
        "network/p2p_node.py",
        [
            "gas_negative",
            "p2p_mempool_negative_gas_refuse",
            "native_mempool_negative_gas_refuse",
        ],
    ),
    (
        "1.3.187",
        "runtime/config.py",
        ["p2p_mempool_negative_gas_refuse"],
    ),
    (
        "1.3.187",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_negative_gas_refuse",
            "abs_p2p_mempool_gas_negative_refuse_total",
        ],
    ),
    (
        "1.3.188",
        "RELEASE_NOTES_v1.3.188.md",
        ["1.3.188-industrial", "from_empty"],
    ),
    (
        "1.3.188",
        "network/p2p_node.py",
        [
            "from_empty",
            "p2p_mempool_empty_from_refuse",
            "native_mempool_empty_from_refuse",
        ],
    ),
    (
        "1.3.188",
        "runtime/config.py",
        ["p2p_mempool_empty_from_refuse"],
    ),
    (
        "1.3.188",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_empty_from_refuse",
            "abs_p2p_mempool_empty_from_refuse_total",
        ],
    ),
    (
        "1.3.189",
        "RELEASE_NOTES_v1.3.189.md",
        ["1.3.189-industrial", "signature_empty"],
    ),
    (
        "1.3.189",
        "network/p2p_node.py",
        [
            "signature_empty",
            "p2p_mempool_empty_sig_refuse",
            "native_mempool_empty_sig_refuse",
        ],
    ),
    (
        "1.3.189",
        "runtime/config.py",
        ["p2p_mempool_empty_sig_refuse"],
    ),
    (
        "1.3.189",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_empty_sig_refuse",
            "abs_p2p_mempool_empty_sig_refuse_total",
        ],
    ),
    (
        "1.3.190",
        "RELEASE_NOTES_v1.3.190.md",
        ["1.3.190-industrial", "pubkey_empty"],
    ),
    (
        "1.3.190",
        "network/p2p_node.py",
        [
            "pubkey_empty",
            "p2p_mempool_empty_pubkey_refuse",
            "native_mempool_empty_pubkey_refuse",
        ],
    ),
    (
        "1.3.190",
        "runtime/config.py",
        ["p2p_mempool_empty_pubkey_refuse"],
    ),
    (
        "1.3.190",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_empty_pubkey_refuse",
            "abs_p2p_mempool_empty_pubkey_refuse_total",
        ],
    ),
    (
        "1.3.191",
        "RELEASE_NOTES_v1.3.191.md",
        ["1.3.191-industrial", "signature_too_large"],
    ),
    (
        "1.3.191",
        "network/p2p_node.py",
        [
            "signature_too_large",
            "p2p_mempool_max_sig_refuse",
            "native_mempool_max_sig_refuse",
        ],
    ),
    (
        "1.3.191",
        "runtime/config.py",
        ["p2p_mempool_max_sig_refuse", "p2p_mempool_max_sig_bytes"],
    ),
    (
        "1.3.191",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_sig_refuse",
            "abs_p2p_mempool_sig_size_refuse_total",
        ],
    ),
    (
        "1.3.192",
        "RELEASE_NOTES_v1.3.192.md",
        ["1.3.192-industrial", "pubkey_too_large"],
    ),
    (
        "1.3.192",
        "network/p2p_node.py",
        [
            "pubkey_too_large",
            "p2p_mempool_max_pubkey_refuse",
            "native_mempool_max_pubkey_refuse",
        ],
    ),
    (
        "1.3.192",
        "runtime/config.py",
        ["p2p_mempool_max_pubkey_refuse", "p2p_mempool_max_pubkey_bytes"],
    ),
    (
        "1.3.192",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_pubkey_refuse",
            "abs_p2p_mempool_pubkey_size_refuse_total",
        ],
    ),
    (
        "1.3.193",
        "RELEASE_NOTES_v1.3.193.md",
        ["1.3.193-industrial", "value_non_finite"],
    ),
    (
        "1.3.193",
        "network/p2p_node.py",
        [
            "value_non_finite",
            "p2p_mempool_nonfinite_value_refuse",
            "native_mempool_nonfinite_value_refuse",
        ],
    ),
    (
        "1.3.193",
        "runtime/config.py",
        ["p2p_mempool_nonfinite_value_refuse"],
    ),
    (
        "1.3.193",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_nonfinite_value_refuse",
            "abs_p2p_mempool_nonfinite_value_refuse_total",
        ],
    ),
    (
        "1.3.194",
        "RELEASE_NOTES_v1.3.194.md",
        ["1.3.194-industrial", "fee_non_finite"],
    ),
    (
        "1.3.194",
        "network/p2p_node.py",
        [
            "fee_non_finite",
            "p2p_mempool_nonfinite_fee_refuse",
            "native_mempool_nonfinite_fee_refuse",
        ],
    ),
    (
        "1.3.194",
        "runtime/config.py",
        ["p2p_mempool_nonfinite_fee_refuse"],
    ),
    (
        "1.3.194",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_nonfinite_fee_refuse",
            "abs_p2p_mempool_nonfinite_fee_refuse_total",
        ],
    ),
    (
        "1.3.195",
        "RELEASE_NOTES_v1.3.195.md",
        ["1.3.195-industrial", "to_empty"],
    ),
    (
        "1.3.195",
        "network/p2p_node.py",
        [
            "to_empty",
            "p2p_mempool_empty_to_refuse",
            "native_mempool_empty_to_refuse",
        ],
    ),
    (
        "1.3.195",
        "runtime/config.py",
        ["p2p_mempool_empty_to_refuse"],
    ),
    (
        "1.3.195",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_empty_to_refuse",
            "abs_p2p_mempool_empty_to_refuse_total",
        ],
    ),
    (
        "1.3.196",
        "RELEASE_NOTES_v1.3.196.md",
        ["1.3.196-industrial", "hash_empty"],
    ),
    (
        "1.3.196",
        "network/p2p_node.py",
        [
            "hash_empty",
            "p2p_mempool_empty_hash_refuse",
            "native_mempool_empty_hash_refuse",
        ],
    ),
    (
        "1.3.196",
        "runtime/config.py",
        ["p2p_mempool_empty_hash_refuse"],
    ),
    (
        "1.3.196",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_empty_hash_refuse",
            "abs_p2p_mempool_empty_hash_refuse_total",
        ],
    ),
    (
        "1.3.197",
        "RELEASE_NOTES_v1.3.197.md",
        ["1.3.197-industrial", "hash_too_large"],
    ),
    (
        "1.3.197",
        "network/p2p_node.py",
        [
            "hash_too_large",
            "p2p_mempool_max_hash_refuse",
            "native_mempool_max_hash_refuse",
        ],
    ),
    (
        "1.3.197",
        "runtime/config.py",
        ["p2p_mempool_max_hash_refuse", "p2p_mempool_max_hash_chars"],
    ),
    (
        "1.3.197",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_hash_refuse",
            "abs_p2p_mempool_hash_size_refuse_total",
        ],
    ),
    (
        "1.3.198",
        "RELEASE_NOTES_v1.3.198.md",
        ["1.3.198-industrial", "from_too_large"],
    ),
    (
        "1.3.198",
        "network/p2p_node.py",
        [
            "from_too_large",
            "p2p_mempool_max_from_refuse",
            "native_mempool_max_from_refuse",
        ],
    ),
    (
        "1.3.198",
        "runtime/config.py",
        ["p2p_mempool_max_from_refuse", "p2p_mempool_max_addr_chars"],
    ),
    (
        "1.3.198",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_from_refuse",
            "abs_p2p_mempool_from_size_refuse_total",
        ],
    ),
    (
        "1.3.199",
        "RELEASE_NOTES_v1.3.199.md",
        ["1.3.199-industrial", "to_too_large"],
    ),
    (
        "1.3.199",
        "network/p2p_node.py",
        [
            "to_too_large",
            "p2p_mempool_max_to_refuse",
            "native_mempool_max_to_refuse",
        ],
    ),
    (
        "1.3.199",
        "runtime/config.py",
        ["p2p_mempool_max_to_refuse"],
    ),
    (
        "1.3.199",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_to_refuse",
            "abs_p2p_mempool_to_size_refuse_total",
        ],
    ),
    (
        "1.3.200",
        "RELEASE_NOTES_v1.3.200.md",
        ["1.3.200-industrial", "nonce_too_high"],
    ),
    (
        "1.3.200",
        "network/p2p_node.py",
        [
            "nonce_too_high",
            "p2p_mempool_max_nonce_refuse",
            "native_mempool_max_nonce_refuse",
        ],
    ),
    (
        "1.3.200",
        "runtime/config.py",
        ["p2p_mempool_max_nonce_refuse", "p2p_mempool_max_nonce"],
    ),
    (
        "1.3.200",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_nonce_refuse",
            "abs_p2p_mempool_nonce_high_refuse_total",
        ],
    ),
    (
        "1.3.201",
        "RELEASE_NOTES_v1.3.201.md",
        ["1.3.201-industrial", "fee_too_high"],
    ),
    (
        "1.3.201",
        "network/p2p_node.py",
        [
            "fee_too_high",
            "p2p_mempool_max_fee_refuse",
            "native_mempool_max_fee_refuse",
        ],
    ),
    (
        "1.3.201",
        "runtime/config.py",
        ["p2p_mempool_max_fee_refuse", "p2p_mempool_max_fee"],
    ),
    (
        "1.3.201",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_fee_refuse",
            "abs_p2p_mempool_fee_high_refuse_total",
        ],
    ),
    (
        "1.3.202",
        "RELEASE_NOTES_v1.3.202.md",
        ["1.3.202-industrial", "value_too_high"],
    ),
    (
        "1.3.202",
        "network/p2p_node.py",
        [
            "value_too_high",
            "p2p_mempool_max_value_refuse",
            "native_mempool_max_value_refuse",
        ],
    ),
    (
        "1.3.202",
        "runtime/config.py",
        ["p2p_mempool_max_value_refuse", "p2p_mempool_max_value"],
    ),
    (
        "1.3.202",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_max_value_refuse",
            "abs_p2p_mempool_value_high_refuse_total",
        ],
    ),
    (
        "1.3.203",
        "RELEASE_NOTES_v1.3.203.md",
        ["1.3.203-industrial", "gas_unparseable"],
    ),
    (
        "1.3.203",
        "network/p2p_node.py",
        [
            "gas_unparseable",
            "p2p_mempool_unparseable_gas_refuse",
            "native_mempool_unparseable_gas_refuse",
        ],
    ),
    (
        "1.3.203",
        "runtime/config.py",
        ["p2p_mempool_unparseable_gas_refuse"],
    ),
    (
        "1.3.203",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_unparseable_gas_refuse",
            "abs_p2p_mempool_gas_unparseable_refuse_total",
        ],
    ),
    (
        "1.3.204",
        "RELEASE_NOTES_v1.3.204.md",
        ["1.3.204-industrial", "value_unparseable"],
    ),
    (
        "1.3.204",
        "network/p2p_node.py",
        [
            "value_unparseable",
            "p2p_mempool_unparseable_value_refuse",
            "native_mempool_unparseable_value_refuse",
        ],
    ),
    (
        "1.3.204",
        "runtime/config.py",
        ["p2p_mempool_unparseable_value_refuse"],
    ),
    (
        "1.3.204",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_unparseable_value_refuse",
            "abs_p2p_mempool_value_unparseable_refuse_total",
        ],
    ),
    (
        "1.3.205",
        "RELEASE_NOTES_v1.3.205.md",
        ["1.3.205-industrial", "nonce_unparseable"],
    ),
    (
        "1.3.205",
        "network/p2p_node.py",
        [
            "nonce_unparseable",
            "p2p_mempool_unparseable_nonce_refuse",
            "native_mempool_unparseable_nonce_refuse",
        ],
    ),
    (
        "1.3.205",
        "runtime/config.py",
        ["p2p_mempool_unparseable_nonce_refuse"],
    ),
    (
        "1.3.205",
        "observability/metrics.py",
        [
            "abs_p2p_native_mempool_unparseable_nonce_refuse",
            "abs_p2p_mempool_nonce_unparseable_refuse_total",
        ],
    ),
    (
        "1.3.206",
        "RELEASE_NOTES_v1.3.206.md",
        ["1.3.206-industrial", "tip-safety", "p2p_dispatch"],
    ),
    (
        "1.3.206",
        "runtime/config.py",
        ["tip_safety_enforce", "1.3.206-industrial"],
    ),
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def check_needles() -> list[str]:
    errors: list[str] = []
    for wave, rel, needles in NEEDLES:
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"[{wave}] missing file: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                errors.append(f"[{wave}] {rel}: missing {needle!r}")
    return errors


def check_version() -> list[str]:
    errors: list[str] = []
    try:
        from runtime.config import Config

        ver = str(Config().node_version)
        if not ver.startswith("1.3.206"):
            errors.append(f"node_version expected 1.3.206-*, got {ver}")
    except Exception as exc:
        errors.append(f"config import failed: {exc}")
    return errors


def run_pytest(tests: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", *tests, "-q", "--tb=line"]
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT) + (
        __import__("os").pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return int(proc.returncode), out


def run_industrial_gate() -> tuple[int, str]:
    cmd = [sys.executable, str(ROOT / "scripts" / "industrial_gate.py")]
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT) + (
        __import__("os").pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return int(proc.returncode), out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-gate", action="store_true", help="Skip industrial_gate.py")
    ap.add_argument("--skip-pytest", action="store_true", help="Skip unit tests")
    ap.add_argument(
        "--json",
        default=str(ROOT / "data" / "verify_industrial_waves.json"),
        help="Write JSON report path",
    )
    args = ap.parse_args()

    started = time.time()
    report: dict = {
        "ok": False,
        "node_version": None,
        "needles_ok": False,
        "pytest_rc": None,
        "gate_rc": None,
        "errors": [],
        "warnings": [
            "green ≠ public mainnet",
            "ceremony pin / external audit remain org blockers",
            "keep bridge OFF on live mesh",
        ],
        "elapsed_sec": 0.0,
    }

    print("=== [1/4] Version ===")
    ver_errs = check_version()
    report["errors"].extend(ver_errs)
    try:
        from runtime.config import Config

        report["node_version"] = Config().node_version
        print(f"  node_version={report['node_version']}")
    except Exception as exc:
        print(f"  FAIL: {exc}")

    print("=== [2/4] Static needles (waves 1.3.65–1.3.68) ===")
    needle_errs = check_needles()
    report["errors"].extend(needle_errs)
    report["needles_ok"] = not needle_errs
    if needle_errs:
        for e in needle_errs:
            print(f"  FAIL: {e}")
    else:
        print(f"  OK: {len(NEEDLES)} file checks passed")

    if not args.skip_pytest:
        print("=== [3/4] Unit tests ===")
        missing = [t for t in WAVE_TESTS if not (ROOT / t).is_file()]
        if missing:
            for m in missing:
                report["errors"].append(f"missing test file: {m}")
                print(f"  FAIL: missing {m}")
        rc, out = run_pytest([t for t in WAVE_TESTS if (ROOT / t).is_file()])
        report["pytest_rc"] = rc
        if rc != 0:
            report["errors"].append("pytest failed")
            print(out[-2000:] if len(out) > 2000 else out)
            print(f"  FAIL: pytest rc={rc}")
        else:
            # last non-empty line often has passed count
            tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
            for ln in tail:
                print(f"  {ln}")
            print(f"  OK: pytest rc=0")
    else:
        print("=== [3/4] Unit tests SKIPPED ===")

    if not args.skip_gate:
        print("=== [4/4] industrial_gate ===")
        rc, out = run_industrial_gate()
        report["gate_rc"] = rc
        # Show last summary lines
        lines = [ln for ln in out.splitlines() if ln.strip()]
        for ln in lines[-12:]:
            print(f"  {ln}")
        if rc != 0:
            report["errors"].append("industrial_gate failed")
            print(f"  FAIL: gate rc={rc}")
        else:
            print("  OK: industrial_gate")
    else:
        print("=== [4/4] industrial_gate SKIPPED ===")

    report["elapsed_sec"] = round(time.time() - started, 3)
    report["ok"] = len(report["errors"]) == 0 and (
        args.skip_pytest or report["pytest_rc"] == 0
    ) and (args.skip_gate or report["gate_rc"] == 0)

    out_path = Path(args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    if report["ok"]:
        print(f"PASS: industrial waves verify OK ({report['elapsed_sec']}s)")
        print(f"  report: {out_path}")
        return 0
    print(f"FAIL: {len(report['errors'])} error(s) ({report['elapsed_sec']}s)")
    for e in report["errors"]:
        print(f"  - {e}")
    print(f"  report: {out_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
