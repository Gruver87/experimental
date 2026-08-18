#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prometheus-совместимые метрики узла."""

import threading
import time
from typing import Any, Optional

# Cumulative histogram buckets for GET /status (ms). 2000ms is soak_preflight fail-closed.
_STATUS_MS_BUCKETS = (50, 100, 200, 500, 1000, 2000, 5000, 15000)


class MetricsCollector:
    """Сбор метрик для GET /metrics (text/plain Prometheus format)."""

    def __init__(self):
        self.start_time = time.time()
        self.rpc_requests = 0
        self.http_requests = 0
        self.errors = 0
        self._status_lock = threading.Lock()
        self._status_bucket_counts = [0] * (len(_STATUS_MS_BUCKETS) + 1)
        self._status_sum_ms = 0.0
        self._status_count = 0
        self._status_last_ms = 0.0
        self._status_max_ms = 0.0

    def observe_status_ms(self, duration_ms: float) -> None:
        """Record GET /status handler wall time. Cumulative Prometheus histogram."""
        try:
            ms = float(duration_ms)
        except (TypeError, ValueError):
            return
        if ms != ms or ms in (float("inf"), float("-inf")):
            return
        if ms < 0.0:
            ms = 0.0
        with self._status_lock:
            self._status_count += 1
            self._status_sum_ms += ms
            self._status_last_ms = ms
            if ms > self._status_max_ms:
                self._status_max_ms = ms
            for i, le in enumerate(_STATUS_MS_BUCKETS):
                if ms <= le:
                    self._status_bucket_counts[i] += 1
            self._status_bucket_counts[-1] += 1

    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    def inc_http(self) -> None:
        self.http_requests += 1

    def inc_rpc(self) -> None:
        self.rpc_requests += 1

    def inc_error(self) -> None:
        self.errors += 1

    def _render_status_histogram(self, node_id: str) -> list[str]:
        with self._status_lock:
            buckets = list(self._status_bucket_counts)
            total = int(self._status_count)
            sum_ms = float(self._status_sum_ms)
            last_ms = float(self._status_last_ms)
            max_ms = float(self._status_max_ms)
        lines = [
            "# HELP abs_http_status_duration_ms GET /status handler duration",
            "# TYPE abs_http_status_duration_ms histogram",
        ]
        for i, le in enumerate(_STATUS_MS_BUCKETS):
            lines.append(
                f'abs_http_status_duration_ms_bucket{{node_id="{node_id}",le="{le}"}} '
                f"{buckets[i]}"
            )
        lines.append(
            f'abs_http_status_duration_ms_bucket{{node_id="{node_id}",le="+Inf"}} '
            f"{buckets[-1]}"
        )
        lines.extend(
            [
                f'abs_http_status_duration_ms_sum{{node_id="{node_id}"}} {sum_ms:.3f}',
                f'abs_http_status_duration_ms_count{{node_id="{node_id}"}} {total}',
                "# HELP abs_http_status_last_ms Last GET /status handler duration",
                "# TYPE abs_http_status_last_ms gauge",
                f'abs_http_status_last_ms{{node_id="{node_id}"}} {last_ms:.3f}',
                "# HELP abs_http_status_max_ms Max GET /status handler duration since boot",
                "# TYPE abs_http_status_max_ms gauge",
                f'abs_http_status_max_ms{{node_id="{node_id}"}} {max_ms:.3f}',
            ]
        )
        return lines

    def render_prometheus(
        self,
        *,
        height: int = 0,
        peers: int = 0,
        mempool: int = 0,
        validators: int = 0,
        deployment_mode: str = "dev",
        node_id: str = "node-1",
        native_crypto: Optional[dict[str, Any]] = None,
        bridge_health: Optional[dict[str, Any]] = None,
        p2p_security: Optional[dict[str, Any]] = None,
        rocksdb_tuning: Optional[dict[str, Any]] = None,
        sync_status: Optional[dict[str, Any]] = None,
        core_engines: Optional[dict[str, Any]] = None,
        ws_stats: Optional[dict[str, Any]] = None,
        apply_isolation: Optional[dict[str, Any]] = None,
        tps: float = 0.0,
    ) -> str:
        native_crypto = native_crypto or {}
        bridge_health = bridge_health or {}
        p2p_security = p2p_security or {}
        rocksdb_tuning = rocksdb_tuning or {}
        sync_status = sync_status or {}
        core_engines = core_engines or {}
        ws_stats = ws_stats or {}
        apply_isolation = apply_isolation or {}
        try:
            tps_val = float(tps or 0.0)
            if tps_val != tps_val or tps_val in (float("inf"), float("-inf")):
                tps_val = 0.0
        except Exception:
            tps_val = 0.0
        if "security_ok" in p2p_security:
            security_ok = 1 if p2p_security.get("security_ok") else 0
        elif p2p_security:
            security_ok = (
                1
                if (
                    "active_bans" in p2p_security
                    or "rate_limit_per_sec" in p2p_security
                )
                else 0
            )
        else:
            security_ok = 0
        lines = [
            "# HELP abs_uptime_seconds Node uptime",
            "# TYPE abs_uptime_seconds gauge",
            f"abs_uptime_seconds{{node_id=\"{node_id}\"}} {self.uptime_seconds():.2f}",
            "# HELP abs_chain_height Current block height",
            "# TYPE abs_chain_height gauge",
            f"abs_chain_height{{node_id=\"{node_id}\"}} {height}",
            "# HELP abs_peers_connected Connected P2P peers",
            "# TYPE abs_peers_connected gauge",
            f"abs_peers_connected{{node_id=\"{node_id}\"}} {peers}",
            "# HELP abs_tps Estimated transactions per second (chain window)",
            "# TYPE abs_tps gauge",
            f"abs_tps{{node_id=\"{node_id}\"}} {tps_val:.6f}",
            "# HELP abs_p2p_security_ok Whether P2P security snapshot is healthy/present",
            "# TYPE abs_p2p_security_ok gauge",
            f"abs_p2p_security_ok{{node_id=\"{node_id}\"}} {security_ok}",
            "# HELP abs_mempool_size Pending transactions",
            "# TYPE abs_mempool_size gauge",
            f"abs_mempool_size{{node_id=\"{node_id}\"}} {mempool}",
            "# HELP abs_validators_active Active validators",
            "# TYPE abs_validators_active gauge",
            f"abs_validators_active{{node_id=\"{node_id}\"}} {validators}",
            "# HELP abs_http_requests_total HTTP requests served",
            "# TYPE abs_http_requests_total counter",
            f"abs_http_requests_total{{node_id=\"{node_id}\"}} {self.http_requests}",
            *self._render_status_histogram(node_id),
            "# HELP abs_errors_total API errors",
            "# TYPE abs_errors_total counter",
            f"abs_errors_total{{node_id=\"{node_id}\"}} {self.errors}",
            f"abs_deployment_mode{{node_id=\"{node_id}\",mode=\"{deployment_mode}\"}} 1",
            "# HELP abs_native_crypto_available Native Rust/PyO3 crypto module availability",
            "# TYPE abs_native_crypto_available gauge",
            (
                f"abs_native_crypto_available{{node_id=\"{node_id}\"}} "
                f"{1 if native_crypto.get('available') else 0}"
            ),
            "# HELP abs_native_crypto_required Whether this node requires native crypto",
            "# TYPE abs_native_crypto_required gauge",
            (
                f"abs_native_crypto_required{{node_id=\"{node_id}\"}} "
                f"{1 if native_crypto.get('required') else 0}"
            ),
            "# HELP abs_native_crypto_self_test Native crypto self-test status",
            "# TYPE abs_native_crypto_self_test gauge",
            (
                f"abs_native_crypto_self_test{{node_id=\"{node_id}\"}} "
                f"{1 if native_crypto.get('self_test') else 0}"
            ),
            "# HELP abs_rust_bridge_enabled Whether the Rust bridge path is enabled",
            "# TYPE abs_rust_bridge_enabled gauge",
            (
                f"abs_rust_bridge_enabled{{node_id=\"{node_id}\"}} "
                f"{1 if bridge_health.get('enabled') and bridge_health.get('mode') == 'rust' else 0}"
            ),
            "# HELP abs_rust_bridge_required Whether readiness requires the Rust bridge",
            "# TYPE abs_rust_bridge_required gauge",
            (
                f"abs_rust_bridge_required{{node_id=\"{node_id}\"}} "
                f"{1 if bridge_health.get('required') else 0}"
            ),
            "# HELP abs_rust_bridge_ok Rust bridge JSON smoke-test status",
            "# TYPE abs_rust_bridge_ok gauge",
            (
                f"abs_rust_bridge_ok{{node_id=\"{node_id}\"}} "
                f"{1 if bridge_health.get('ok') else 0}"
            ),
            "# HELP abs_l1_rpc_configured Whether any L1 RPC URL is configured",
            "# TYPE abs_l1_rpc_configured gauge",
            (
                f"abs_l1_rpc_configured{{node_id=\"{node_id}\"}} "
                f"{1 if (bridge_health.get('l1_rpc') or {}).get('configured') else 0}"
            ),
            "# HELP abs_l1_rpc_required Whether readiness requires live L1 RPC",
            "# TYPE abs_l1_rpc_required gauge",
            (
                f"abs_l1_rpc_required{{node_id=\"{node_id}\"}} "
                f"{1 if (bridge_health.get('l1_rpc') or {}).get('required') else 0}"
            ),
            "# HELP abs_l1_rpc_ok L1 RPC reachability probe status",
            "# TYPE abs_l1_rpc_ok gauge",
            (
                f"abs_l1_rpc_ok{{node_id=\"{node_id}\"}} "
                f"{1 if (bridge_health.get('l1_rpc') or {}).get('ok') else 0}"
            ),
            "# HELP abs_l1_rpc_probed Whether a live L1 eth_blockNumber probe ran",
            "# TYPE abs_l1_rpc_probed gauge",
            (
                f"abs_l1_rpc_probed{{node_id=\"{node_id}\"}} "
                f"{1 if (bridge_health.get('l1_rpc') or {}).get('probed') else 0}"
            ),
            "# HELP abs_p2p_handshake_rejects_total Handshake rejects (payload + mid-session)",
            "# TYPE abs_p2p_handshake_rejects_total counter",
            (
                f"abs_p2p_handshake_rejects_total{{node_id=\"{node_id}\"}} "
                f"{int(p2p_security.get('handshake_rejects', 0) or 0)}"
            ),
            "# HELP abs_p2p_attestation_local_fail_total Local attestation sign failures",
            "# TYPE abs_p2p_attestation_local_fail_total counter",
            (
                f"abs_p2p_attestation_local_fail_total{{node_id=\"{node_id}\"}} "
                f"{int(p2p_security.get('attestation_local_fail', 0) or 0)}"
            ),
            "# HELP abs_p2p_peer_tx_reject_total Semantic peer tx rejects / mempool drops",
            "# TYPE abs_p2p_peer_tx_reject_total counter",
            (
                f"abs_p2p_peer_tx_reject_total{{node_id=\"{node_id}\"}} "
                f"{int((p2p_security.get('ops_errors') or {}).get('peer_tx_reject', 0) or 0)}"
            ),
            "# HELP abs_p2p_shape_rejects_total Fail-closed P2P shape rejects",
            "# TYPE abs_p2p_shape_rejects_total counter",
            (
                f"abs_p2p_shape_rejects_total{{node_id=\"{node_id}\"}} "
                f"{int(p2p_security.get('shape_rejects_total', 0) or 0)}"
            ),
            "# HELP abs_p2p_active_bans Currently banned peer keys",
            "# TYPE abs_p2p_active_bans gauge",
            (
                f"abs_p2p_active_bans{{node_id=\"{node_id}\"}} "
                f"{int(p2p_security.get('active_bans', 0) or 0)}"
            ),
            "# HELP abs_p2p_rate_limit_drops_total P2P per-peer rate-limit drops (strikes)",
            "# TYPE abs_p2p_rate_limit_drops_total counter",
            (
                f"abs_p2p_rate_limit_drops_total{{node_id=\"{node_id}\"}} "
                f"{int(p2p_security.get('rate_limit_drops', 0) or 0)}"
            ),
            "# HELP abs_p2p_shape_rejects Fail-closed P2P shape rejects by reason",
            "# TYPE abs_p2p_shape_rejects counter",
        ]
        for reason, count in (p2p_security.get("shape_rejects") or {}).items():
            safe_reason = (
                str(reason)
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", " ")
            )
            lines.append(
                f"abs_p2p_shape_rejects{{node_id=\"{node_id}\",reason=\"{safe_reason}\"}} "
                f"{int(count or 0)}"
            )
        ops_errors = dict(p2p_security.get("ops_errors") or {})
        lines.extend(
            [
                "# HELP abs_p2p_peer_send_fail_total Outbound P2P send failures",
                "# TYPE abs_p2p_peer_send_fail_total counter",
                (
                    f"abs_p2p_peer_send_fail_total{{node_id=\"{node_id}\"}} "
                    f"{int(ops_errors.get('peer_send_fail', 0) or 0)}"
                ),
                "# HELP abs_p2p_ops_errors P2P operational error counters by kind",
                "# TYPE abs_p2p_ops_errors counter",
            ]
        )
        for kind, count in ops_errors.items():
            safe_kind = (
                str(kind)
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", " ")
            )
            lines.append(
                f"abs_p2p_ops_errors{{node_id=\"{node_id}\",kind=\"{safe_kind}\"}} "
                f"{int(count or 0)}"
            )
        lines.extend(
            [
                "# HELP abs_db_engine Storage engine label (rocksdb|sqlite|unknown)",
                "# TYPE abs_db_engine gauge",
                (
                    f"abs_db_engine{{node_id=\"{node_id}\","
                    f"engine=\"{str(rocksdb_tuning.get('engine') or 'unknown')}\"}} 1"
                ),
            ]
        )
        emit_rocks = str(rocksdb_tuning.get("engine") or "") == "rocksdb" or str(
            rocksdb_tuning.get("source") or ""
        ) in ("live", "config_fallback")
        if emit_rocks and str(rocksdb_tuning.get("engine") or "") != "sqlite":
            lines.extend(
                [
                    "# HELP abs_rocksdb_column_families Whether RocksDB column families are enabled",
                    "# TYPE abs_rocksdb_column_families gauge",
                    (
                        f"abs_rocksdb_column_families{{node_id=\"{node_id}\"}} "
                        f"{1 if rocksdb_tuning.get('column_families') else 0}"
                    ),
                    "# HELP abs_rocksdb_block_cache_mb RocksDB block cache size (MB)",
                    "# TYPE abs_rocksdb_block_cache_mb gauge",
                    (
                        f"abs_rocksdb_block_cache_mb{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('block_cache_mb', 0) or 0)}"
                    ),
                    "# HELP abs_rocksdb_write_buffer_mb RocksDB write buffer size (MB)",
                    "# TYPE abs_rocksdb_write_buffer_mb gauge",
                    (
                        f"abs_rocksdb_write_buffer_mb{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('write_buffer_mb', 0) or 0)}"
                    ),
                    "# HELP abs_rocksdb_json_decode_failures Corrupt RocksDB JSON rows skipped",
                    "# TYPE abs_rocksdb_json_decode_failures counter",
                    (
                        f"abs_rocksdb_json_decode_failures{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('json_decode_failures', 0) or 0)}"
                    ),
                    "# HELP abs_rocksdb_running_compactions RocksDB running compactions",
                    "# TYPE abs_rocksdb_running_compactions gauge",
                    (
                        f"abs_rocksdb_running_compactions{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('running_compactions', 0) or 0)}"
                    ),
                    "# HELP abs_rocksdb_running_flushes RocksDB running flushes",
                    "# TYPE abs_rocksdb_running_flushes gauge",
                    (
                        f"abs_rocksdb_running_flushes{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('running_flushes', 0) or 0)}"
                    ),
                    "# HELP abs_rocksdb_estimate_num_keys RocksDB estimated key count",
                    "# TYPE abs_rocksdb_estimate_num_keys gauge",
                    (
                        f"abs_rocksdb_estimate_num_keys{{node_id=\"{node_id}\"}} "
                        f"{int(rocksdb_tuning.get('estimate_num_keys', 0) or 0)}"
                    ),
                ]
            )
        lines.extend(
            [
                "# HELP abs_sqlite_json_decode_failures Corrupt SQLite/aux JSON rows skipped",
                "# TYPE abs_sqlite_json_decode_failures counter",
                (
                    f"abs_sqlite_json_decode_failures{{node_id=\"{node_id}\"}} "
                    f"{int(rocksdb_tuning.get('sqlite_json_decode_failures', 0) or 0)}"
                ),
                "# HELP abs_aux_json_decode_failures Corrupt hybrid aux.db JSON rows skipped",
                "# TYPE abs_aux_json_decode_failures counter",
                (
                    f"abs_aux_json_decode_failures{{node_id=\"{node_id}\"}} "
                    f"{int(rocksdb_tuning.get('aux_json_decode_failures', 0) or 0)}"
                ),
                "# HELP abs_ws_send_failures_total WebSocket outbound send failures",
                "# TYPE abs_ws_send_failures_total counter",
                (
                    f"abs_ws_send_failures_total{{node_id=\"{node_id}\"}} "
                    f"{int(ws_stats.get('send_failures', 0) or 0)}"
                ),
                "# HELP abs_ws_running Whether WebSocket server reports running",
                "# TYPE abs_ws_running gauge",
                (
                    f"abs_ws_running{{node_id=\"{node_id}\"}} "
                    f"{1 if ws_stats.get('running') else 0}"
                ),
            ]
        )
        lines.extend(
            [
                "# HELP abs_state_consistent Whether tip state root matches peers",
                "# TYPE abs_state_consistent gauge",
                (
                    f"abs_state_consistent{{node_id=\"{node_id}\"}} "
                    f"{1 if sync_status.get('state_consistent') else 0}"
                ),
                "# HELP abs_sync_wire_probe_ok Last peer state_root wire probe "
                "# (-1=never probed, 0=failed, 1=ok)",
                "# TYPE abs_sync_wire_probe_ok gauge",
                (
                    f"abs_sync_wire_probe_ok{{node_id=\"{node_id}\"}} "
                    f"{self._wire_probe_ok_gauge(sync_status)}"
                ),
                "# HELP abs_sync_wire_probe_probed Whether a wire probe has completed",
                "# TYPE abs_sync_wire_probe_probed gauge",
                (
                    f"abs_sync_wire_probe_probed{{node_id=\"{node_id}\"}} "
                    f"{1 if sync_status.get('wire_probe_probed') else 0}"
                ),
                "# HELP abs_sync_consistency_state Consistency machine state label",
                "# TYPE abs_sync_consistency_state gauge",
                (
                    f"abs_sync_consistency_state{{node_id=\"{node_id}\","
                    f"state=\"{str(sync_status.get('sync_consistency_state') or 'unknown')}\"}} 1"
                ),
                "# HELP abs_sync_lockdown_total Consistency lockdown transitions",
                "# TYPE abs_sync_lockdown_total counter",
                (
                    f"abs_sync_lockdown_total{{node_id=\"{node_id}\"}} "
                    f"{int(sync_status.get('sync_lockdown_total', 0) or 0)}"
                ),
                "# HELP abs_rocksdb_tuning_source Whether live DB stats or config fallback",
                "# TYPE abs_rocksdb_tuning_source gauge",
                (
                    f"abs_rocksdb_tuning_source{{node_id=\"{node_id}\","
                    f"source=\"{str(rocksdb_tuning.get('source') or 'unknown')}\"}} 1"
                ),
                "# HELP abs_state_engine_available Deterministic StateEngine present",
                "# TYPE abs_state_engine_available gauge",
                (
                    f"abs_state_engine_available{{node_id=\"{node_id}\"}} "
                    f"{1 if core_engines.get('state_engine') else 0}"
                ),
                "# HELP abs_finality_engine_available FinalityEngine (Casper FFG) present",
                "# TYPE abs_finality_engine_available gauge",
                (
                    f"abs_finality_engine_available{{node_id=\"{node_id}\"}} "
                    f"{1 if core_engines.get('finality_engine') else 0}"
                ),
                "# HELP abs_ims_available ImmutableStateManager present",
                "# TYPE abs_ims_available gauge",
                (
                    f"abs_ims_available{{node_id=\"{node_id}\"}} "
                    f"{1 if core_engines.get('immutable_state') else 0}"
                ),
                "# HELP abs_chain_apply_queue_depth Serial apply queue depth",
                "# TYPE abs_chain_apply_queue_depth gauge",
                (
                    f"abs_chain_apply_queue_depth{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('queue_depth', 0) or 0)}"
                ),
                "# HELP abs_chain_apply_wait_seconds_total Cumulative wait on apply queue",
                "# TYPE abs_chain_apply_wait_seconds_total counter",
                (
                    f"abs_chain_apply_wait_seconds_total{{node_id=\"{node_id}\"}} "
                    f"{float(apply_isolation.get('wait_seconds_total', 0) or 0):.6f}"
                ),
                "# HELP abs_chain_apply_reject_total Apply queue backpressure rejects",
                "# TYPE abs_chain_apply_reject_total counter",
                (
                    f"abs_chain_apply_reject_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('reject_total', 0) or 0)}"
                ),
                "# HELP abs_chain_apply_expired_total Apply jobs expired before start",
                "# TYPE abs_chain_apply_expired_total counter",
                (
                    f"abs_chain_apply_expired_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('expired_total', 0) or 0)}"
                ),
                "# HELP abs_chain_apply_timeout_total Apply Future.result timeouts",
                "# TYPE abs_chain_apply_timeout_total counter",
                (
                    f"abs_chain_apply_timeout_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('timeout_total', 0) or 0)}"
                ),
                "# HELP abs_chain_apply_error_total Apply worker exceptions",
                "# TYPE abs_chain_apply_error_total counter",
                (
                    f"abs_chain_apply_error_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('error_total', 0) or 0)}"
                ),
                "# HELP abs_chain_apply_priority_lanes Priority lanes enabled (reorg>forge>add>import)",
                "# TYPE abs_chain_apply_priority_lanes gauge",
                (
                    f"abs_chain_apply_priority_lanes{{node_id=\"{node_id}\"}} "
                    f"{1 if apply_isolation.get('priority_lanes') else 0}"
                ),
                "# HELP abs_chain_apply_exec_seconds_total Cumulative apply execution time",
                "# TYPE abs_chain_apply_exec_seconds_total counter",
                (
                    f"abs_chain_apply_exec_seconds_total{{node_id=\"{node_id}\"}} "
                    f"{float(apply_isolation.get('exec_seconds_total', 0) or 0):.6f}"
                ),
                "# HELP abs_p2p_sync_tasks Active coalesced sync tasks",
                "# TYPE abs_p2p_sync_tasks gauge",
                (
                    f"abs_p2p_sync_tasks{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('sync_tasks', 0) or 0)}"
                ),
                "# HELP abs_p2p_import_offload_total P2P import/reorg offload submissions",
                "# TYPE abs_p2p_import_offload_total counter",
                (
                    f"abs_p2p_import_offload_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('import_offload_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_outbound_drops_total Outbound send-queue drops under backpressure",
                "# TYPE abs_p2p_outbound_drops_total counter",
                (
                    f"abs_p2p_outbound_drops_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('outbound_drops', 0) or 0)}"
                ),
                "# HELP abs_p2p_sync_admission_rejects_total Sync tasks rejected by inflight cap",
                "# TYPE abs_p2p_sync_admission_rejects_total counter",
                (
                    f"abs_p2p_sync_admission_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('sync_admission_rejects', 0) or 0)}"
                ),
                "# HELP abs_p2p_max_sync_inflight Configured global sync concurrency cap",
                "# TYPE abs_p2p_max_sync_inflight gauge",
                (
                    f"abs_p2p_max_sync_inflight{{node_id=\"{node_id}\"}} "
                    f"{int(apply_isolation.get('max_sync_inflight', 2) or 2)}"
                ),
                "# HELP abs_p2p_bandwidth_rejects_total Per-peer inbound bandwidth budget rejects",
                "# TYPE abs_p2p_bandwidth_rejects_total counter",
                (
                    f"abs_p2p_bandwidth_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('bandwidth_rejects', 0) or 0)}"
                ),
                "# HELP abs_p2p_max_bytes_per_sec Configured per-peer inbound bandwidth budget",
                "# TYPE abs_p2p_max_bytes_per_sec gauge",
                (
                    f"abs_p2p_max_bytes_per_sec{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('max_bytes_per_sec', 0) or 0)}"
                ),
                "# HELP abs_p2p_egress_rejects_total Per-peer outbound bandwidth budget rejects",
                "# TYPE abs_p2p_egress_rejects_total counter",
                (
                    f"abs_p2p_egress_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('egress_rejects', 0) or 0)}"
                ),
                "# HELP abs_p2p_max_outbound_bytes_per_sec Configured per-peer outbound bandwidth budget",
                "# TYPE abs_p2p_max_outbound_bytes_per_sec gauge",
                (
                    f"abs_p2p_max_outbound_bytes_per_sec{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('max_outbound_bytes_per_sec', 0) or 0)}"
                ),
                "# HELP abs_p2p_subnet_rejects_total Public subnet diversity inbound rejects",
                "# TYPE abs_p2p_subnet_rejects_total counter",
                (
                    f"abs_p2p_subnet_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('subnet_rejects', 0) or 0)}"
                ),
                "# HELP abs_p2p_reserved_slot_rejects_total Inbound rejects preserving outbound dial slots",
                "# TYPE abs_p2p_reserved_slot_rejects_total counter",
                (
                    f"abs_p2p_reserved_slot_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('reserved_slot_rejects', 0) or 0)}"
                ),
                "# HELP abs_p2p_eclipse_at_risk Eclipse risk gauge (1 when densest public subnet ratio exceeds warn)",
                "# TYPE abs_p2p_eclipse_at_risk gauge",
                (
                    f"abs_p2p_eclipse_at_risk{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('eclipse_at_risk') else 0}"
                ),
                "# HELP abs_p2p_eclipse_ratio Densest public subnet share of public peers",
                "# TYPE abs_p2p_eclipse_ratio gauge",
                (
                    f"abs_p2p_eclipse_ratio{{node_id=\"{node_id}\"}} "
                    f"{float(p2p_security.get('eclipse_ratio', 0) or 0)}"
                ),
                "# HELP abs_p2p_eclipse_prune_total Peers pruned due to eclipse concentration",
                "# TYPE abs_p2p_eclipse_prune_total counter",
                (
                    f"abs_p2p_eclipse_prune_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('eclipse_prune_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_transport Whether Rust TCP transport is active (0/1)",
                "# TYPE abs_p2p_native_transport gauge",
                (
                    f"abs_p2p_native_transport{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_p2p_transport') else 0}"
                ),
                "# HELP abs_p2p_native_tls Whether native transport uses rustls (0/1)",
                "# TYPE abs_p2p_native_tls gauge",
                (
                    f"abs_p2p_native_tls{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_p2p_tls') else 0}"
                ),
                "# HELP abs_p2p_transport_boundary Whether transport boundary adapter status is present (0/1)",
                "# TYPE abs_p2p_transport_boundary gauge",
                (
                    f"abs_p2p_transport_boundary{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('transport_boundary') else 0}"
                ),
                "# HELP abs_p2p_transport_admit_ok_total Transport-boundary ingress admits",
                "# TYPE abs_p2p_transport_admit_ok_total counter",
                (
                    f"abs_p2p_transport_admit_ok_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('transport_admit_ok_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_transport_egress_ok_total Transport-boundary egress prepares",
                "# TYPE abs_p2p_transport_egress_ok_total counter",
                (
                    f"abs_p2p_transport_egress_ok_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('transport_egress_ok_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_transport_reject_total Transport-boundary rejects (all classes)",
                "# TYPE abs_p2p_transport_reject_total counter",
                (
                    f"abs_p2p_transport_reject_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('transport_reject_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_transport_reject Transport-boundary rejects by reason",
                "# TYPE abs_p2p_transport_reject counter",
            ]
        )
        for reason, count in (p2p_security.get("transport_reject_by_reason") or {}).items():
            safe_reason = (
                str(reason)
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", " ")
            )
            lines.append(
                f"abs_p2p_transport_reject{{node_id=\"{node_id}\",reason=\"{safe_reason}\"}} "
                f"{int(count or 0)}"
            )
        lines.extend(
            [
                "# HELP abs_p2p_transport_reject_class Transport-boundary rejects by class",
                "# TYPE abs_p2p_transport_reject_class counter",
            ]
        )
        for klass, count in (p2p_security.get("transport_reject_by_class") or {}).items():
            safe_klass = (
                str(klass)
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", " ")
            )
            lines.append(
                f"abs_p2p_transport_reject_class{{node_id=\"{node_id}\",class=\"{safe_klass}\"}} "
                f"{int(count or 0)}"
            )
        lines.extend(
            [
                "# HELP abs_p2p_native_read_message Whether fused read_message pump is active (0/1)",
                "# TYPE abs_p2p_native_read_message gauge",
                (
                    f"abs_p2p_native_read_message{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_read_message') else 0}"
                ),
                "# HELP abs_p2p_native_write_message Whether fused write_message pump is active (0/1)",
                "# TYPE abs_p2p_native_write_message gauge",
                (
                    f"abs_p2p_native_write_message{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_write_message') else 0}"
                ),
                "# HELP abs_p2p_native_read_messages Whether batch read_messages pump is active (0/1)",
                "# TYPE abs_p2p_native_read_messages gauge",
                (
                    f"abs_p2p_native_read_messages{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_read_messages') else 0}"
                ),
                "# HELP abs_p2p_native_write_messages Whether batch write_messages pump is active (0/1)",
                "# TYPE abs_p2p_native_write_messages gauge",
                (
                    f"abs_p2p_native_write_messages{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_write_messages') else 0}"
                ),
                "# HELP abs_p2p_native_handshake Whether native handshake_roundtrip is active (0/1)",
                "# TYPE abs_p2p_native_handshake gauge",
                (
                    f"abs_p2p_native_handshake{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake') else 0}"
                ),
                "# HELP abs_p2p_native_mid_session_gate Whether native mid-session handshake gate is active (0/1)",
                "# TYPE abs_p2p_native_mid_session_gate gauge",
                (
                    f"abs_p2p_native_mid_session_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mid_session_gate') else 0}"
                ),
                "# HELP abs_p2p_native_peer_identities Whether native CN/SAN identity extract is active (0/1)",
                "# TYPE abs_p2p_native_peer_identities gauge",
                (
                    f"abs_p2p_native_peer_identities{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_peer_identities') else 0}"
                ),
                "# HELP abs_p2p_native_auto_pong Whether native read-path auto-pong is active (0/1)",
                "# TYPE abs_p2p_native_auto_pong gauge",
                (
                    f"abs_p2p_native_auto_pong{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_auto_pong') else 0}"
                ),
                "# HELP abs_p2p_native_keepalive Whether native ping/pong keepalive consume is active (0/1)",
                "# TYPE abs_p2p_native_keepalive gauge",
                (
                    f"abs_p2p_native_keepalive{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_auto_pong') else 0}"
                ),
                "# HELP abs_p2p_native_housekeeping_gate Whether native housekeeping payload gate is active (0/1)",
                "# TYPE abs_p2p_native_housekeeping_gate gauge",
                (
                    f"abs_p2p_native_housekeeping_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_housekeeping_gate') else 0}"
                ),
                "# HELP abs_p2p_native_status_gate Whether native status payload gate is active (0/1)",
                "# TYPE abs_p2p_native_status_gate gauge",
                (
                    f"abs_p2p_native_status_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_gate') else 0}"
                ),
                "# HELP abs_p2p_native_attestation_gate Whether native attestation shape gate is active (0/1)",
                "# TYPE abs_p2p_native_attestation_gate gauge",
                (
                    f"abs_p2p_native_attestation_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_attestation_gate') else 0}"
                ),
                "# HELP abs_p2p_native_block_sync_gate Whether native new_block/get_block shape gates are active (0/1)",
                "# TYPE abs_p2p_native_block_sync_gate gauge",
                (
                    f"abs_p2p_native_block_sync_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_sync_gate') else 0}"
                ),
                "# HELP abs_p2p_native_block_fetch_gate Whether native get_blocks/get_block_by_hash/blocks gates are active (0/1)",
                "# TYPE abs_p2p_native_block_fetch_gate gauge",
                (
                    f"abs_p2p_native_block_fetch_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_fetch_gate') else 0}"
                ),
                "# HELP abs_p2p_native_tx_gossip_gate Whether native new_tx/mempool shape gates are active (0/1)",
                "# TYPE abs_p2p_native_tx_gossip_gate gauge",
                (
                    f"abs_p2p_native_tx_gossip_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_tx_gossip_gate') else 0}"
                ),
                "# HELP abs_p2p_native_block_payload_gate Whether native singular block payload gate is active (0/1)",
                "# TYPE abs_p2p_native_block_payload_gate gauge",
                (
                    f"abs_p2p_native_block_payload_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_payload_gate') else 0}"
                ),
                "# HELP abs_p2p_native_peer_discovery_gate Whether native peers/validator_register gates are active (0/1)",
                "# TYPE abs_p2p_native_peer_discovery_gate gauge",
                (
                    f"abs_p2p_native_peer_discovery_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_peer_discovery_gate') else 0}"
                ),
                "# HELP abs_p2p_native_state_root_gate Whether native state_root request/response gates are active (0/1)",
                "# TYPE abs_p2p_native_state_root_gate gauge",
                (
                    f"abs_p2p_native_state_root_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_gate') else 0}"
                ),
                "# HELP abs_p2p_native_cross_shard_gate Whether native cross-shard shape gates are active (0/1)",
                "# TYPE abs_p2p_native_cross_shard_gate gauge",
                (
                    f"abs_p2p_native_cross_shard_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_cross_shard_gate') else 0}"
                ),
                "# HELP abs_p2p_native_handshake_payload_gate Whether native handshake payload gate is active (0/1)",
                "# TYPE abs_p2p_native_handshake_payload_gate gauge",
                (
                    f"abs_p2p_native_handshake_payload_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake_payload_gate') else 0}"
                ),
                "# HELP abs_p2p_native_handshake_policy_gate Whether native handshake policy fuse is active (0/1)",
                "# TYPE abs_p2p_native_handshake_policy_gate gauge",
                (
                    f"abs_p2p_native_handshake_policy_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake_policy_gate') else 0}"
                ),
                "# HELP abs_p2p_native_message_loop_shell Whether native message-loop event shell is active (0/1)",
                "# TYPE abs_p2p_native_message_loop_shell gauge",
                (
                    f"abs_p2p_native_message_loop_shell{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_message_loop_shell') else 0}"
                ),
                "# HELP abs_p2p_native_attestation_semantic_gate Whether native attestation semantic gate is active (0/1)",
                "# TYPE abs_p2p_native_attestation_semantic_gate gauge",
                (
                    f"abs_p2p_native_attestation_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_attestation_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_attestation_semantic_rejects_total Attestation identity/sig rejects from native semantic gate",
                "# TYPE abs_p2p_attestation_semantic_rejects_total counter",
                (
                    f"abs_p2p_attestation_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('attestation_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_tx_semantic_gate Whether native new_tx signature gate is active (0/1)",
                "# TYPE abs_p2p_native_tx_semantic_gate gauge",
                (
                    f"abs_p2p_native_tx_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_tx_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_tx_semantic_rejects_total new_tx/mempool signature rejects from native semantic gate",
                "# TYPE abs_p2p_tx_semantic_rejects_total counter",
                (
                    f"abs_p2p_tx_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tx_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_semantic_gate Whether native mempool batch signature gate is active (0/1)",
                "# TYPE abs_p2p_native_mempool_semantic_gate gauge",
                (
                    f"abs_p2p_native_mempool_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_native_block_semantic_gate Whether native new_block hash gate is active (0/1)",
                "# TYPE abs_p2p_native_block_semantic_gate gauge",
                (
                    f"abs_p2p_native_block_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_block_semantic_rejects_total new_block/blocks hash rejects from native semantic gate",
                "# TYPE abs_p2p_block_semantic_rejects_total counter",
                (
                    f"abs_p2p_block_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('block_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_blocks_batch_semantic_gate Whether native blocks batch hash gate is active (0/1)",
                "# TYPE abs_p2p_native_blocks_batch_semantic_gate gauge",
                (
                    f"abs_p2p_native_blocks_batch_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_blocks_batch_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_native_block_payload_semantic_gate Whether native singular block hash gate is active (0/1)",
                "# TYPE abs_p2p_native_block_payload_semantic_gate gauge",
                (
                    f"abs_p2p_native_block_payload_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_payload_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_native_state_root_response_semantic_gate Whether native state_root_response digest gate is active (0/1)",
                "# TYPE abs_p2p_native_state_root_response_semantic_gate gauge",
                (
                    f"abs_p2p_native_state_root_response_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_response_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_state_root_semantic_rejects_total state_root_response digest rejects from native semantic gate",
                "# TYPE abs_p2p_state_root_semantic_rejects_total counter",
                (
                    f"abs_p2p_state_root_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('state_root_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_status_head_hash_semantic_gate Whether native status head_hash digest gate is active (0/1)",
                "# TYPE abs_p2p_native_status_head_hash_semantic_gate gauge",
                (
                    f"abs_p2p_native_status_head_hash_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_head_hash_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_status_semantic_rejects_total status head_hash digest rejects from native semantic gate",
                "# TYPE abs_p2p_status_semantic_rejects_total counter",
                (
                    f"abs_p2p_status_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('status_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_blocks_response_semantic_gate Whether request-bound blocks response gate is active (0/1)",
                "# TYPE abs_p2p_native_blocks_response_semantic_gate gauge",
                (
                    f"abs_p2p_native_blocks_response_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_blocks_response_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_blocks_response_semantic_rejects_total request-bound blocks response rejects",
                "# TYPE abs_p2p_blocks_response_semantic_rejects_total counter",
                (
                    f"abs_p2p_blocks_response_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('blocks_response_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_block_response_semantic_gate Whether request-bound singular block response gate is active (0/1)",
                "# TYPE abs_p2p_native_block_response_semantic_gate gauge",
                (
                    f"abs_p2p_native_block_response_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_response_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_block_response_semantic_rejects_total request-bound singular block response rejects",
                "# TYPE abs_p2p_block_response_semantic_rejects_total counter",
                (
                    f"abs_p2p_block_response_semantic_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('block_response_semantic_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_state_root_response_request_gate Whether request-bound state_root height gate is active (0/1)",
                "# TYPE abs_p2p_native_state_root_response_request_gate gauge",
                (
                    f"abs_p2p_native_state_root_response_request_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_response_request_gate') else 0}"
                ),
                "# HELP abs_p2p_state_root_response_request_rejects_total request-bound state_root height rejects",
                "# TYPE abs_p2p_state_root_response_request_rejects_total counter",
                (
                    f"abs_p2p_state_root_response_request_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('state_root_response_request_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_state_root_outbound_honesty Whether outbound state_root height honesty is active (0/1)",
                "# TYPE abs_p2p_native_state_root_outbound_honesty gauge",
                (
                    f"abs_p2p_native_state_root_outbound_honesty{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_outbound_honesty') else 0}"
                ),
                "# HELP abs_p2p_state_root_outbound_refuse_total Outbound state_root_request refused (ahead/missing)",
                "# TYPE abs_p2p_state_root_outbound_refuse_total counter",
                (
                    f"abs_p2p_state_root_outbound_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('state_root_outbound_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_state_root_response_head_gate Whether soft expected_head on state_root waiters is active (0/1)",
                "# TYPE abs_p2p_native_state_root_response_head_gate gauge",
                (
                    f"abs_p2p_native_state_root_response_head_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_response_head_gate') else 0}"
                ),
                "# HELP abs_p2p_native_mempool_solicit_only Whether unsolicited mempool batches are rejected (0/1)",
                "# TYPE abs_p2p_native_mempool_solicit_only gauge",
                (
                    f"abs_p2p_native_mempool_solicit_only{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_solicit_only') else 0}"
                ),
                "# HELP abs_p2p_native_mempool_solicit_armed_shell Whether native shell skips ECDSA on unsolicited mempool (0/1)",
                "# TYPE abs_p2p_native_mempool_solicit_armed_shell gauge",
                (
                    f"abs_p2p_native_mempool_solicit_armed_shell{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_solicit_armed_shell') else 0}"
                ),
                "# HELP abs_p2p_native_peer_score_quality Whether peer score includes strikes/import fails (0/1)",
                "# TYPE abs_p2p_native_peer_score_quality gauge",
                (
                    f"abs_p2p_native_peer_score_quality{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_peer_score_quality') else 0}"
                ),
                "# HELP abs_p2p_unsolicited_mempool_rejects_total Unsolicited mempool batch rejects",
                "# TYPE abs_p2p_unsolicited_mempool_rejects_total counter",
                (
                    f"abs_p2p_unsolicited_mempool_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('unsolicited_mempool_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_status_height_cap_total Status peer.height claims capped above local tip",
                "# TYPE abs_p2p_status_height_cap_total counter",
                (
                    f"abs_p2p_status_height_cap_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('status_height_cap_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_new_block_height_cap Whether new_block peer.height ahead gate is active (0/1)",
                "# TYPE abs_p2p_native_new_block_height_cap gauge",
                (
                    f"abs_p2p_native_new_block_height_cap{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_height_cap') else 0}"
                ),
                "# HELP abs_p2p_new_block_height_cap_total new_block announces capped/refused above local tip window",
                "# TYPE abs_p2p_new_block_height_cap_total counter",
                (
                    f"abs_p2p_new_block_height_cap_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_height_cap_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_height_cap_clear_head Whether height-cap clears fantasy peer.head (0/1)",
                "# TYPE abs_p2p_native_height_cap_clear_head gauge",
                (
                    f"abs_p2p_native_height_cap_clear_head{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_height_cap_clear_head') else 0}"
                ),
                "# HELP abs_p2p_native_new_block_head_height_bind Whether known announce hash height bind is active (0/1)",
                "# TYPE abs_p2p_native_new_block_head_height_bind gauge",
                (
                    f"abs_p2p_native_new_block_head_height_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_head_height_bind') else 0}"
                ),
                "# HELP abs_p2p_new_block_head_height_mismatch_total new_block announces refused for local head/height mismatch",
                "# TYPE abs_p2p_new_block_head_height_mismatch_total counter",
                (
                    f"abs_p2p_new_block_head_height_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_head_height_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_status_head_height_bind Whether known status/handshake head height bind is active (0/1)",
                "# TYPE abs_p2p_native_status_head_height_bind gauge",
                (
                    f"abs_p2p_native_status_head_height_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_head_height_bind') else 0}"
                ),
                "# HELP abs_p2p_status_head_height_mismatch_total status/handshake tip meta refused for local head/height mismatch",
                "# TYPE abs_p2p_status_head_height_mismatch_total counter",
                (
                    f"abs_p2p_status_head_height_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('status_head_height_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_status_head_requires_height Whether head-only STATUS is refused when local tip > 0 (0/1)",
                "# TYPE abs_p2p_native_status_head_requires_height gauge",
                (
                    f"abs_p2p_native_status_head_requires_height{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_head_requires_height') else 0}"
                ),
                "# HELP abs_p2p_status_head_without_height_total STATUS head-only (height<=0) refused while local tip > 0",
                "# TYPE abs_p2p_status_head_without_height_total counter",
                (
                    f"abs_p2p_status_head_without_height_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('status_head_without_height_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_handshake_head_requires_height Whether head-only handshake is refused when local tip > 0 (0/1)",
                "# TYPE abs_p2p_native_handshake_head_requires_height gauge",
                (
                    f"abs_p2p_native_handshake_head_requires_height{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake_head_requires_height') else 0}"
                ),
                "# HELP abs_p2p_handshake_head_without_height_total Handshake head-only (height<=0) refused while local tip > 0",
                "# TYPE abs_p2p_handshake_head_without_height_total counter",
                (
                    f"abs_p2p_handshake_head_without_height_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('handshake_head_without_height_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_new_block_announce_body_bind Whether new_block announce↔body bind is active (0/1)",
                "# TYPE abs_p2p_native_new_block_announce_body_bind gauge",
                (
                    f"abs_p2p_native_new_block_announce_body_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_announce_body_bind') else 0}"
                ),
                "# HELP abs_p2p_native_new_block_defer_tip Whether new_block defers tip mutate until body parse (0/1)",
                "# TYPE abs_p2p_native_new_block_defer_tip gauge",
                (
                    f"abs_p2p_native_new_block_defer_tip{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_defer_tip') else 0}"
                ),
                "# HELP abs_p2p_new_block_announce_body_refuse_total new_block announces refused for announce↔body mismatch",
                "# TYPE abs_p2p_new_block_announce_body_refuse_total counter",
                (
                    f"abs_p2p_new_block_announce_body_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_announce_body_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_new_block_contiguous_parent_bind Whether +1 new_block parent must match local tip (0/1)",
                "# TYPE abs_p2p_native_new_block_contiguous_parent_bind gauge",
                (
                    f"abs_p2p_native_new_block_contiguous_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_contiguous_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_new_block_contiguous_parent_mismatch_total new_block +1 announces refused for parent/tip mismatch",
                "# TYPE abs_p2p_new_block_contiguous_parent_mismatch_total counter",
                (
                    f"abs_p2p_new_block_contiguous_parent_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_contiguous_parent_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_new_block_same_height_parent_bind Whether same-height new_block parent must match tip parent (0/1)",
                "# TYPE abs_p2p_native_new_block_same_height_parent_bind gauge",
                (
                    f"abs_p2p_native_new_block_same_height_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_same_height_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_new_block_same_height_parent_mismatch_total same-height new_block refused for parent/tip-parent mismatch",
                "# TYPE abs_p2p_new_block_same_height_parent_mismatch_total counter",
                (
                    f"abs_p2p_new_block_same_height_parent_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_same_height_parent_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_new_block_tip_head_bind Whether new_block accept requires tip==announce hash (0/1)",
                "# TYPE abs_p2p_native_new_block_tip_head_bind gauge",
                (
                    f"abs_p2p_native_new_block_tip_head_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_new_block_tip_head_bind') else 0}"
                ),
                "# HELP abs_p2p_new_block_tip_head_mismatch_total new_block accept refused when tip != announce hash",
                "# TYPE abs_p2p_new_block_tip_head_mismatch_total counter",
                (
                    f"abs_p2p_new_block_tip_head_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('new_block_tip_head_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_handshake_height_cap Whether handshake peer.height ahead gate is active (0/1)",
                "# TYPE abs_p2p_native_handshake_height_cap gauge",
                (
                    f"abs_p2p_native_handshake_height_cap{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake_height_cap') else 0}"
                ),
                "# HELP abs_p2p_handshake_height_cap_total Handshake peer.height claims capped above local tip",
                "# TYPE abs_p2p_handshake_height_cap_total counter",
                (
                    f"abs_p2p_handshake_height_cap_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('handshake_height_cap_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_status_capped_head_refuse Whether capped status skips fantasy peer.head (0/1)",
                "# TYPE abs_p2p_native_status_capped_head_refuse gauge",
                (
                    f"abs_p2p_native_status_capped_head_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_capped_head_refuse') else 0}"
                ),
                "# HELP abs_p2p_native_state_root_local_consistency Whether known-header state_root match is enforced (0/1)",
                "# TYPE abs_p2p_native_state_root_local_consistency gauge",
                (
                    f"abs_p2p_native_state_root_local_consistency{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_local_consistency') else 0}"
                ),
                "# HELP abs_p2p_state_root_local_rejects_total state_root responses mismatching known local header root",
                "# TYPE abs_p2p_state_root_local_rejects_total counter",
                (
                    f"abs_p2p_state_root_local_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('state_root_local_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_attestation_slot_ahead Whether attestation slot/height ahead gate is active (0/1)",
                "# TYPE abs_p2p_native_attestation_slot_ahead gauge",
                (
                    f"abs_p2p_native_attestation_slot_ahead{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_attestation_slot_ahead') else 0}"
                ),
                "# HELP abs_p2p_attestation_slot_ahead_rejects_total Attestations refused for slot/target_height above local window",
                "# TYPE abs_p2p_attestation_slot_ahead_rejects_total counter",
                (
                    f"abs_p2p_attestation_slot_ahead_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('attestation_slot_ahead_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_attestation_local_head Whether known-block attestation height match is enforced (0/1)",
                "# TYPE abs_p2p_native_attestation_local_head gauge",
                (
                    f"abs_p2p_native_attestation_local_head{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_attestation_local_head') else 0}"
                ),
                "# HELP abs_p2p_attestation_local_head_rejects_total Attestations refused for local height mismatch",
                "# TYPE abs_p2p_attestation_local_head_rejects_total counter",
                (
                    f"abs_p2p_attestation_local_head_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('attestation_local_head_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_attestation_target_head_bind Whether tip-height attestation must cite local tip (0/1)",
                "# TYPE abs_p2p_native_attestation_target_head_bind gauge",
                (
                    f"abs_p2p_native_attestation_target_head_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_attestation_target_head_bind') else 0}"
                ),
                "# HELP abs_p2p_attestation_target_head_rejects_total Tip-height attestations refused for non-tip target_hash",
                "# TYPE abs_p2p_attestation_target_head_rejects_total counter",
                (
                    f"abs_p2p_attestation_target_head_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('attestation_target_head_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_block_solicit_only Whether unsolicited block/blocks responses are rejected (0/1)",
                "# TYPE abs_p2p_native_block_solicit_only gauge",
                (
                    f"abs_p2p_native_block_solicit_only{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_block_solicit_only') else 0}"
                ),
                "# HELP abs_p2p_unsolicited_block_rejects_total Unsolicited MSG_BLOCK/MSG_BLOCKS rejects",
                "# TYPE abs_p2p_unsolicited_block_rejects_total counter",
                (
                    f"abs_p2p_unsolicited_block_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('unsolicited_block_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_state_root_solicit_only Whether unsolicited state_root_response is rejected (0/1)",
                "# TYPE abs_p2p_native_state_root_solicit_only gauge",
                (
                    f"abs_p2p_native_state_root_solicit_only{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_state_root_solicit_only') else 0}"
                ),
                "# HELP abs_p2p_native_peers_solicit_only Whether unsolicited MSG_PEERS are rejected (0/1)",
                "# TYPE abs_p2p_native_peers_solicit_only gauge",
                (
                    f"abs_p2p_native_peers_solicit_only{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_peers_solicit_only') else 0}"
                ),
                "# HELP abs_p2p_unsolicited_peers_rejects_total Unsolicited MSG_PEERS rejects",
                "# TYPE abs_p2p_unsolicited_peers_rejects_total counter",
                (
                    f"abs_p2p_unsolicited_peers_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('unsolicited_peers_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_unsolicited_state_root_rejects_total Unsolicited state_root_response rejects",
                "# TYPE abs_p2p_unsolicited_state_root_rejects_total counter",
                (
                    f"abs_p2p_unsolicited_state_root_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('unsolicited_state_root_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_require_head Whether catch-up requires peer.head (0/1)",
                "# TYPE abs_p2p_native_catch_up_require_head gauge",
                (
                    f"abs_p2p_native_catch_up_require_head{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_require_head') else 0}"
                ),
                "# HELP abs_p2p_catch_up_no_head_refuse_total Catch-up refused for height-only claims without peer.head",
                "# TYPE abs_p2p_catch_up_no_head_refuse_total counter",
                (
                    f"abs_p2p_catch_up_no_head_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_no_head_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_tip_probe Whether catch-up solicits local-tip state_root first (0/1)",
                "# TYPE abs_p2p_native_catch_up_tip_probe gauge",
                (
                    f"abs_p2p_native_catch_up_tip_probe{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_tip_probe') else 0}"
                ),
                "# HELP abs_p2p_native_catch_up_head_height_bind Whether known peer.head must match claimed height (0/1)",
                "# TYPE abs_p2p_native_catch_up_head_height_bind gauge",
                (
                    f"abs_p2p_native_catch_up_head_height_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_head_height_bind') else 0}"
                ),
                "# HELP abs_p2p_catch_up_head_height_mismatch_total Catch-up refused when local head height disagrees",
                "# TYPE abs_p2p_catch_up_head_height_mismatch_total counter",
                (
                    f"abs_p2p_catch_up_head_height_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_head_height_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_catch_up_tip_probe_refuse_total Catch-up refused after local-tip state_root probe fail",
                "# TYPE abs_p2p_catch_up_tip_probe_refuse_total counter",
                (
                    f"abs_p2p_catch_up_tip_probe_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_tip_probe_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_peer_head_probe Whether catch-up solicits peer.head via get_block_by_hash (0/1)",
                "# TYPE abs_p2p_native_catch_up_peer_head_probe gauge",
                (
                    f"abs_p2p_native_catch_up_peer_head_probe{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_peer_head_probe') else 0}"
                ),
                "# HELP abs_p2p_catch_up_peer_head_probe_refuse_total Catch-up refused after peer.head wire probe fail",
                "# TYPE abs_p2p_catch_up_peer_head_probe_refuse_total counter",
                (
                    f"abs_p2p_catch_up_peer_head_probe_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_peer_head_probe_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_peer_head_parent_bind Whether +1 catch-up peer.head parent must match local tip (0/1)",
                "# TYPE abs_p2p_native_catch_up_peer_head_parent_bind gauge",
                (
                    f"abs_p2p_native_catch_up_peer_head_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_peer_head_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_native_catch_up_tip_head_bind Whether catch-up completion requires tip==peer.head (0/1)",
                "# TYPE abs_p2p_native_catch_up_tip_head_bind gauge",
                (
                    f"abs_p2p_native_catch_up_tip_head_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_tip_head_bind') else 0}"
                ),
                "# HELP abs_p2p_catch_up_tip_head_mismatch_total Catch-up height-complete refused when tip hash != peer.head",
                "# TYPE abs_p2p_catch_up_tip_head_mismatch_total counter",
                (
                    f"abs_p2p_catch_up_tip_head_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_tip_head_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_contiguous_parent_bind Whether +1 catch-up import parent must match tip (0/1)",
                "# TYPE abs_p2p_native_catch_up_contiguous_parent_bind gauge",
                (
                    f"abs_p2p_native_catch_up_contiguous_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_contiguous_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_catch_up_contiguous_parent_mismatch_total Catch-up import refused when +1 parent != tip",
                "# TYPE abs_p2p_catch_up_contiguous_parent_mismatch_total counter",
                (
                    f"abs_p2p_catch_up_contiguous_parent_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_contiguous_parent_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_catch_up_height_continuity_bind Whether catch-up import height must equal sync cursor (0/1)",
                "# TYPE abs_p2p_native_catch_up_height_continuity_bind gauge",
                (
                    f"abs_p2p_native_catch_up_height_continuity_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_catch_up_height_continuity_bind') else 0}"
                ),
                "# HELP abs_p2p_catch_up_height_continuity_mismatch_total Catch-up import refused when body height != expected cursor",
                "# TYPE abs_p2p_catch_up_height_continuity_mismatch_total counter",
                (
                    f"abs_p2p_catch_up_height_continuity_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('catch_up_height_continuity_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_fork_peer_head_probe Whether same-height fork solicits peer.head first (0/1)",
                "# TYPE abs_p2p_native_fork_peer_head_probe gauge",
                (
                    f"abs_p2p_native_fork_peer_head_probe{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_fork_peer_head_probe') else 0}"
                ),
                "# HELP abs_p2p_fork_peer_head_probe_refuse_total Same-height fork refused after peer.head wire probe fail",
                "# TYPE abs_p2p_fork_peer_head_probe_refuse_total counter",
                (
                    f"abs_p2p_fork_peer_head_probe_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('fork_peer_head_probe_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_fork_peer_head_parent_bind Whether same-height fork requires peer.head parent==tip parent (0/1)",
                "# TYPE abs_p2p_native_fork_peer_head_parent_bind gauge",
                (
                    f"abs_p2p_native_fork_peer_head_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_fork_peer_head_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_native_reconcile_head_hash_bind Whether reconcile refuses fetched head hash mismatch (0/1)",
                "# TYPE abs_p2p_native_reconcile_head_hash_bind gauge",
                (
                    f"abs_p2p_native_reconcile_head_hash_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_reconcile_head_hash_bind') else 0}"
                ),
                "# HELP abs_p2p_reconcile_head_hash_mismatch_total Reconcile refused when fetched block hash != target_head",
                "# TYPE abs_p2p_reconcile_head_hash_mismatch_total counter",
                (
                    f"abs_p2p_reconcile_head_hash_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('reconcile_head_hash_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_ghost_head_probe Whether GHOST reorg solicits canonical head first (0/1)",
                "# TYPE abs_p2p_native_ghost_head_probe gauge",
                (
                    f"abs_p2p_native_ghost_head_probe{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_ghost_head_probe') else 0}"
                ),
                "# HELP abs_p2p_ghost_head_probe_refuse_total GHOST reorg refused after canonical head wire probe fail",
                "# TYPE abs_p2p_ghost_head_probe_refuse_total counter",
                (
                    f"abs_p2p_ghost_head_probe_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('ghost_head_probe_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_ghost_head_parent_bind Whether GHOST reorg requires head parent==tip parent (0/1)",
                "# TYPE abs_p2p_native_ghost_head_parent_bind gauge",
                (
                    f"abs_p2p_native_ghost_head_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_ghost_head_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_native_reconcile_contiguous_parent_bind Whether +1 reconcile requires parent==local tip (0/1)",
                "# TYPE abs_p2p_native_reconcile_contiguous_parent_bind gauge",
                (
                    f"abs_p2p_native_reconcile_contiguous_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_reconcile_contiguous_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_reconcile_contiguous_parent_mismatch_total Reconcile refused when +1 head parent != local tip",
                "# TYPE abs_p2p_reconcile_contiguous_parent_mismatch_total counter",
                (
                    f"abs_p2p_reconcile_contiguous_parent_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('reconcile_contiguous_parent_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_reconcile_same_height_parent_bind Whether same-height reconcile requires parent==tip parent (0/1)",
                "# TYPE abs_p2p_native_reconcile_same_height_parent_bind gauge",
                (
                    f"abs_p2p_native_reconcile_same_height_parent_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_reconcile_same_height_parent_bind') else 0}"
                ),
                "# HELP abs_p2p_reconcile_same_height_parent_mismatch_total Reconcile refused when same-height head parent != tip parent",
                "# TYPE abs_p2p_reconcile_same_height_parent_mismatch_total counter",
                (
                    f"abs_p2p_reconcile_same_height_parent_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('reconcile_same_height_parent_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_reconcile_tip_head_bind Whether reconcile success requires tip==target_head (0/1)",
                "# TYPE abs_p2p_native_reconcile_tip_head_bind gauge",
                (
                    f"abs_p2p_native_reconcile_tip_head_bind{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_reconcile_tip_head_bind') else 0}"
                ),
                "# HELP abs_p2p_reconcile_tip_head_mismatch_total Reconcile refused when post-import tip != target_head",
                "# TYPE abs_p2p_reconcile_tip_head_mismatch_total counter",
                (
                    f"abs_p2p_reconcile_tip_head_mismatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('reconcile_tip_head_mismatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_sync_heads_no_invent Whether SyncEngine refuses inventing peer.head from local blocks (0/1)",
                "# TYPE abs_p2p_native_sync_heads_no_invent gauge",
                (
                    f"abs_p2p_native_sync_heads_no_invent{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_sync_heads_no_invent') else 0}"
                ),
                "# HELP abs_p2p_native_sync_state_wire_only Whether sync_state same-height match is wire-only (0/1)",
                "# TYPE abs_p2p_native_sync_state_wire_only gauge",
                (
                    f"abs_p2p_native_sync_state_wire_only{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_sync_state_wire_only') else 0}"
                ),
                "# HELP abs_p2p_native_mempool_cheap_refuse Whether P2P mempool refuses known hashes before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_cheap_refuse gauge",
                (
                    f"abs_p2p_native_mempool_cheap_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_cheap_refuse') else 0}"
                ),
                "# HELP abs_p2p_native_mempool_new_tx_rate_primary Whether new_tx uses primary rate budget (0/1)",
                "# TYPE abs_p2p_native_mempool_new_tx_rate_primary gauge",
                (
                    f"abs_p2p_native_mempool_new_tx_rate_primary{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_new_tx_rate_primary') else 0}"
                ),
                "# HELP abs_p2p_native_tx_sig_before_state Whether validate_transaction verifies sig before DB (0/1)",
                "# TYPE abs_p2p_native_tx_sig_before_state gauge",
                (
                    f"abs_p2p_native_tx_sig_before_state{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_tx_sig_before_state') else 0}"
                ),
                "# HELP abs_p2p_mempool_dup_refuse_total Known-hash mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_dup_refuse_total counter",
                (
                    f"abs_p2p_mempool_dup_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_dup_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_min_fee_refuse Whether P2P refuses fee<min_fee before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_min_fee_refuse gauge",
                (
                    f"abs_p2p_native_mempool_min_fee_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_min_fee_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_fee_refuse_total Low-fee mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_fee_refuse_total counter",
                (
                    f"abs_p2p_mempool_fee_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_fee_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_fee_refuse Whether P2P refuses fee>max_fee before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_fee_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_fee_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_fee_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_fee_high_refuse_total High-fee mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_fee_high_refuse_total counter",
                (
                    f"abs_p2p_mempool_fee_high_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_fee_high_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_gas_refuse Whether P2P refuses gas>evm_gas_limit before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_gas_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_gas_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_gas_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_gas_refuse_total Over-gas mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_gas_refuse_total counter",
                (
                    f"abs_p2p_mempool_gas_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_gas_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_calldata_refuse Whether P2P refuses oversized calldata before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_calldata_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_calldata_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_calldata_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_calldata_refuse_total Oversized-calldata mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_calldata_refuse_total counter",
                (
                    f"abs_p2p_mempool_calldata_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_calldata_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_negative_value_refuse Whether P2P refuses value<0 before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_negative_value_refuse gauge",
                (
                    f"abs_p2p_native_mempool_negative_value_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_negative_value_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_value_refuse_total Negative-value mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_value_refuse_total counter",
                (
                    f"abs_p2p_mempool_value_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_value_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_value_refuse Whether P2P refuses value>max_value before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_value_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_value_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_value_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_value_high_refuse_total High-value mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_value_high_refuse_total counter",
                (
                    f"abs_p2p_mempool_value_high_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_value_high_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_negative_nonce_refuse Whether P2P refuses nonce<0 before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_negative_nonce_refuse gauge",
                (
                    f"abs_p2p_native_mempool_negative_nonce_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_negative_nonce_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_nonce_refuse_total Negative-nonce mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_nonce_refuse_total counter",
                (
                    f"abs_p2p_mempool_nonce_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_nonce_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_nonce_refuse Whether P2P refuses oversized nonce before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_nonce_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_nonce_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_nonce_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_nonce_high_refuse_total Oversized-nonce mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_nonce_high_refuse_total counter",
                (
                    f"abs_p2p_mempool_nonce_high_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_nonce_high_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_negative_fee_refuse Whether P2P refuses fee<0 before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_negative_fee_refuse gauge",
                (
                    f"abs_p2p_native_mempool_negative_fee_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_negative_fee_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_fee_negative_refuse_total Negative-fee mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_fee_negative_refuse_total counter",
                (
                    f"abs_p2p_mempool_fee_negative_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_fee_negative_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_negative_gas_refuse Whether P2P refuses gas<0 before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_negative_gas_refuse gauge",
                (
                    f"abs_p2p_native_mempool_negative_gas_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_negative_gas_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_gas_negative_refuse_total Negative-gas mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_gas_negative_refuse_total counter",
                (
                    f"abs_p2p_mempool_gas_negative_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_gas_negative_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_unparseable_gas_refuse Whether P2P refuses unparseable gas before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_unparseable_gas_refuse gauge",
                (
                    f"abs_p2p_native_mempool_unparseable_gas_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_unparseable_gas_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_gas_unparseable_refuse_total Unparseable-gas mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_gas_unparseable_refuse_total counter",
                (
                    f"abs_p2p_mempool_gas_unparseable_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_gas_unparseable_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_unparseable_value_refuse Whether P2P refuses unparseable value before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_unparseable_value_refuse gauge",
                (
                    f"abs_p2p_native_mempool_unparseable_value_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_unparseable_value_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_value_unparseable_refuse_total Unparseable-value mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_value_unparseable_refuse_total counter",
                (
                    f"abs_p2p_mempool_value_unparseable_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_value_unparseable_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_unparseable_nonce_refuse Whether P2P refuses unparseable nonce before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_unparseable_nonce_refuse gauge",
                (
                    f"abs_p2p_native_mempool_unparseable_nonce_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_unparseable_nonce_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_nonce_unparseable_refuse_total Unparseable-nonce mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_nonce_unparseable_refuse_total counter",
                (
                    f"abs_p2p_mempool_nonce_unparseable_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_nonce_unparseable_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_enabled Whether tip-safety shadow observer is enabled (0/1)",
                "# TYPE abs_tip_safety_shadow_enabled gauge",
                (
                    f"abs_tip_safety_shadow_enabled{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('tip_safety_shadow_enabled') else 0}"
                ),
                "# HELP abs_tip_safety_enforce Whether tip-safety import enforce is enabled (0/1)",
                "# TYPE abs_tip_safety_enforce gauge",
                (
                    f"abs_tip_safety_enforce{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('tip_safety_enforce') else 0}"
                ),
                "# HELP abs_tip_safety_enforce_refuse_total Tip-safety enforce refused imports",
                "# TYPE abs_tip_safety_enforce_refuse_total counter",
                (
                    f"abs_tip_safety_enforce_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_enforce_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_observe_total Tip-safety shadow observations",
                "# TYPE abs_tip_safety_shadow_observe_total counter",
                (
                    f"abs_tip_safety_shadow_observe_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_observe_total', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_accept_total Tip-safety shadow policy accepts",
                "# TYPE abs_tip_safety_shadow_accept_total counter",
                (
                    f"abs_tip_safety_shadow_accept_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_accept_total', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_reject_total Tip-safety shadow policy rejects",
                "# TYPE abs_tip_safety_shadow_reject_total counter",
                (
                    f"abs_tip_safety_shadow_reject_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_reject_total', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_diverge_policy_reject_import_ok Shadow policy reject but import succeeded",
                "# TYPE abs_tip_safety_shadow_diverge_policy_reject_import_ok counter",
                (
                    f"abs_tip_safety_shadow_diverge_policy_reject_import_ok{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_diverge_policy_reject_import_ok', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_diverge_policy_accept_import_fail Shadow policy accept but import failed",
                "# TYPE abs_tip_safety_shadow_diverge_policy_accept_import_fail counter",
                (
                    f"abs_tip_safety_shadow_diverge_policy_accept_import_fail{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_diverge_policy_accept_import_fail', 0) or 0)}"
                ),
                "# HELP abs_tip_safety_shadow_observe_errors Tip-safety shadow observer internal errors",
                "# TYPE abs_tip_safety_shadow_observe_errors counter",
                (
                    f"abs_tip_safety_shadow_observe_errors{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('tip_safety_shadow_observe_errors', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_empty_from_refuse Whether P2P refuses empty from before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_empty_from_refuse gauge",
                (
                    f"abs_p2p_native_mempool_empty_from_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_empty_from_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_empty_from_refuse_total Empty-from mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_empty_from_refuse_total counter",
                (
                    f"abs_p2p_mempool_empty_from_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_empty_from_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_from_refuse Whether P2P refuses oversized from before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_from_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_from_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_from_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_from_size_refuse_total Oversized-from mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_from_size_refuse_total counter",
                (
                    f"abs_p2p_mempool_from_size_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_from_size_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_empty_to_refuse Whether P2P refuses empty to before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_empty_to_refuse gauge",
                (
                    f"abs_p2p_native_mempool_empty_to_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_empty_to_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_empty_to_refuse_total Empty-to mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_empty_to_refuse_total counter",
                (
                    f"abs_p2p_mempool_empty_to_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_empty_to_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_to_refuse Whether P2P refuses oversized to before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_to_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_to_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_to_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_to_size_refuse_total Oversized-to mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_to_size_refuse_total counter",
                (
                    f"abs_p2p_mempool_to_size_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_to_size_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_empty_hash_refuse Whether P2P refuses empty hash before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_empty_hash_refuse gauge",
                (
                    f"abs_p2p_native_mempool_empty_hash_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_empty_hash_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_empty_hash_refuse_total Empty-hash mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_empty_hash_refuse_total counter",
                (
                    f"abs_p2p_mempool_empty_hash_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_empty_hash_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_hash_refuse Whether P2P refuses oversized hash before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_hash_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_hash_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_hash_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_hash_size_refuse_total Oversized-hash mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_hash_size_refuse_total counter",
                (
                    f"abs_p2p_mempool_hash_size_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_hash_size_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_empty_sig_refuse Whether P2P refuses empty signature before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_empty_sig_refuse gauge",
                (
                    f"abs_p2p_native_mempool_empty_sig_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_empty_sig_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_empty_sig_refuse_total Empty-signature mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_empty_sig_refuse_total counter",
                (
                    f"abs_p2p_mempool_empty_sig_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_empty_sig_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_empty_pubkey_refuse Whether P2P refuses empty public_key before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_empty_pubkey_refuse gauge",
                (
                    f"abs_p2p_native_mempool_empty_pubkey_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_empty_pubkey_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_empty_pubkey_refuse_total Empty-pubkey mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_empty_pubkey_refuse_total counter",
                (
                    f"abs_p2p_mempool_empty_pubkey_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_empty_pubkey_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_sig_refuse Whether P2P refuses oversized signature before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_sig_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_sig_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_sig_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_sig_size_refuse_total Oversized-signature mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_sig_size_refuse_total counter",
                (
                    f"abs_p2p_mempool_sig_size_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_sig_size_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_max_pubkey_refuse Whether P2P refuses oversized public_key before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_max_pubkey_refuse gauge",
                (
                    f"abs_p2p_native_mempool_max_pubkey_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_max_pubkey_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_pubkey_size_refuse_total Oversized-pubkey mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_pubkey_size_refuse_total counter",
                (
                    f"abs_p2p_mempool_pubkey_size_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_pubkey_size_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_nonfinite_value_refuse Whether P2P refuses NaN/Inf value before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_nonfinite_value_refuse gauge",
                (
                    f"abs_p2p_native_mempool_nonfinite_value_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_nonfinite_value_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_nonfinite_value_refuse_total Non-finite value mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_nonfinite_value_refuse_total counter",
                (
                    f"abs_p2p_mempool_nonfinite_value_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_nonfinite_value_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_nonfinite_fee_refuse Whether P2P refuses NaN/Inf fee before validate (0/1)",
                "# TYPE abs_p2p_native_mempool_nonfinite_fee_refuse gauge",
                (
                    f"abs_p2p_native_mempool_nonfinite_fee_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_nonfinite_fee_refuse') else 0}"
                ),
                "# HELP abs_p2p_mempool_nonfinite_fee_refuse_total Non-finite fee mempool refuses before validate_transaction",
                "# TYPE abs_p2p_mempool_nonfinite_fee_refuse_total counter",
                (
                    f"abs_p2p_mempool_nonfinite_fee_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('mempool_nonfinite_fee_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_get_blocks_future_refuse Whether GET_BLOCKS refuses from_height>local tip (0/1)",
                "# TYPE abs_p2p_native_get_blocks_future_refuse gauge",
                (
                    f"abs_p2p_native_get_blocks_future_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_get_blocks_future_refuse') else 0}"
                ),
                "# HELP abs_p2p_get_blocks_future_refuse_total GET_BLOCKS empty replies for from_height>local tip",
                "# TYPE abs_p2p_get_blocks_future_refuse_total counter",
                (
                    f"abs_p2p_get_blocks_future_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('get_blocks_future_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_get_block_future_refuse Whether GET_BLOCK refuses height>local tip (0/1)",
                "# TYPE abs_p2p_native_get_block_future_refuse gauge",
                (
                    f"abs_p2p_native_get_block_future_refuse{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_get_block_future_refuse') else 0}"
                ),
                "# HELP abs_p2p_get_block_future_refuse_total GET_BLOCK null replies for height>local tip",
                "# TYPE abs_p2p_get_block_future_refuse_total counter",
                (
                    f"abs_p2p_get_block_future_refuse_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('get_block_future_refuse_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_get_blocks_past_tip_clamp Whether GET_BLOCKS clamps end to local tip (0/1)",
                "# TYPE abs_p2p_native_get_blocks_past_tip_clamp gauge",
                (
                    f"abs_p2p_native_get_blocks_past_tip_clamp{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_get_blocks_past_tip_clamp') else 0}"
                ),
                "# HELP abs_p2p_get_blocks_past_tip_clamp_total GET_BLOCKS ranges clamped to local tip",
                "# TYPE abs_p2p_get_blocks_past_tip_clamp_total counter",
                (
                    f"abs_p2p_get_blocks_past_tip_clamp_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('get_blocks_past_tip_clamp_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_mempool_serve_tip_align Whether GET_MEMPOOL requires near tip alignment (0/1)",
                "# TYPE abs_p2p_native_mempool_serve_tip_align gauge",
                (
                    f"abs_p2p_native_mempool_serve_tip_align{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_mempool_serve_tip_align') else 0}"
                ),
                "# HELP abs_p2p_get_mempool_tip_misaligned_total GET_MEMPOOL dumps refused for far peer tip",
                "# TYPE abs_p2p_get_mempool_tip_misaligned_total counter",
                (
                    f"abs_p2p_get_mempool_tip_misaligned_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('get_mempool_tip_misaligned_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_heads_skipped_no_head Peers skipped in request_heads due to empty peer.head",
                "# TYPE abs_p2p_heads_skipped_no_head gauge",
                (
                    f"abs_p2p_heads_skipped_no_head{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('heads_skipped_no_head', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_bootstrap_resilient Whether missing-bootstrap redial is active (0/1)",
                "# TYPE abs_p2p_native_bootstrap_resilient gauge",
                (
                    f"abs_p2p_native_bootstrap_resilient{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_bootstrap_resilient') else 0}"
                ),
                "# HELP abs_p2p_bootstrap_redial_total Bootstrap redial attempts for missing seeds",
                "# TYPE abs_p2p_bootstrap_redial_total counter",
                (
                    f"abs_p2p_bootstrap_redial_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('bootstrap_redial_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_bootstrap_missing_count Configured bootstrap peers not currently covered",
                "# TYPE abs_p2p_bootstrap_missing_count gauge",
                (
                    f"abs_p2p_bootstrap_missing_count{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('bootstrap_missing_count', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_bootstrap_pin_gate Whether per-seed TLS bootstrap pins are active (0/1)",
                "# TYPE abs_p2p_native_bootstrap_pin_gate gauge",
                (
                    f"abs_p2p_native_bootstrap_pin_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_bootstrap_pin_gate') else 0}"
                ),
                "# HELP abs_p2p_bootstrap_pin_rejects_total Bootstrap seed TLS pin mismatches",
                "# TYPE abs_p2p_bootstrap_pin_rejects_total counter",
                (
                    f"abs_p2p_bootstrap_pin_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('bootstrap_pin_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_bootstrap_pins_configured Number of host:port bootstrap pins configured",
                "# TYPE abs_p2p_bootstrap_pins_configured gauge",
                (
                    f"abs_p2p_bootstrap_pins_configured{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('bootstrap_pins_configured', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_discovery_dialability_gate Whether discovery dialability gate is active (0/1)",
                "# TYPE abs_p2p_native_discovery_dialability_gate gauge",
                (
                    f"abs_p2p_native_discovery_dialability_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_discovery_dialability_gate') else 0}"
                ),
                "# HELP abs_p2p_discovery_dial_rejects_total discovery dial targets rejected by policy",
                "# TYPE abs_p2p_discovery_dial_rejects_total counter",
                (
                    f"abs_p2p_discovery_dial_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('discovery_dial_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_handshake_head_semantic_gate Whether handshake head soft-binding gate is active (0/1)",
                "# TYPE abs_p2p_native_handshake_head_semantic_gate gauge",
                (
                    f"abs_p2p_native_handshake_head_semantic_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_handshake_head_semantic_gate') else 0}"
                ),
                "# HELP abs_p2p_handshake_head_rejects_total handshake head soft-binding rejects",
                "# TYPE abs_p2p_handshake_head_rejects_total counter",
                (
                    f"abs_p2p_handshake_head_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('handshake_head_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_status_height_head_gate Whether status height↔head soft-binding gate is active (0/1)",
                "# TYPE abs_p2p_native_status_height_head_gate gauge",
                (
                    f"abs_p2p_native_status_height_head_gate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_status_height_head_gate') else 0}"
                ),
                "# HELP abs_p2p_status_height_head_rejects_total status height↔head soft-binding rejects",
                "# TYPE abs_p2p_status_height_head_rejects_total counter",
                (
                    f"abs_p2p_status_height_head_rejects_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('status_height_head_rejects_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_message_loop_dispatch_total Dispatch events from native loop shell",
                "# TYPE abs_p2p_native_message_loop_dispatch_total counter",
                (
                    f"abs_p2p_native_message_loop_dispatch_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_message_loop_dispatch_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_message_loop_strikes_total Strike events from native loop shell",
                "# TYPE abs_p2p_native_message_loop_strikes_total counter",
                (
                    f"abs_p2p_native_message_loop_strikes_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_message_loop_strikes_total', 0) or 0)}"
                ),
                "# HELP abs_p2p_native_shape_revalidate Whether Python dual shape re-validate is active (0=native skipped)",
                "# TYPE abs_p2p_native_shape_revalidate gauge",
                (
                    f"abs_p2p_native_shape_revalidate{{node_id=\"{node_id}\"}} "
                    f"{1 if p2p_security.get('native_shape_revalidate') else 0}"
                ),
                "# HELP abs_p2p_native_read_batch Configured native read_messages batch size",
                "# TYPE abs_p2p_native_read_batch gauge",
                (
                    f"abs_p2p_native_read_batch{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_read_batch') or 0)}"
                ),
                "# HELP abs_p2p_native_write_batch Configured native write batch size",
                "# TYPE abs_p2p_native_write_batch gauge",
                (
                    f"abs_p2p_native_write_batch{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_write_batch') or 0)}"
                ),
                "# HELP abs_p2p_native_read_chunk Configured native read chunk bytes",
                "# TYPE abs_p2p_native_read_chunk gauge",
                (
                    f"abs_p2p_native_read_chunk{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_read_chunk') or 0)}"
                ),
                "# HELP abs_p2p_native_io_timeout_ms Configured native socket I/O timeout (ms)",
                "# TYPE abs_p2p_native_io_timeout_ms gauge",
                (
                    f"abs_p2p_native_io_timeout_ms{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_io_timeout_ms') or 0)}"
                ),
                "# HELP abs_p2p_native_accept_total Native TCP accepts",
                "# TYPE abs_p2p_native_accept_total counter",
                (
                    f"abs_p2p_native_accept_total{{node_id=\"{node_id}\"}} "
                    f"{int(p2p_security.get('native_accept_total', 0) or 0)}"
                ),
            ]
        )
        for kernel in native_crypto.get("kernels", []):
            safe_kernel = str(kernel).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(
                f"abs_native_crypto_kernel_enabled{{node_id=\"{node_id}\",kernel=\"{safe_kernel}\"}} 1"
            )
        # ADR 0019 Slice Z: optional libp2p lab series from security status block.
        libp2p_block = p2p_security.get("libp2p")
        if isinstance(libp2p_block, dict):
            try:
                from network.transport.libp2p_adapter.prometheus_export import (
                    append_libp2p_prometheus_lines,
                )

                append_libp2p_prometheus_lines(
                    lines, libp2p_block, node_id=node_id
                )
            except Exception:
                # Fail-open for /metrics scrape — never break industrial series.
                pass
        return "\n".join(lines) + "\n"

    @staticmethod
    def _wire_probe_ok_gauge(sync_status: Optional[dict[str, Any]]) -> int:
        """Prometheus value: -1 never probed, 0 failed, 1 ok."""
        status = sync_status or {}
        if not bool(status.get("wire_probe_probed")):
            return -1
        return 1 if bool(status.get("wire_probe_ok")) else 0
