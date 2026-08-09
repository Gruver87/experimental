"""ADR 0019 Slice Z — Prometheus text export for libp2p_* status metrics.

Honesty: lab/R&D counters only — emitting series ≠ prod mesh is libp2p.
TCP+TLS remains the default industrial mesh.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, MutableSequence, Optional

from network.transport.libp2p_adapter.status_metrics import LIBP2P_STATUS_METRIC_KEYS

# Keys treated as Prometheus counters (monotonic lab totals).
_COUNTER_SUFFIXES: tuple[str, ...] = (
    "_ok",
    "_fail",
    "_sent",
    "_recv",
    "_denied",
    "_discovered",
    "_closes",
    "_attempted",
    "_scheduled",
    "_give_up",
    "_autoblocks",
    "_ticks",
    "_probes",
    "_changes",
    "_success",
    "_reservations",
    "_circuits",
    "_learned",
    "_registers",
    "_discovers",
    "_registrations",
    "_refused_budget",
    "_disconnects",
    "_sets",
)


def _prom_type(key: str) -> str:
    for suf in _COUNTER_SUFFIXES:
        if key.endswith(suf):
            return "counter"
    return "gauge"


def _safe_node_id(node_id: str) -> str:
    return str(node_id or "node-1").replace("\\", "\\\\").replace('"', '\\"')


def _as_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        # bool is int subclass — treat True/False as 1/0 for feature flags only
        # when caller passes them explicitly; skip random bools from capability.
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def append_libp2p_prometheus_lines(
    lines: MutableSequence[str],
    source: Mapping[str, Any] | None,
    *,
    node_id: str = "node-1",
    keys: Iterable[str] = LIBP2P_STATUS_METRIC_KEYS,
) -> int:
    """Append ``abs_libp2p_*`` series from a libp2p status/metrics mapping.

    Returns the number of sample lines written (excluding HELP/TYPE).
    """
    if not source:
        return 0
    nid = _safe_node_id(node_id)
    written = 0

    # Honesty / freeze gauges (always when a libp2p block is present).
    feature = 1 if source.get("feature_libp2p") else (
        1 if any(k in source for k in keys) else 0
    )
    if not feature and not any(k in source for k in keys):
        return 0

    lines.append(
        "# HELP abs_libp2p_feature Whether ADR 0019 libp2p status metrics are present (lab)"
    )
    lines.append("# TYPE abs_libp2p_feature gauge")
    lines.append(f'abs_libp2p_feature{{node_id="{nid}"}} {1 if feature else 0}')
    written += 1

    default_mesh = source.get("default_mesh")
    mesh_val = 0
    if default_mesh is not None:
        mesh_val = 1 if bool(default_mesh) else 0
    lines.append(
        "# HELP abs_libp2p_default_mesh Must stay 0 — TCP+TLS remains default industrial mesh"
    )
    lines.append("# TYPE abs_libp2p_default_mesh gauge")
    lines.append(f'abs_libp2p_default_mesh{{node_id="{nid}"}} {mesh_val}')
    written += 1

    for key in keys:
        if key not in source:
            continue
        num = _as_number(source.get(key))
        if num is None:
            continue
        # Metric name: libp2p_peers → abs_libp2p_peers
        metric = key if key.startswith("abs_") else f"abs_{key}"
        help_txt = f"ADR 0019 lab metric {key} (not prod mesh cutover)"
        mtype = _prom_type(key)
        lines.append(f"# HELP {metric} {help_txt}")
        lines.append(f"# TYPE {metric} {mtype}")
        # Prefer integer formatting when whole.
        if float(num).is_integer():
            sample = f"{int(num)}"
        else:
            sample = f"{num}"
        lines.append(f'{metric}{{node_id="{nid}"}} {sample}')
        written += 1
    return written


def render_libp2p_prometheus(
    source: Mapping[str, Any] | None,
    *,
    node_id: str = "node-1",
    keys: Iterable[str] = LIBP2P_STATUS_METRIC_KEYS,
) -> str:
    """Render a standalone Prometheus text body for libp2p lab metrics."""
    lines: List[str] = []
    append_libp2p_prometheus_lines(lines, source, node_id=node_id, keys=keys)
    if not lines:
        return ""
    return "\n".join(lines) + "\n"
