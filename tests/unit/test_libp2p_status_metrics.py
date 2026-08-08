"""ADR 0019 Slice J — shared libp2p status metric helpers."""

from __future__ import annotations

from network.transport.libp2p_adapter.status_metrics import (
    LIBP2P_STATUS_METRIC_KEYS,
    empty_libp2p_status_metrics,
    merge_libp2p_status_metrics,
)


def test_empty_metrics_cover_known_keys() -> None:
    empty = empty_libp2p_status_metrics()
    assert set(empty) == set(LIBP2P_STATUS_METRIC_KEYS)
    assert all(v == 0 for v in empty.values())
    assert "libp2p_block_denied" in empty
    assert "libp2p_relay_reservations" in empty
    assert "libp2p_kad_peers" in empty
    assert "libp2p_abs_wire_v2_recv" in empty
    assert "libp2p_autonat_probes" in empty
    assert "libp2p_dcutr_upgrade_success" in empty


def test_merge_overwrites_present_keys_only() -> None:
    block = empty_libp2p_status_metrics()
    block["libp2p_peers"] = 3
    merge_libp2p_status_metrics(
        block,
        {"libp2p_dial_ok": 2, "libp2p_block_denied": 1, "unrelated": 99},
    )
    assert block["libp2p_peers"] == 3
    assert block["libp2p_dial_ok"] == 2
    assert block["libp2p_block_denied"] == 1
    assert "unrelated" not in block
