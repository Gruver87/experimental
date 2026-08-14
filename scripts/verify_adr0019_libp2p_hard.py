#!/usr/bin/env python3
"""HARD local gate for ADR 0019 rust-libp2p (Experimental only).

Fail-closed checklist (exit 1 on first FAIL unless --keep-going):

  1) repo / honesty markers
  2) cargo fmt --check (abs_native)
  3) cargo test --no-default-features --features auto-initialize,libp2p --lib
     (scripts/cargo_test_abs_native.py — real CPython link; not extension-module)
  4) cargo audit (native lockfile; uses .cargo/audit.toml)
  5) abs_native libp2p deep capability (protocols + block_peer + metrics keys)
  6) industrial freeze: prod JSON feature_libp2p=false + Config prod OFF
  7) bridge OFF audit gate
  8) pytest unit suite (libp2p + dual_stack + prod freeze)
  9) all Slice A–J labs (must print OK:/PASS)
 10) optional --rebuild (maturin + pip install)
 11) optional --evidence pack

Usage (from Experimental repo root):
  python scripts/verify_adr0019_libp2p_hard.py
  python scripts/verify_adr0019_libp2p_hard.py --keep-going
  python scripts/verify_adr0019_libp2p_hard.py --rebuild
  python scripts/verify_adr0019_libp2p_hard.py --evidence
  powershell -ExecutionPolicy Bypass -File scripts\\verify_adr0019_libp2p_hard.ps1

Honesty: PASS here ≠ tip proof ≠ prod libp2p mesh. TCP+TLS remains default.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "abs_native"

REQUIRED_METRIC_KEYS = (
    "libp2p_peers",
    "libp2p_dial_ok",
    "libp2p_dial_fail",
    "libp2p_dial_fail_transport",
    "libp2p_dial_fail_wrong_peer_id",
    "libp2p_dial_fail_no_addresses",
    "libp2p_dial_fail_aborted",
    "libp2p_dial_fail_local_peer_id",
    "libp2p_dial_fail_condition",
    "libp2p_dial_fail_denied",
    "libp2p_dial_fail_denied_block",
    "libp2p_dial_fail_denied_allow",
    "libp2p_dial_fail_denied_limit",
    "libp2p_dialing",
    "libp2p_incoming_connection_error",
    "libp2p_incoming_fail_transport",
    "libp2p_incoming_fail_wrong_peer_id",
    "libp2p_incoming_fail_aborted",
    "libp2p_incoming_fail_local_peer_id",
    "libp2p_incoming_fail_denied",
    "libp2p_incoming_fail_denied_block",
    "libp2p_incoming_fail_denied_allow",
    "libp2p_incoming_fail_denied_limit",
    "libp2p_peer_external_addr",
    "libp2p_wire_sent",
    "libp2p_wire_recv",
    "libp2p_wire_outbound_failure",
    "libp2p_wire_outbound_fail_dial",
    "libp2p_wire_outbound_fail_timeout",
    "libp2p_wire_outbound_fail_connection_closed",
    "libp2p_wire_outbound_fail_unsupported",
    "libp2p_wire_outbound_fail_io",
    "libp2p_wire_inbound_failure",
    "libp2p_wire_inbound_fail_timeout",
    "libp2p_wire_inbound_fail_connection_closed",
    "libp2p_wire_inbound_fail_unsupported",
    "libp2p_wire_inbound_fail_response_omission",
    "libp2p_wire_inbound_fail_io",
    "libp2p_wire_response_sent",
    "libp2p_wire_response_ok",
    "libp2p_inbound_established",
    "libp2p_incoming_connections",
    "libp2p_connection_closed",
    "libp2p_connection_closed_local",
    "libp2p_connection_closed_io",
    "libp2p_connection_closed_keep_alive",
    "libp2p_established_in_ms_last",
    "libp2p_established_in_ms_max",
    "libp2p_new_listen_addr",
    "libp2p_expired_listen_addr",
    "libp2p_listener_closed",
    "libp2p_listener_error",
    "libp2p_bytes_in",
    "libp2p_bytes_out",
    "libp2p_external_addrs",
    "libp2p_external_addr_confirmed",
    "libp2p_external_addr_expired",
    "libp2p_external_addr_cleared",
    "libp2p_external_addr_loaded",
    "libp2p_external_addr_persisted",
    "libp2p_max_advertised_external",
    "libp2p_listen_derived_externals",
    "libp2p_aux_advertised_externals",
    "libp2p_advertised_externals_used",
    "libp2p_external_addr_limit_refused",
    "libp2p_external_addr_candidates",
    "libp2p_dial_refused_budget",
    "libp2p_gossip_pub",
    "libp2p_gossip_recv",
    "libp2p_mdns_discovered",
    "libp2p_mdns_expired",
    "libp2p_mdns_listen_addr_omitted",
    "libp2p_mdns_advertised_listen",
    "libp2p_mdns_ttl_secs",
    "libp2p_kad_peers",
    "libp2p_kad_listen_addr_omitted",
    "libp2p_kad_advertised_listen",
    "libp2p_kad_queries",
    "libp2p_kad_query_ok",
    "libp2p_kad_query_fail",
    "libp2p_kad_inbound_requests",
    "libp2p_kad_unroutable_peer",
    "libp2p_kad_routable_peer",
    "libp2p_kad_pending_routable_peer",
    "libp2p_kad_mode_changed",
    "libp2p_relay_reservations",
    "libp2p_relay_circuits",
    "libp2p_relay_reservation_denied",
    "libp2p_relay_reservation_timed_out",
    "libp2p_relay_circuit_denied",
    "libp2p_relay_circuit_closed",
    "libp2p_relay_inbound_circuit",
    "libp2p_relay_outbound_circuit",
    "libp2p_relay_max_reservations",
    "libp2p_conn_limit_denied",
    "libp2p_block_denied",
    "libp2p_blocked_peers",
    "libp2p_allow_denied",
    "libp2p_allowed_peers",
    "libp2p_identify_peers",
    "libp2p_identify_received",
    "libp2p_identify_listen_addr_omitted",
    "libp2p_identify_candidate_omitted",
    "libp2p_identify_sent",
    "libp2p_identify_pushed",
    "libp2p_identify_error",
    "libp2p_abs_wire_v1_sent",
    "libp2p_abs_wire_v2_sent",
    "libp2p_abs_wire_v1_recv",
    "libp2p_abs_wire_v2_recv",
    "libp2p_autonat_probes",
    "libp2p_autonat_listen_addr_omitted",
    "libp2p_autonat_advertised_listen",
    "libp2p_autonat_status_changes",
    "libp2p_autonat_inbound_probe",
    "libp2p_autonat_outbound_probe",
    "libp2p_autonat_inbound_probe_error",
    "libp2p_autonat_outbound_probe_error",
    "libp2p_dcutr_upgrade_success",
    "libp2p_dcutr_upgrade_fail",
    "libp2p_dcutr_candidate_omitted",
    "libp2p_dcutr_advertised_candidates",
    "libp2p_bootstrap_peers",
    "libp2p_bootstrap_dials_ok",
    "libp2p_bootstrap_dials_fail",
    "libp2p_bootstrap_dials_timeout",
    "libp2p_bootstrap_dials_attempted",
    "libp2p_bootstrap_removed",
    "libp2p_bootstrap_cleared",
    "libp2p_reconnect_scheduled",
    "libp2p_reconnect_ok",
    "libp2p_reconnect_fail",
    "libp2p_reconnect_give_up",
    "libp2p_gossip_validation_accept",
    "libp2p_gossip_validation_reject",
    "libp2p_gossip_validation_ignore",
    "libp2p_gossip_validation_pending",
    "libp2p_gossip_defer_validation",
    "libp2p_wire_omit_response",
    "libp2p_identify_push",
    "libp2p_identify_push_requests",
    "libp2p_identify_error_timeout",
    "libp2p_identify_error_negotiation",
    "libp2p_identify_error_apply",
    "libp2p_identify_error_io",
    "libp2p_identify_interval_ms",
    "libp2p_last_observed_addr",
    "libp2p_observed_addr_updates",
    "libp2p_observed_addr_confirmed",
    "libp2p_observed_addr_cleared",
    "libp2p_confirm_observed_addr",
    "libp2p_agent_version",
    "libp2p_protocol_version",
    "libp2p_last_gossip_message_id",
    "libp2p_last_gossip_propagation_peer",
    "libp2p_gossip_app_score_sets",
    "libp2p_gossip_not_supported",
    "libp2p_gossip_peer_subscribed",
    "libp2p_gossip_peer_unsubscribed",
    "libp2p_gossip_peer_score",
    "libp2p_ping_ok",
    "libp2p_ping_fail",
    "libp2p_ping_fail_timeout",
    "libp2p_ping_fail_unsupported",
    "libp2p_ping_fail_other",
    "libp2p_ping_interval_ms",
    "libp2p_ping_timeout_ms",
    "libp2p_ping_rtt_ms_last",
    "libp2p_ping_rtt_ms_max",
    "libp2p_ping_unhealthy_disconnects",
    "libp2p_ping_unhealthy_disconnect",
    "libp2p_ping_max_fails",
    "libp2p_ping_max_rtt_ms",
    "libp2p_score_autoblock",
    "libp2p_score_graylist_threshold",
    "libp2p_score_autoblocks",
    "libp2p_score_sweep_ticks",
    "libp2p_peerstore_peers",
    "libp2p_peerstore_learned",
    "libp2p_peerstore_removed",
    "libp2p_peerstore_cleared",
    "libp2p_peerstore_allow_learn",
    "libp2p_peerstore_dials_ok",
    "libp2p_peerstore_dials_fail",
    "libp2p_peerstore_dials_timeout",
    "libp2p_peerstore_dials_attempted",
    "libp2p_reconnect_from_peerstore",
    "libp2p_idle_connection_timeout_secs",
    "libp2p_idle_timeout_closes",
    "libp2p_ipv6_listens",
    "libp2p_ipv6_dial_ok",
    "libp2p_rendezvous_registers",
    "libp2p_rendezvous_register_fail",
    "libp2p_rendezvous_discovers",
    "libp2p_rendezvous_discovered_peers",
    "libp2p_rendezvous_discover_fail",
    "libp2p_rendezvous_server_registrations",
    "libp2p_rendezvous_server_unregistrations",
    "libp2p_rendezvous_server_discover_served",
    "libp2p_rendezvous_server_discover_not_served",
    "libp2p_rendezvous_server_not_registered",
    "libp2p_rendezvous_server_registration_expired",
    "libp2p_rendezvous_expired",
    "libp2p_dns_dial_ok",
    "libp2p_dns_dial_fail",
    "libp2p_connection_limits_updates",
    "libp2p_quic_listens",
    "libp2p_quic_dial_ok",
    "libp2p_quic_dial_fail",
    "libp2p_ws_listens",
    "libp2p_ws_dial_ok",
    "libp2p_ws_dial_fail",
    "libp2p_upnp_external_addrs",
    "libp2p_upnp_listen_addr_omitted",
    "libp2p_upnp_advertised_listen",
    "libp2p_upnp_expired_external_addrs",
    "libp2p_upnp_gateway_not_found",
    "libp2p_upnp_non_routable_gateway",
)

UNIT_TESTS = [
    "tests/unit/test_libp2p_adapter.py",
    "tests/unit/test_libp2p_wire_bridge.py",
    "tests/unit/test_libp2p_status_metrics.py",
    "tests/unit/test_libp2p_prometheus_export.py",
    "tests/unit/test_libp2p_swarm_lab.py",
    "tests/unit/test_dual_stack.py",
    "tests/unit/test_prod_mesh_feature_freeze.py",
    "tests/unit/test_cargo_test_abs_native.py",
    "tests/unit/test_package_libp2p_evidence.py",
]

LABS = [
    ("A", "scripts/libp2p_rust_two_node_lab.py"),
    ("B", "scripts/libp2p_rust_wire_lab.py"),
    ("B", "scripts/libp2p_rust_three_node_lab.py"),
    ("C", "scripts/libp2p_rust_soak_lab.py"),
    ("D", "scripts/libp2p_mixed_dual_stack_lab.py"),
    ("E", "scripts/libp2p_rust_gossip_lab.py"),
    ("F", "scripts/libp2p_rust_identity_mdns_lab.py"),
    ("G", "scripts/libp2p_rust_kad_lab.py"),
    ("G", "scripts/libp2p_rust_abs_announce_lab.py"),
    ("H", "scripts/libp2p_rust_relay_limits_lab.py"),
    ("I", "scripts/libp2p_rust_blocklist_lab.py"),
    ("J", "scripts/libp2p_rust_status_surface_lab.py"),
    ("K", "scripts/libp2p_rust_mdns_toggle_lab.py"),
    ("L", "scripts/libp2p_rust_wire_timeout_lab.py"),
    ("M", "scripts/libp2p_rust_abs_wire_lab.py"),
    ("N", "scripts/libp2p_rust_autonat_dcutr_lab.py"),
    ("O", "scripts/libp2p_rust_bootstrap_lab.py"),
    ("P", "scripts/libp2p_rust_reconnect_lab.py"),
    ("Q", "scripts/libp2p_rust_peer_score_lab.py"),
    ("R", "scripts/libp2p_rust_ping_lab.py"),
    ("S", "scripts/libp2p_rust_score_autoblock_lab.py"),
    ("T", "scripts/libp2p_rust_peerstore_lab.py"),
    ("U", "scripts/libp2p_rust_peerstore_reconnect_lab.py"),
    ("V", "scripts/libp2p_rust_idle_timeout_lab.py"),
    ("W", "scripts/libp2p_rust_ipv6_lab.py"),
    ("X", "scripts/libp2p_rust_rendezvous_lab.py"),
    ("Y", "scripts/libp2p_rust_dns_lab.py"),
    ("Z", "scripts/libp2p_rust_prometheus_lab.py"),
    ("AA", "scripts/libp2p_rust_connection_manager_lab.py"),
    ("AB", "scripts/libp2p_rust_quic_lab.py"),
    ("AC", "scripts/libp2p_rust_websocket_lab.py"),
    ("AD", "scripts/libp2p_rust_upnp_lab.py"),
    ("AE", "scripts/libp2p_rust_allowlist_lab.py"),
    ("AF", "scripts/libp2p_rust_bandwidth_lab.py"),
    ("AG", "scripts/libp2p_rust_external_addr_lab.py"),
    ("AH", "scripts/libp2p_rust_connection_lifecycle_lab.py"),
    ("AI", "scripts/libp2p_rust_connection_close_cause_lab.py"),
    ("AJ", "scripts/libp2p_rust_listener_lifecycle_lab.py"),
    ("AK", "scripts/libp2p_rust_connection_attempt_lab.py"),
    ("AL", "scripts/libp2p_rust_identify_events_lab.py"),
    ("AM", "scripts/libp2p_rust_gossip_subscription_lab.py"),
    ("AN", "scripts/libp2p_rust_kad_events_lab.py"),
    ("AO", "scripts/libp2p_rust_wire_rr_events_lab.py"),
    ("AP", "scripts/libp2p_rust_relay_events_lab.py"),
    ("AQ", "scripts/libp2p_rust_rendezvous_events_lab.py"),
    ("AR", "scripts/libp2p_rust_autonat_events_lab.py"),
    ("AS", "scripts/libp2p_rust_mdns_events_lab.py"),
    ("AT", "scripts/libp2p_rust_relay_client_events_lab.py"),
    ("AU", "scripts/libp2p_rust_dial_fail_events_lab.py"),
    ("AV", "scripts/libp2p_rust_incoming_fail_events_lab.py"),
    ("AW", "scripts/libp2p_rust_dial_deny_events_lab.py"),
    ("AX", "scripts/libp2p_rust_deny_cause_events_lab.py"),
    ("AY", "scripts/libp2p_rust_ping_fail_events_lab.py"),
    ("AZ", "scripts/libp2p_rust_wire_fail_events_lab.py"),
    ("BA", "scripts/libp2p_rust_gossip_validation_lab.py"),
    ("BB", "scripts/libp2p_rust_wire_omit_response_lab.py"),
    ("BC", "scripts/libp2p_rust_identify_push_lab.py"),
    ("BD", "scripts/libp2p_rust_identify_interval_lab.py"),
    ("BE", "scripts/libp2p_rust_peerstore_remove_lab.py"),
    ("BF", "scripts/libp2p_rust_peerstore_allow_learn_lab.py"),
    ("BG", "scripts/libp2p_rust_identify_observed_addr_lab.py"),
    ("BH", "scripts/libp2p_rust_bootstrap_remove_lab.py"),
    ("BI", "scripts/libp2p_rust_confirm_observed_addr_auto_lab.py"),
    ("BJ", "scripts/libp2p_rust_bootstrap_clear_lab.py"),
    ("BK", "scripts/libp2p_rust_peerstore_clear_lab.py"),
    ("BL", "scripts/libp2p_rust_clear_observed_addr_lab.py"),
    ("BM", "scripts/libp2p_rust_clear_external_addrs_lab.py"),
    ("BN", "scripts/libp2p_rust_remove_external_addr_lab.py"),
    ("BO", "scripts/libp2p_rust_add_external_addr_lab.py"),
    ("BP", "scripts/libp2p_rust_external_addrs_persist_lab.py"),
    ("BQ", "scripts/libp2p_rust_external_addrs_atomic_persist_lab.py"),
    ("BR", "scripts/libp2p_rust_external_addrs_max_lab.py"),
    ("BS", "scripts/libp2p_rust_listen_derived_external_max_lab.py"),
    ("BT", "scripts/libp2p_rust_advertised_externals_shared_max_lab.py"),
    ("BU", "scripts/libp2p_rust_advertised_externals_all_paths_max_lab.py"),
    ("BV", "scripts/libp2p_rust_identify_listen_addrs_capped_lab.py"),
    ("BW", "scripts/libp2p_rust_mdns_listen_addrs_capped_lab.py"),
    ("BX", "scripts/libp2p_rust_kad_listen_addrs_capped_lab.py"),
    ("BY", "scripts/libp2p_rust_autonat_listen_addrs_capped_lab.py"),
    ("BZ", "scripts/libp2p_rust_upnp_listen_addrs_capped_lab.py"),
    ("CA", "scripts/libp2p_rust_advertised_externals_libp2p_book_max_lab.py"),
    ("CB", "scripts/libp2p_rust_dcutr_candidates_capped_lab.py"),
    ("CC", "scripts/libp2p_rust_identify_candidates_capped_lab.py"),
    ("CD", "scripts/libp2p_rust_external_addrs_replace_no_unlink_lab.py"),
    ("CE", "scripts/libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py"),
    ("CF", "scripts/libp2p_rust_identity_atomic_persist_lab.py"),
    ("CG", "scripts/libp2p_rust_persist_parent_dir_fsync_lab.py"),
    ("CH", "scripts/libp2p_rust_identity_key_mode_lab.py"),
    ("CI", "scripts/libp2p_rust_identity_key_windows_dacl_lab.py"),
    ("CJ", "scripts/libp2p_rust_persist_mkdir_fsync_lab.py"),
    ("CK", "scripts/libp2p_rust_identity_create_exclusive_lab.py"),
    ("CL", "scripts/libp2p_rust_identity_tmp_dacl_at_create_lab.py"),
    ("CM", "scripts/libp2p_rust_identity_existing_acl_refuse_lab.py"),
    ("CN", "scripts/libp2p_rust_identity_null_dacl_refuse_lab.py"),
    ("CO", "scripts/libp2p_rust_identity_callback_ace_refuse_lab.py"),
    ("CP", "scripts/libp2p_rust_identity_protected_dacl_refuse_lab.py"),
]

PROD_JSONS = (
    "docker/node.prod.json",
    "docker/node.prod.mesh1.json",
    "docker/node.prod.mesh2.json",
    "docker/node.prod.mesh3.json",
)


def _print(text: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
    sys.stdout.flush()


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 300,
    env: dict[str, str] | None = None,
) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return False, float(timeout), f"TIMEOUT: {exc}"
    except OSError as exc:
        return False, 0.0, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, time.perf_counter() - t0, out


def _tail(out: str, n: int = 1200) -> str:
    out = (out or "").strip()
    return out[-n:] if len(out) > n else out


class HardGate:
    def __init__(self, *, keep_going: bool, quiet: bool) -> None:
        self.keep_going = keep_going
        self.quiet = quiet
        self.rows: list[tuple[str, bool, float, str]] = []

    def step(self, name: str, fn: Callable[[], tuple[bool, str]], *, elapsed: float = 0.0) -> bool:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"exception: {exc}"
        self.rows.append((name, ok, elapsed, detail))
        _print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        if not ok and not self.keep_going:
            return False
        return True

    def step_cmd(
        self,
        name: str,
        cmd: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300,
        env: dict[str, str] | None = None,
        require_substr: str | None = None,
    ) -> bool:
        ok, elapsed, out = _run(cmd, cwd=cwd, timeout=timeout, env=env)
        detail = ""
        for ln in (out or "").splitlines()[::-1]:
            if ln.strip():
                detail = ln.strip()
                break
        if ok and require_substr and require_substr not in (out or ""):
            ok = False
            detail = f"missing required text {require_substr!r}"
        self.rows.append((name, ok, elapsed, detail))
        _print(f"[{'PASS' if ok else 'FAIL'}] {name} ({elapsed:.1f}s) {detail}")
        if not ok and not self.quiet:
            _print(_tail(out))
        if not ok and not self.keep_going:
            return False
        return True


def check_repo_honesty() -> tuple[bool, str]:
    adr = ROOT / "docs" / "adr" / "0019-rust-libp2p-industrial.md"
    if not adr.is_file():
        return False, "missing ADR 0019"
    text = adr.read_text(encoding="utf-8", errors="replace")
    need = (
        "TCP+TLS",
        "tip proof",
        "Gruver87/experimental",
        "Slice U",
        "Slice V",
        "Slice W",
        "Slice X",
        "Slice Y",
        "Slice Z",
        "Slice AA",
        "Slice AB",
        "Slice AC",
        "Slice AD",
        "Slice AE",
        "Slice AF",
        "Slice AG",
        "Slice AH",
        "Slice BS",
        "Slice BT",
        "Slice BU",
        "Slice BV",
        "Slice BW",
        "Slice BX",
        "Slice BY",
        "Slice BZ",
        "Slice CA",
        "Slice CB",
        "Slice CC",
        "FEATURE_LIBP2P",
        "## Honesty",
    )
    missing = [m for m in need if m not in text]
    if "experimental" not in text.lower():
        missing.append("experimental")
    if missing:
        return False, f"ADR honesty markers missing: {missing}"
    # Refuse running from Ultimate Hybrid audit pin by path heuristic
    root_name = ROOT.name.lower()
    if "ultimate_hybrid" in root_name and "experimental" not in root_name:
        return False, f"refusing audit-pin tree: {ROOT}"
    return True, f"repo={ROOT.name}"


def check_native_deep() -> tuple[bool, str]:
    try:
        import abs_native  # type: ignore
    except Exception as exc:
        return False, f"import failed: {exc}"
    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        return False, "libp2p_available() False — rebuild with maturin --features libp2p"
    wire = str(getattr(abs_native, "ABS_WIRE_PROTOCOL", ""))
    gossip = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", ""))
    kad = str(getattr(abs_native, "ABS_KAD_PROTOCOL", ""))
    if wire != "/abs/wire/1.0.0":
        return False, f"bad ABS_WIRE_PROTOCOL={wire!r}"
    if gossip != "abs/blocks/1.0.0":
        return False, f"bad ABS_GOSSIP_BLOCKS_TOPIC={gossip!r}"
    if kad != "/absolute/kad/1.0.0":
        return False, f"bad ABS_KAD_PROTOCOL={kad!r}"

    a = abs_native.libp2p_node_new()
    b = abs_native.libp2p_node_new()
    try:
        addrs = a.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs:
            return False, "listen returned empty"
        remote = b.dial(addrs[0])
        if not remote:
            return False, "dial returned empty peer id"
        time.sleep(0.25)
        m = dict(b.metrics())
        missing = [k for k in REQUIRED_METRIC_KEYS if k not in m]
        if missing:
            native_path = getattr(abs_native, "__file__", "?")
            return False, (
                f"metrics missing keys: {missing} "
                f"(installed {native_path}; stale wheel vs this script — "
                "run: python scripts/verify_adr0019_libp2p_hard.py --rebuild)"
            )
        cap = dict(a.capability_status())
        if cap.get("default_mesh") is not False:
            return False, "capability_status.default_mesh must be False"
        if int(cap.get("phase") or 0) < 8:
            return False, f"capability phase too low: {cap.get('phase')}"
        if not cap.get("external_addrs_replace_no_unlink"):
            return False, (
                "capability external_addrs_replace_no_unlink missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("bootstrap_peerstore_atomic_persist"):
            return False, (
                "capability bootstrap_peerstore_atomic_persist missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("identity_atomic_persist"):
            return False, (
                "capability identity_atomic_persist missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("persist_parent_dir_fsync"):
            return False, (
                "capability persist_parent_dir_fsync missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("identity_key_mode_restrict"):
            return False, (
                "capability identity_key_mode_restrict missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        want_strategy = (
            "windows_movefileex_replace" if os.name == "nt" else "posix_rename"
        )
        got_strategy = cap.get("external_addrs_replace_strategy")
        if got_strategy != want_strategy:
            return False, (
                f"replace strategy {got_strategy!r} != {want_strategy} "
                "(stale wheel — --rebuild)"
            )
        want_dir = (
            "windows_dir_flushfilebuffers"
            if os.name == "nt"
            else "posix_dir_fsync"
        )
        got_dir = cap.get("persist_parent_dir_fsync_strategy")
        if got_dir != want_dir:
            return False, (
                f"parent-dir fsync strategy {got_dir!r} != {want_dir} "
                "(stale wheel — --rebuild)"
            )
        want_key = "unix_0600" if os.name != "nt" else "windows_owner_only_dacl"
        got_key = cap.get("identity_key_mode_strategy")
        if got_key != want_key:
            return False, (
                f"identity key mode strategy {got_key!r} != {want_key} "
                "(stale wheel — --rebuild)"
            )
        if os.name == "nt" and not cap.get("identity_key_windows_owner_dacl"):
            return False, (
                "capability identity_key_windows_owner_dacl missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("persist_mkdir_fsync"):
            return False, (
                "capability persist_mkdir_fsync missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if not cap.get("identity_create_exclusive"):
            return False, (
                "capability identity_create_exclusive missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        want_excl = (
            "windows_movefileex_noreplace"
            if os.name == "nt"
            else "posix_hardlink_exclusive"
        )
        got_excl = cap.get("identity_create_exclusive_strategy")
        if got_excl != want_excl:
            return False, (
                f"identity exclusive strategy {got_excl!r} != {want_excl} "
                "(stale wheel — --rebuild)"
            )
        if not cap.get("identity_key_tmp_restrict_at_create"):
            return False, (
                "capability identity_key_tmp_restrict_at_create missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        want_tmp = (
            "windows_createfile_owner_dacl"
            if os.name == "nt"
            else "unix_0600_at_create"
        )
        got_tmp = cap.get("identity_key_tmp_restrict_strategy")
        if got_tmp != want_tmp:
            return False, (
                f"identity tmp restrict strategy {got_tmp!r} != {want_tmp} "
                "(stale wheel — --rebuild)"
            )
        if not cap.get("identity_key_existing_acl_refuse"):
            return False, (
                "capability identity_key_existing_acl_refuse missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if os.name == "nt" and not cap.get("identity_key_null_dacl_refuse"):
            return False, (
                "capability identity_key_null_dacl_refuse missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if os.name == "nt" and not cap.get("identity_key_callback_ace_refuse"):
            return False, (
                "capability identity_key_callback_ace_refuse missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        if os.name == "nt" and not cap.get("identity_key_protected_dacl_refuse"):
            return False, (
                "capability identity_key_protected_dacl_refuse missing "
                "(stale wheel — run verify_adr0019_libp2p_hard.py --rebuild)"
            )
        # Slice I API must exist
        a.block_peer(b.peer_id)
        if b.peer_id not in list(a.blocked_peers()):
            return False, "block_peer did not stick"
        a.unblock_peer(b.peer_id)
        if b.peer_id in list(a.blocked_peers()):
            return False, "unblock_peer failed"
        # honesty string
        if "ADR0019" not in str(cap.get("honesty", "")):
            return False, "capability honesty marker missing"
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass
    return True, f"wire={wire} kad={kad} phase_ok metrics={len(REQUIRED_METRIC_KEYS)}"


def check_industrial_freeze() -> tuple[bool, str]:
    bad: list[str] = []
    for rel in PROD_JSONS:
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"missing {rel}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if bool(data.get("feature_libp2p", False)):
            bad.append(f"{path.name}: feature_libp2p true")
        if bool(data.get("feature_long_range", False)):
            bad.append(f"{path.name}: feature_long_range true")
    # Config prod path
    env = os.environ.copy()
    env["DEPLOYMENT_MODE"] = "prod"
    env["FEATURE_LIBP2P"] = "true"
    env["FEATURE_LONG_RANGE"] = "true"
    code = (
        "from runtime.config import Config\n"
        "c=Config(); c.deployment_mode='prod'; c.apply_env()\n"
        "assert c.feature_libp2p is False\n"
        "assert c.feature_long_range is False\n"
        "print('prod_freeze_ok')\n"
    )
    ok, _, out = _run([sys.executable, "-c", code], env=env, timeout=60)
    if not ok or "prod_freeze_ok" not in out:
        bad.append("Config prod freeze failed")
    if bad:
        return False, "; ".join(bad)
    return True, "prod JSON + Config freeze OK"


def do_rebuild() -> tuple[bool, str]:
    ok, elapsed, out = _run(
        [
            "maturin",
            "build",
            "--release",
            "--features",
            "pyo3/extension-module,libp2p",
        ],
        cwd=NATIVE,
        timeout=900,
    )
    if not ok:
        return False, f"maturin failed ({elapsed:.0f}s): {_tail(out, 400)}"
    candidates: list[Path] = []
    candidates.extend(NATIVE.joinpath("target", "wheels").glob("abs_native-*.whl"))
    cargo_target = str(os.environ.get("CARGO_TARGET_DIR", "") or "").strip()
    if cargo_target:
        candidates.extend(Path(cargo_target).joinpath("wheels").glob("abs_native-*.whl"))
    if not candidates:
        candidates.extend(ROOT.rglob("abs_native-*.whl"))
    wheels = sorted(
        {p.resolve() for p in candidates if p.is_file()},
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not wheels:
        return False, "no wheel found after maturin build"
    whl = wheels[0]
    ok2, _, out2 = _run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(whl)],
        timeout=120,
    )
    if not ok2:
        return False, f"pip install failed: {_tail(out2, 400)}"
    return True, f"installed {whl}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep-going", action="store_true", help="run all steps even after FAIL")
    ap.add_argument("--rebuild", action="store_true", help="maturin build + pip install first")
    ap.add_argument("--evidence", action="store_true", help="package evidence after green path")
    ap.add_argument("--skip-cargo", action="store_true", help="skip fmt/test/audit (not hard)")
    ap.add_argument("--skip-labs", action="store_true")
    ap.add_argument("--skip-units", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    g = HardGate(keep_going=args.keep_going, quiet=args.quiet)
    _print("=== ADR 0019 HARD VERIFY (Experimental) ===")
    _print(f"root: {ROOT}")
    _print("fail-closed: any FAIL => exit 1 (unless --keep-going)")
    _print("honesty: not tip proof / not prod libp2p mesh")

    if not g.step("repo_honesty", check_repo_honesty):
        return 1

    if args.rebuild:
        if not g.step("rebuild_wheel", do_rebuild):
            return 1

    if not args.skip_cargo:
        if not g.step_cmd(
            "cargo_fmt",
            ["cargo", "fmt", "--manifest-path", str(NATIVE / "Cargo.toml"), "--all", "--", "--check"],
            timeout=120,
        ):
            return 1
        if not g.step_cmd(
            "cargo_test_libp2p",
            [
                sys.executable,
                str(ROOT / "scripts" / "cargo_test_abs_native.py"),
                "--features",
                "libp2p",
                "--",
                "--lib",
            ],
            timeout=600,
        ):
            return 1
        # audit: prefer project config; also pass known ignores for CI parity
        audit_cmd = [
            "cargo",
            "audit",
            "--file",
            str(NATIVE / "Cargo.lock"),
        ]
        if not g.step_cmd("cargo_audit", audit_cmd, timeout=180):
            # cargo-audit may be missing
            if "no such command" in (g.rows[-1][3] or "").lower() or "audit" in g.rows[-1][3]:
                _print("HINT: cargo install cargo-audit --locked")
            return 1

    if not g.step("native_libp2p_deep", check_native_deep):
        return 1

    if not g.step("industrial_freeze", check_industrial_freeze):
        return 1

    if not g.step_cmd(
        "bridge_off_gate",
        [sys.executable, str(ROOT / "scripts" / "bridge_off_audit_gate.py")],
        timeout=60,
    ):
        return 1

    if not args.skip_units:
        if not g.step_cmd(
            "unit_tests",
            [sys.executable, "-m", "pytest", "-q", *UNIT_TESTS],
            timeout=300,
        ):
            return 1

    if not args.skip_labs:
        for slice_id, rel in LABS:
            label = f"lab_{slice_id}:{Path(rel).stem}"
            ok = g.step_cmd(
                label,
                [sys.executable, str(ROOT / rel)],
                timeout=180,
                require_substr="PASS",
            )
            if not ok:
                return 1

    if args.evidence:
        # only if everything so far passed
        if all(ok for _, ok, _, _ in g.rows):
            if not g.step_cmd(
                "evidence_pack",
                [sys.executable, str(ROOT / "scripts" / "package_libp2p_evidence.py")],
                timeout=600,
            ):
                return 1
        else:
            g.rows.append(("evidence_pack", False, 0.0, "skipped: prior FAIL"))
            _print("[FAIL] evidence_pack — skipped: prior FAIL")

    passed = sum(1 for _, ok, _, _ in g.rows if ok)
    failed = sum(1 for _, ok, _, _ in g.rows if not ok)
    _print("---")
    _print(f"HARD summary: {passed} PASS, {failed} FAIL / {len(g.rows)} steps")
    if failed:
        _print("FAILED steps:")
        for name, ok, _, detail in g.rows:
            if not ok:
                _print(f"  - {name}: {detail}")
    _print("honesty: lab/R&D only — TCP+TLS remains default industrial mesh")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
