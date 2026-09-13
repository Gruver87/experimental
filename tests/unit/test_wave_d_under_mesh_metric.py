"""Wave D: abs_p2p_under_mesh / p2p_sync_status gauges (honesty DX)."""

from __future__ import annotations

from observability.metrics import MetricsCollector


def test_under_mesh_gauge_one_when_flagged():
    text = MetricsCollector().render_prometheus(
        node_id="n1",
        peers=1,
        deployment_mode="prod",
        sync_status={
            "state_consistent": True,
            "wire_probe_ok": True,
            "wire_probe_probed": True,
            "under_mesh": True,
            "p2p_sync_status": "under_mesh",
            "peer_sync_gap": 0,
            "mesh_min_peers": 2,
        },
    )
    assert 'abs_p2p_under_mesh{node_id="n1"} 1' in text
    assert 'abs_p2p_sync_status{node_id="n1",status="under_mesh"} 1' in text
    assert 'abs_p2p_mesh_min_peers{node_id="n1"} 2' in text
    assert 'abs_p2p_peer_sync_gap{node_id="n1"} 0' in text


def test_under_mesh_gauge_zero_when_aligned():
    text = MetricsCollector().render_prometheus(
        node_id="n1",
        peers=2,
        deployment_mode="prod",
        sync_status={
            "under_mesh": False,
            "p2p_sync_status": "aligned",
            "peer_sync_gap": 0,
            "mesh_min_peers": 2,
        },
    )
    assert 'abs_p2p_under_mesh{node_id="n1"} 0' in text
    assert 'abs_p2p_sync_status{node_id="n1",status="aligned"} 1' in text


def test_http_derive_under_mesh_prod():
    from api.http import _derive_p2p_sync_status

    assert (
        _derive_p2p_sync_status(
            peer_count=1,
            peer_gap=0,
            state_consistent=True,
            deployment_mode="prod",
            mesh_min_peers=2,
        )
        == "under_mesh"
    )
    assert (
        _derive_p2p_sync_status(
            peer_count=1,
            peer_gap=5,
            state_consistent=True,
            deployment_mode="prod",
            mesh_min_peers=2,
        )
        == "under_mesh_lagging"
    )
