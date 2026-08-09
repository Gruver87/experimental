"""ADR 0019 Slice Z — Prometheus export unit tests."""

from __future__ import annotations

import math
import re

from network.transport.libp2p_adapter.prometheus_export import (
    append_libp2p_prometheus_lines,
    render_libp2p_prometheus,
)
from network.transport.libp2p_adapter.status_metrics import empty_libp2p_status_metrics
from observability.metrics import MetricsCollector

_METRIC_LINE = re.compile(
    r"^(?:# (?:HELP|TYPE) .+|[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})? "
    r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)$"
)


def test_render_libp2p_prometheus_empty() -> None:
    assert render_libp2p_prometheus(None) == ""
    assert render_libp2p_prometheus({}) == ""


def test_render_libp2p_prometheus_series_and_honesty() -> None:
    src = empty_libp2p_status_metrics()
    src["feature_libp2p"] = True
    src["default_mesh"] = False
    src["libp2p_dial_ok"] = 3
    src["libp2p_peers"] = 2
    text = render_libp2p_prometheus(src, node_id='n"1')
    assert 'abs_libp2p_feature{node_id="n\\"1"} 1' in text
    assert 'abs_libp2p_default_mesh{node_id="n\\"1"} 0' in text
    assert 'abs_libp2p_dial_ok{node_id="n\\"1"} 3' in text
    assert "# TYPE abs_libp2p_dial_ok counter" in text
    assert "# TYPE abs_libp2p_peers gauge" in text
    for line in text.strip().splitlines():
        assert _METRIC_LINE.match(line), line
        if line.startswith("#"):
            continue
        fval = float(line.rsplit(" ", 1)[-1])
        assert not math.isnan(fval) and not math.isinf(fval)


def test_metrics_collector_hooks_libp2p_block() -> None:
    mc = MetricsCollector()
    text = mc.render_prometheus(
        node_id="z1",
        p2p_security={
            "active_bans": 0,
            "libp2p": {
                "feature_libp2p": True,
                "default_mesh": False,
                "libp2p_wire_sent": 9,
            },
        },
    )
    assert "abs_libp2p_feature" in text
    assert 'abs_libp2p_wire_sent{node_id="z1"} 9' in text
    assert 'abs_libp2p_default_mesh{node_id="z1"} 0' in text


def test_append_returns_sample_count() -> None:
    lines: list[str] = []
    n = append_libp2p_prometheus_lines(
        lines,
        {"feature_libp2p": True, "libp2p_peers": 1},
        node_id="a",
    )
    assert n >= 3
    assert any(ln.startswith("abs_libp2p_peers") for ln in lines)
