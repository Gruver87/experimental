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
    assert "libp2p_bootstrap_peers" in empty
    assert "libp2p_bootstrap_dials_attempted" in empty
    assert "libp2p_reconnect_ok" in empty
    assert "libp2p_gossip_peer_score" in empty
    assert "libp2p_gossip_validation_accept" in empty
    assert "libp2p_gossip_validation_ignore" in empty
    assert "libp2p_gossip_validation_pending" in empty
    assert "libp2p_gossip_defer_validation" in empty
    assert "libp2p_wire_omit_response" in empty
    assert "libp2p_identify_push" in empty
    assert "libp2p_identify_push_requests" in empty
    assert "libp2p_agent_version" in empty
    assert "libp2p_protocol_version" in empty
    assert "libp2p_last_gossip_message_id" in empty
    assert "libp2p_last_gossip_propagation_peer" in empty
    assert "libp2p_ping_ok" in empty
    assert "libp2p_ping_fail_timeout" in empty
    assert "libp2p_ping_fail_unsupported" in empty
    assert "libp2p_ping_fail_other" in empty
    assert "libp2p_ping_interval_ms" in empty
    assert "libp2p_ping_timeout_ms" in empty
    assert "libp2p_ping_unhealthy_disconnects" in empty
    assert "libp2p_score_autoblocks" in empty
    assert "libp2p_score_sweep_ticks" in empty
    assert "libp2p_peerstore_learned" in empty
    assert "libp2p_peerstore_dials_ok" in empty
    assert "libp2p_reconnect_from_peerstore" in empty
    assert "libp2p_idle_connection_timeout_secs" in empty
    assert "libp2p_idle_timeout_closes" in empty
    assert "libp2p_ipv6_listens" in empty
    assert "libp2p_ipv6_dial_ok" in empty
    assert "libp2p_rendezvous_registers" in empty
    assert "libp2p_rendezvous_server_registrations" in empty
    assert "libp2p_dns_dial_ok" in empty
    assert "libp2p_dns_dial_fail" in empty
    assert "libp2p_connection_limits_updates" in empty
    assert "libp2p_quic_listens" in empty
    assert "libp2p_quic_dial_ok" in empty
    assert "libp2p_ws_listens" in empty
    assert "libp2p_ws_dial_ok" in empty
    assert "libp2p_upnp_gateway_not_found" in empty
    assert "libp2p_upnp_external_addrs" in empty
    assert "libp2p_allow_denied" in empty
    assert "libp2p_allowed_peers" in empty
    assert "libp2p_bytes_in" in empty
    assert "libp2p_bytes_out" in empty
    assert "libp2p_external_addr_confirmed" in empty
    assert "libp2p_external_addrs" in empty
    assert "libp2p_inbound_established" in empty
    assert "libp2p_connection_closed" in empty
    assert "libp2p_connection_closed_local" in empty
    assert "libp2p_connection_closed_io" in empty
    assert "libp2p_connection_closed_keep_alive" in empty
    assert "libp2p_new_listen_addr" in empty
    assert "libp2p_listener_closed" in empty
    assert "libp2p_expired_listen_addr" in empty
    assert "libp2p_listener_error" in empty
    assert "libp2p_dialing" in empty
    assert "libp2p_incoming_connection_error" in empty
    assert "libp2p_peer_external_addr" in empty
    assert "libp2p_identify_received" in empty
    assert "libp2p_identify_sent" in empty
    assert "libp2p_identify_pushed" in empty
    assert "libp2p_identify_error" in empty
    assert "libp2p_gossip_peer_subscribed" in empty
    assert "libp2p_gossip_peer_unsubscribed" in empty
    assert "libp2p_kad_query_ok" in empty
    assert "libp2p_kad_query_fail" in empty
    assert "libp2p_kad_inbound_requests" in empty
    assert "libp2p_kad_mode_changed" in empty
    assert "libp2p_wire_outbound_failure" in empty
    assert "libp2p_wire_outbound_fail_dial" in empty
    assert "libp2p_wire_outbound_fail_timeout" in empty
    assert "libp2p_wire_outbound_fail_connection_closed" in empty
    assert "libp2p_wire_outbound_fail_unsupported" in empty
    assert "libp2p_wire_outbound_fail_io" in empty
    assert "libp2p_wire_inbound_fail_timeout" in empty
    assert "libp2p_wire_inbound_fail_connection_closed" in empty
    assert "libp2p_wire_inbound_fail_unsupported" in empty
    assert "libp2p_wire_inbound_fail_response_omission" in empty
    assert "libp2p_wire_inbound_fail_io" in empty
    assert "libp2p_wire_inbound_failure" in empty
    assert "libp2p_wire_response_sent" in empty
    assert "libp2p_wire_response_ok" in empty
    assert "libp2p_relay_reservation_denied" in empty
    assert "libp2p_relay_reservation_timed_out" in empty
    assert "libp2p_relay_circuit_denied" in empty
    assert "libp2p_relay_circuit_closed" in empty
    assert "libp2p_relay_max_reservations" in empty
    assert "libp2p_rendezvous_server_unregistrations" in empty
    assert "libp2p_rendezvous_server_discover_served" in empty
    assert "libp2p_rendezvous_server_discover_not_served" in empty
    assert "libp2p_rendezvous_server_not_registered" in empty
    assert "libp2p_rendezvous_server_registration_expired" in empty
    assert "libp2p_rendezvous_expired" in empty
    assert "libp2p_autonat_inbound_probe" in empty
    assert "libp2p_autonat_outbound_probe" in empty
    assert "libp2p_autonat_inbound_probe_error" in empty
    assert "libp2p_autonat_outbound_probe_error" in empty
    assert "libp2p_mdns_expired" in empty
    assert "libp2p_mdns_ttl_secs" in empty
    assert "libp2p_relay_inbound_circuit" in empty
    assert "libp2p_relay_outbound_circuit" in empty
    assert "libp2p_dial_fail_transport" in empty
    assert "libp2p_dial_fail_wrong_peer_id" in empty
    assert "libp2p_dial_fail_no_addresses" in empty
    assert "libp2p_dial_fail_aborted" in empty
    assert "libp2p_dial_fail_local_peer_id" in empty
    assert "libp2p_dial_fail_condition" in empty
    assert "libp2p_dial_fail_denied" in empty
    assert "libp2p_dial_fail_denied_block" in empty
    assert "libp2p_dial_fail_denied_allow" in empty
    assert "libp2p_dial_fail_denied_limit" in empty
    assert "libp2p_incoming_fail_transport" in empty
    assert "libp2p_incoming_fail_wrong_peer_id" in empty
    assert "libp2p_incoming_fail_aborted" in empty
    assert "libp2p_incoming_fail_local_peer_id" in empty
    assert "libp2p_incoming_fail_denied" in empty
    assert "libp2p_incoming_fail_denied_block" in empty
    assert "libp2p_incoming_fail_denied_allow" in empty
    assert "libp2p_incoming_fail_denied_limit" in empty


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
