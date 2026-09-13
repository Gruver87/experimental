# observability/ports.py — ADR 0015 MetricsExporterPort
"""Isolated Prometheus export surface (snapshot DTO + text render)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class MetricsSnapshot:
    """Immutable scrape snapshot — built on the HTTP worker thread."""

    node_id: str = "node-1"
    height: int = 0
    peers: int = 0
    mempool: int = 0
    validators: int = 0
    deployment_mode: str = "dev"
    tps: float = 0.0
    p2p_security_ok: bool = False
    native_crypto: Mapping[str, Any] = field(default_factory=dict)
    bridge_health: Mapping[str, Any] = field(default_factory=dict)
    p2p_security: Mapping[str, Any] = field(default_factory=dict)
    rocksdb_tuning: Mapping[str, Any] = field(default_factory=dict)
    sync_status: Mapping[str, Any] = field(default_factory=dict)
    core_engines: Mapping[str, Any] = field(default_factory=dict)
    ws_stats: Mapping[str, Any] = field(default_factory=dict)
    apply_isolation: Mapping[str, Any] = field(default_factory=dict)
    mempool_store: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class MetricsExporterPort(Protocol):
    """Render a Prometheus text exposition from a MetricsSnapshot."""

    def render(self, snapshot: MetricsSnapshot) -> str:
        ...


def compute_tps_from_chain_metrics(chain_metrics: Optional[Mapping[str, Any]]) -> float:
    """Derive TPS from chain window metrics; fail-closed 0 on missing/invalid."""
    if not chain_metrics:
        return 0.0
    try:
        if "tps" in chain_metrics and chain_metrics.get("tps") is not None:
            val = float(chain_metrics.get("tps") or 0)
            if val != val or val in (float("inf"), float("-inf")):  # NaN/Inf
                return 0.0
            return max(0.0, val)
        wtx = chain_metrics.get("window_tx_count")
        wel = chain_metrics.get("window_elapsed_sec")
        if wtx is not None and wel is not None:
            return max(0.0, float(wtx)) / max(float(wel), 1.0)
        avg_bt = float(chain_metrics.get("avg_block_time_sec") or 0)
        tip = int(chain_metrics.get("height") or 0)
        tx_total = int(chain_metrics.get("tx_count") or 0)
        if avg_bt <= 0 or tip <= 0:
            return 0.0
        return max(0.0, (tx_total / tip) / avg_bt)
    except Exception:
        return 0.0


def p2p_security_ok_from_status(p2p_security: Optional[Mapping[str, Any]]) -> bool:
    """True when a live P2P security snapshot was obtained (subsystem present)."""
    if not p2p_security:
        return False
    if "security_ok" in p2p_security:
        return bool(p2p_security.get("security_ok"))
    return "active_bans" in p2p_security or "rate_limit_per_sec" in p2p_security


class NullMetricsExporter:
    """Minimal valid Prometheus body for tests / chaos."""

    def render(self, snapshot: MetricsSnapshot) -> str:
        nid = str(snapshot.node_id or "node-1").replace('"', "")
        return (
            "# HELP abs_metrics_exporter_null Null metrics exporter active\n"
            "# TYPE abs_metrics_exporter_null gauge\n"
            f'abs_metrics_exporter_null{{node_id="{nid}"}} 1\n'
        )


class PrometheusMetricsExporter:
    """Adapter: MetricsCollector.render_prometheus ← MetricsSnapshot."""

    def __init__(self, collector: Any = None) -> None:
        if collector is None:
            from observability.metrics import MetricsCollector

            collector = MetricsCollector()
        self._collector = collector

    def render(self, snapshot: MetricsSnapshot) -> str:
        # Enrich p2p_security with security_ok for gauge emission.
        p2p = dict(snapshot.p2p_security or {})
        p2p["security_ok"] = bool(snapshot.p2p_security_ok)
        return self._collector.render_prometheus(
            height=int(snapshot.height or 0),
            peers=int(snapshot.peers or 0),
            mempool=int(snapshot.mempool or 0),
            validators=int(snapshot.validators or 0),
            deployment_mode=str(snapshot.deployment_mode or "dev"),
            node_id=str(snapshot.node_id or "node-1"),
            native_crypto=dict(snapshot.native_crypto or {}),
            bridge_health=dict(snapshot.bridge_health or {}),
            p2p_security=p2p,
            rocksdb_tuning=dict(snapshot.rocksdb_tuning or {}),
            sync_status=dict(snapshot.sync_status or {}),
            core_engines=dict(snapshot.core_engines or {}),
            ws_stats=dict(snapshot.ws_stats or {}),
            apply_isolation=dict(snapshot.apply_isolation or {}),
            mempool_store=dict(snapshot.mempool_store or {}),
            tps=float(snapshot.tps or 0.0),
        )
