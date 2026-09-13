"""Wave E: abs_mempool_store_demoted / demote_count / backend gauges."""

from __future__ import annotations

from observability.metrics import MetricsCollector
from observability.ports import MetricsSnapshot, PrometheusMetricsExporter


def test_mempool_demote_gauges_when_demoted():
    text = MetricsCollector().render_prometheus(
        node_id="n1",
        mempool=3,
        mempool_store={
            "store_demoted": True,
            "demote_count": 2,
            "store_backend": "python",
        },
    )
    assert 'abs_mempool_store_demoted{node_id="n1"} 1' in text
    assert 'abs_mempool_store_demote_count{node_id="n1"} 2' in text
    assert 'abs_mempool_store_backend{node_id="n1",backend="python"} 1' in text


def test_mempool_demote_gauges_when_healthy_rust():
    text = MetricsCollector().render_prometheus(
        node_id="n1",
        mempool_store={
            "store_demoted": False,
            "demote_count": 0,
            "store_backend": "rust",
        },
    )
    assert 'abs_mempool_store_demoted{node_id="n1"} 0' in text
    assert 'abs_mempool_store_demote_count{node_id="n1"} 0' in text
    assert 'abs_mempool_store_backend{node_id="n1",backend="rust"} 1' in text


def test_snapshot_exporter_passes_mempool_store():
    snap = MetricsSnapshot(
        node_id="n2",
        mempool_store={
            "store_demoted": True,
            "demote_count": 1,
            "store_backend": "python",
        },
    )
    text = PrometheusMetricsExporter().render(snap)
    assert 'abs_mempool_store_demoted{node_id="n2"} 1' in text
    assert 'abs_mempool_store_demote_count{node_id="n2"} 1' in text
