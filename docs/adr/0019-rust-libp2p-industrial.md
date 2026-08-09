# ADR 0019 — rust-libp2p industrial path (experimental)

- **Status:** Accepted (experimental sandbox only)
- **Date:** 2026-08-08
- **Deciders:** Absolute Blockchain experimental maintainers
- **Supersedes (partially):** Phase-1 stub depth of [ADR 0018](0018-libp2p-transport.md); dual-stack gate of 0018 remains in force

## Context

Profile F labs (ADR 0018) proved dual-stack ports, multiaddr, in-process
swarm, request/response, relay, discovery, and identify **stubs** in Python.
Those labs do **not** provide:

- cryptographic PeerId / Noise secure channels
- real TCP listen/dial + Yamux multiplexing
- industrial I/O suitable for soak / mesh evidence

Production Absolute mesh remains native TCP + TLS/mTLS ([ADR 0002](0002-p2p-transport-boundary.md),
[ADR 0008](0008-hotpath-wire-codec.md)). Audit-pin /
`v1.3.1339-tip-v2-industrial` must not flip transport by accident.

## What we are doing

Raise a **real** rust-libp2p swarm inside `native/abs_native` (optional Cargo
feature `libp2p`), exposed to Python through the existing
`Libp2pTransportAdapter` / `DualStackDialer` surface.

## Why

1. Interoperable P2P identity and secure streams without rewriting
   `p2p_dispatch`.
2. Keep Absolute wire (ADR 0008) as a **protocol on streams**
   (`/abs/wire/1.0.0` in Phase-B), not a gossipsub rewrite.
3. Preserve industrial default TCP+TLS until an explicit cutover ADR.

## Decision

| Topic | Choice |
|-------|--------|
| Mode | Dual-stack; TCP+TLS **remains default** |
| Gate | `FEATURE_LIBP2P` / prod JSON `feature_libp2p=false` |
| Security | Noise XX + Ed25519 PeerId (rust-libp2p standard) — **not** a drop-in for current mTLS peer-cert model |
| Mux | Yamux |
| Absolute wire | Slice A: identify + ping + listen/dial. Slice B: `/abs/wire/1.0.0` request-response (lab frames). Slice C: dial budgets. Slice M: ADR 0008 Absolute codecs (v1 NDJSON / v2 Borsh AB2) over `/abs/wire` + admit |
| Gossipsub | Slice E: signed gossipsub announce (`abs/blocks/1.0.0`); Absolute wire remains request-response — not replaced by gossipsub |
| Identity / discovery | Slice F: protobuf Ed25519 key file (`key_path` / `ABS_LIBP2P_KEY_PATH`); mDNS local discovery (LAN; may be filtered in CI) |
| Kademlia | Slice G: `/absolute/kad/1.0.0` MemoryStore DHT (lab mesh; not IPFS public bootstrap) |
| Relay / limits | Slice H: circuit-relay-v2 (`listen_relay` + circuit dial) + `connection_limits` (`max_established_incoming`) |
| Ban / block-list | Slice I: `allow_block_list` (`block_peer` / `unblock_peer`) + `Libp2pPeerPolicy.sync_block` |
| Status surface | Slice J: shared metric keys → `/status` / hardening snapshot + `adapter.status_snapshot` |
| mDNS hygiene | Slice K: `enable_mdns` / `ABS_LIBP2P_MDNS` Toggle; loopback-only discoveries |
| Wire timeout / adapter | Slice L: `wire_timeout_secs` / `ABS_LIBP2P_WIRE_TIMEOUT_SECS`; adapter kad/relay/block parity |
| ADR 0008 on wire | Slice M: Absolute v1/v2 classify + counters; `send_abs_wire` / admit inbox; `libp2p_rust_abs_wire_lab.py` |
| NAT traversal | Slice N: AutoNAT + DCUtR; `enable_autonat` / `ABS_LIBP2P_AUTONAT` (default off) + explicit `autonat_add_server`; `libp2p_rust_autonat_dcutr_lab.py` |
| Bootstrap book | Slice O: JSON peer book + industrial sequential `bootstrap_dial` (budget/timeout/settle); `libp2p_rust_bootstrap_lab.py` |
| Reconnect | Slice P: bootstrap auto-redial on disconnect with exponential backoff; `libp2p_rust_reconnect_lab.py` |
| Peer score | Slice Q: gossipsub peer scoring + app score hooks; `libp2p_rust_peer_score_lab.py` |
| Ping / liveness | Slice R: ping RTT metrics + unhealthy disconnect policy; `libp2p_rust_ping_lab.py` |
| Score autoblock | Slice S: gossip graylist score → native `block_peer`; `libp2p_rust_score_autoblock_lab.py` |
| Learned peerstore | Slice T: persistent identify/connection peer book + warm `peerstore_dial`; `libp2p_rust_peerstore_lab.py` |
| Peerstore reconnect | Slice U: reconnect policy covers learned peerstore (not only bootstrap); `libp2p_rust_peerstore_reconnect_lab.py` |
| Idle connection timeout | Slice V: `idle_connection_timeout_secs` / `ABS_LIBP2P_IDLE_CONNECTION_TIMEOUT_SECS` + `libp2p_idle_timeout_closes`; `libp2p_rust_idle_timeout_lab.py` |
| IPv6 dual-stack | Slice W: `/ip6/.../tcp/...` listen/dial + `libp2p_ipv6_*` metrics; `libp2p_rust_ipv6_lab.py` |
| Rendezvous | Slice X: server/client register+discover + `libp2p_rendezvous_*` metrics; `libp2p_rust_rendezvous_lab.py` |
| DNS multiaddr | Slice Y: `/dns4|/dns6` parse/dial + rust `dns` transport + `libp2p_dns_dial_*`; `libp2p_rust_dns_lab.py` |
| Prometheus export | Slice Z: `abs_libp2p_*` series on `/metrics` + `adapter.prometheus_text`; `libp2p_rust_prometheus_lab.py` |
| Connection manager | Slice AA: full ConnectionLimits + runtime `set_connection_limits`; `libp2p_rust_connection_manager_lab.py` |
| QUIC | Slice AB: `/udp/.../quic-v1` listen/dial beside TCP + `libp2p_quic_*`; `libp2p_rust_quic_lab.py` |
| WebSocket | Slice AC: `/tcp/.../ws` listen/dial beside TCP/QUIC + `libp2p_ws_*`; `libp2p_rust_websocket_lab.py` |
| UPnP | Slice AD: opt-in IGD mapping (`enable_upnp` / `ABS_LIBP2P_UPNP`) + `libp2p_upnp_*`; `libp2p_rust_upnp_lab.py` |
| Allow-list | Slice AE: opt-in whitelist (`enable_allow_list` / `ABS_LIBP2P_ALLOW_LIST`) + `allow_peer`/`disallow_peer`; `libp2p_rust_allowlist_lab.py` |
| Bandwidth | Slice AF: stream byte counters (`libp2p_bytes_in` / `libp2p_bytes_out` via BandwidthSinks); `libp2p_rust_bandwidth_lab.py` |
| External addrs | Slice AG: confirmed/expired/candidates book + `add_external_address`/`remove_external_address`; `libp2p_rust_external_addr_lab.py` |
| Connection lifecycle | Slice AH: inbound/incoming/closed + establish latency ms; `libp2p_rust_connection_lifecycle_lab.py` |
| Close causes | Slice AI: `connection_closed_{local,io,keep_alive}` taxonomy; `libp2p_rust_connection_close_cause_lab.py` |
| Listener lifecycle | Slice AJ: `new/expired_listen_addr` + `listener_closed/error` + `remove_listener`; `libp2p_rust_listener_lifecycle_lab.py` |
| Connection attempts | Slice AK: `dialing` + `incoming_connection_error` + `peer_external_addr`; `libp2p_rust_connection_attempt_lab.py` |
| Identify events | Slice AL: `identify_{received,sent,pushed,error}` + snap; `libp2p_rust_identify_events_lab.py` |
| Gossip subscriptions | Slice AM: remote subscribe/unsubscribe + `gossip_topic_peers`/`gossip_mesh_peers`; `libp2p_rust_gossip_subscription_lab.py` |
| Kademlia events | Slice AN: `kad_query_{ok,fail}` + routable/inbound/mode counters; `libp2p_rust_kad_events_lab.py` |
| Wire RR events | Slice AO: `wire_{outbound,inbound}_failure` + `response_{sent,ok}`; `libp2p_rust_wire_rr_events_lab.py` |
| Relay events | Slice AP: `relay_{reservation_denied,reservation_timed_out,circuit_denied,circuit_closed}` + `relay_max_reservations`; `libp2p_rust_relay_events_lab.py` |
| Rendezvous events | Slice AQ: `rendezvous_server_{unregistrations,discover_served,...}` + client `rendezvous_expired`; `libp2p_rust_rendezvous_events_lab.py` |
| AutoNAT events | Slice AR: `autonat_{inbound,outbound}_probe` + `_error`; `libp2p_rust_autonat_events_lab.py` |
| mDNS events | Slice AS: `mdns_expired` + `mdns_ttl_secs` override; `libp2p_rust_mdns_events_lab.py` |
| Relay client events | Slice AT: `relay_{inbound,outbound}_circuit`; `libp2p_rust_relay_client_events_lab.py` |
| Dial fail events | Slice AU: `dial_fail_{transport,wrong_peer_id,no_addresses,aborted,local_peer_id,condition}`; `libp2p_rust_dial_fail_events_lab.py` |
| Incoming fail events | Slice AV: `incoming_fail_{transport,wrong_peer_id,aborted,local_peer_id,denied}`; `libp2p_rust_incoming_fail_events_lab.py` |
| Dial deny events | Slice AW: `dial_fail_denied` (+ cause in `block_denied` / `allow_denied` / `conn_limit_denied`); `libp2p_rust_dial_deny_events_lab.py` |
| Deny cause events | Slice AX: `dial_fail_denied_{block,allow,limit}` + `incoming_fail_denied_{block,allow,limit}`; `libp2p_rust_deny_cause_events_lab.py` |
| Ping fail events | Slice AY: `ping_fail_{timeout,unsupported,other}` + `ABS_LIBP2P_PING_{INTERVAL,TIMEOUT}_MS` (`TIMEOUT_MS=0` forces timeout in lab); `libp2p_rust_ping_fail_events_lab.py` |
| Wire fail events | Slice AZ: `wire_outbound_fail_{dial,timeout,connection_closed,unsupported,io}` + inbound taxonomy; `libp2p_rust_wire_fail_events_lab.py` |
| Gossip validation | Slice BA: defer via `ABS_LIBP2P_GOSSIP_DEFER_VALIDATION` + `gossip_validation_{reject,ignore,pending}` / last message id; `libp2p_rust_gossip_validation_lab.py` |
| Wire omit-response | Slice BB: `ABS_LIBP2P_WIRE_OMIT_RESPONSE` → inbound `wire_inbound_fail_response_omission`; `libp2p_rust_wire_omit_response_lab.py` |
| Identify push | Slice BC: `identify_push` API + `ABS_LIBP2P_IDENTIFY_PUSH` / `ABS_LIBP2P_AGENT_VERSION`; `libp2p_rust_identify_push_lab.py` |
| Identify interval | Slice BD: `ABS_LIBP2P_IDENTIFY_INTERVAL_MS` + `identify_error_{timeout,negotiation,apply,io}`; `libp2p_rust_identify_interval_lab.py` |
| Peerstore remove | Slice BE: `peerstore_remove` + `peerstore_removed`; `libp2p_rust_peerstore_remove_lab.py` |
| Peerstore allow-learn | Slice BF: `peerstore_allow_learn` clears forget → re-learn; `libp2p_rust_peerstore_allow_learn_lab.py` |
| Identify observed-addr | Slice BG: `last_observed_addr` / `confirm_observed_addr`; `libp2p_rust_identify_observed_addr_lab.py` |
| Bootstrap remove | Slice BH: `bootstrap_remove` → bool + `bootstrap_removed`; `libp2p_rust_bootstrap_remove_lab.py` |
| Confirm observed auto | Slice BI: `ABS_LIBP2P_CONFIRM_OBSERVED_ADDR` auto-promotes observed addr; `libp2p_rust_confirm_observed_addr_auto_lab.py` |
| Bootstrap clear | Slice BJ: `bootstrap_clear` → peers cleared + `bootstrap_cleared`; `libp2p_rust_bootstrap_clear_lab.py` |
| Peerstore clear | Slice BK: `peerstore_clear` → peers cleared + `peerstore_cleared`; `libp2p_rust_peerstore_clear_lab.py` |
| Clear observed-addr | Slice BL: `clear_observed_addr` → previous value + `observed_addr_cleared`; `libp2p_rust_clear_observed_addr_lab.py` |
| Build | Cargo feature `libp2p` (opt-in); default wheel/CI without feature stays lean |
| Repo | `Gruver87/experimental` only — never audit-pin |

### Slice status

| Slice | Deliverable |
|-------|-------------|
| A | Listen/dial/Noise/Yamux; `libp2p_rust_two_node_lab.py` |
| B | `/abs/wire/1.0.0` + `libp2p_peers` / `libp2p_dial_ok`; wire + 3-node rust labs |
| C | `max_dials` budget + `libp2p_dial_refused_budget`; soak lab |
| D | `/status` libp2p block; ADR 0008 wire bridge; PeerManager ban hooks; mixed dual-stack lab; evidence pack |
| E | Gossipsub publish/subscribe + identify Received; `libp2p_rust_gossip_lab.py` |
| F | Persistent PeerId keystore + mDNS discovery; `libp2p_rust_identity_mdns_lab.py` |
| G | Kademlia DHT + Absolute `new_block` gossip announce admit; kad + abs_announce labs |
| H | Circuit-relay-v2 + connection limits; `libp2p_rust_relay_limits_lab.py` |
| I | Native block-list + policy sync; `libp2p_rust_blocklist_lab.py` |
| J | Status metric surface (G–I counters) + adapter hooks; `libp2p_rust_status_surface_lab.py` |
| K | mDNS Toggle + loopback filter; `libp2p_rust_mdns_toggle_lab.py` |
| L | Wire timeout + adapter API parity; `libp2p_rust_wire_timeout_lab.py` |
| M | ADR 0008 v1/v2 over `/abs/wire`; `libp2p_rust_abs_wire_lab.py` |
| N | AutoNAT + DCUtR hole-punch; `libp2p_rust_autonat_dcutr_lab.py` |
| O | Persistent bootstrap JSON + industrial dial settle; `libp2p_rust_bootstrap_lab.py` |
| P | Bootstrap reconnect backoff policy; `libp2p_rust_reconnect_lab.py` |
| Q | Gossipsub peer scoring + app score; `libp2p_rust_peer_score_lab.py` |
| R | Ping RTT + unhealthy disconnect; `libp2p_rust_ping_lab.py` |
| S | Gossip score auto-block; `libp2p_rust_score_autoblock_lab.py` |
| T | Persistent learned peerstore + warm dial; `libp2p_rust_peerstore_lab.py` |
| U | Peerstore reconnect (bootstrap ∪ learned); `libp2p_rust_peerstore_reconnect_lab.py` |
| V | Idle connection timeout policy; `libp2p_rust_idle_timeout_lab.py` |
| W | IPv6 dual-stack listen/dial; `libp2p_rust_ipv6_lab.py` |
| X | Rendezvous register/discover; `libp2p_rust_rendezvous_lab.py` |
| Y | DNS multiaddr dial (`/dns4`/`/dns6`); `libp2p_rust_dns_lab.py` |
| Z | Prometheus `abs_libp2p_*` export; `libp2p_rust_prometheus_lab.py` |
| AA | Connection manager (full limits + runtime set); `libp2p_rust_connection_manager_lab.py` |
| AB | QUIC listen/dial (`quic-v1`); `libp2p_rust_quic_lab.py` |
| AC | WebSocket listen/dial (`/ws`); `libp2p_rust_websocket_lab.py` |
| AD | UPnP / IGD port mapping (opt-in); `libp2p_rust_upnp_lab.py` |
| AE | Allow-list whitelist (opt-in); `libp2p_rust_allowlist_lab.py` |
| AF | Bandwidth byte counters; `libp2p_rust_bandwidth_lab.py` |
| AG | External address book; `libp2p_rust_external_addr_lab.py` |
| AH | Connection lifecycle metrics; `libp2p_rust_connection_lifecycle_lab.py` |
| AI | Connection close-cause taxonomy; `libp2p_rust_connection_close_cause_lab.py` |
| AJ | Listener lifecycle metrics + `remove_listener`; `libp2p_rust_listener_lifecycle_lab.py` |
| AK | Connection attempt metrics (`dialing` / inbound error / peer external addr); `libp2p_rust_connection_attempt_lab.py` |
| AL | Identify event metrics; `libp2p_rust_identify_events_lab.py` |
| AM | Gossip subscription events + mesh peers; `libp2p_rust_gossip_subscription_lab.py` |
| AN | Kademlia event metrics; `libp2p_rust_kad_events_lab.py` |
| AO | Wire request-response event metrics; `libp2p_rust_wire_rr_events_lab.py` |
| AP | Relay event taxonomy metrics; `libp2p_rust_relay_events_lab.py` |
| AQ | Rendezvous event taxonomy metrics; `libp2p_rust_rendezvous_events_lab.py` |
| AR | AutoNAT probe event taxonomy; `libp2p_rust_autonat_events_lab.py` |
| AS | mDNS discover/expire event metrics; `libp2p_rust_mdns_events_lab.py` |
| AT | Relay client circuit direction metrics; `libp2p_rust_relay_client_events_lab.py` |
| AU | Dial failure taxonomy metrics; `libp2p_rust_dial_fail_events_lab.py` |
| AV | Incoming ListenError taxonomy metrics; `libp2p_rust_incoming_fail_events_lab.py` |
| AW | Dial Denied taxonomy metrics; `libp2p_rust_dial_deny_events_lab.py` |
| AX | Denied cause taxonomy (block/allow/limit) by direction; `libp2p_rust_deny_cause_events_lab.py` |
| AY | Ping failure taxonomy metrics; `libp2p_rust_ping_fail_events_lab.py` |
| AZ | Wire RR failure taxonomy metrics; `libp2p_rust_wire_fail_events_lab.py` |
| BA | Deferred gossip validation + ignore/reject outcomes; `libp2p_rust_gossip_validation_lab.py` |
| BB | Wire omit-response lab path (`ResponseOmission`); `libp2p_rust_wire_omit_response_lab.py` |
| BC | Identify push API + agent version + listen-addr push; `libp2p_rust_identify_push_lab.py` |
| BD | Identify interval + error taxonomy; `libp2p_rust_identify_interval_lab.py` |
| BE | Peerstore remove (forget peer); `libp2p_rust_peerstore_remove_lab.py` |
| BF | Peerstore allow-learn (clear forget); `libp2p_rust_peerstore_allow_learn_lab.py` |
| BG | Identify observed-addr + confirm; `libp2p_rust_identify_observed_addr_lab.py` |
| BH | Bootstrap remove (bool + counter); `libp2p_rust_bootstrap_remove_lab.py` |
| BI | Auto-confirm observed-addr; `libp2p_rust_confirm_observed_addr_auto_lab.py` |
| BJ | Bootstrap clear (wipe book + counter); `libp2p_rust_bootstrap_clear_lab.py` |
| BK | Peerstore clear (wipe learned + counter); `libp2p_rust_peerstore_clear_lab.py` |
| BL | Clear observed-addr surface; `libp2p_rust_clear_observed_addr_lab.py` |

## Honesty

- «rust-libp2p compiled behind feature» ≠ «prod mesh is libp2p».
- Lab PASS with `FEATURE_LIBP2P=true` does not authorize industrial compose.
- Do not set `finality_quorum_live` or claim tip proof from this ADR.

## Consequences

- Module: `native/abs_native/src/libp2p_swarm.rs` + PyO3 (`libp2p_available`,
  `Libp2pNode` / `libp2p_node_new`, `send_wire`, `metrics`).
- Labs: `libp2p_rust_two_node_lab.py`, `libp2p_rust_wire_lab.py`,
  `libp2p_rust_three_node_lab.py`, `libp2p_rust_soak_lab.py`,
  `libp2p_mixed_dual_stack_lab.py`, `libp2p_rust_gossip_lab.py`,
  `libp2p_rust_identity_mdns_lab.py`, `libp2p_rust_kad_lab.py`,
  `libp2p_rust_abs_announce_lab.py`, `libp2p_rust_relay_limits_lab.py`,
  `libp2p_rust_blocklist_lab.py`,   `libp2p_rust_status_surface_lab.py`,
  `libp2p_rust_mdns_toggle_lab.py`, `libp2p_rust_wire_timeout_lab.py`,
  `libp2p_rust_abs_wire_lab.py`, `libp2p_rust_autonat_dcutr_lab.py`,
  `libp2p_rust_bootstrap_lab.py`,   `libp2p_rust_reconnect_lab.py`,
  `libp2p_rust_peer_score_lab.py`, `libp2p_rust_ping_lab.py`,
  `libp2p_rust_score_autoblock_lab.py`, `libp2p_rust_peerstore_lab.py`,
  `libp2p_rust_peerstore_reconnect_lab.py`, `libp2p_rust_idle_timeout_lab.py`,
  `libp2p_rust_ipv6_lab.py`, `libp2p_rust_rendezvous_lab.py`,
  `libp2p_rust_dns_lab.py`,   `libp2p_rust_prometheus_lab.py`,
  `libp2p_rust_connection_manager_lab.py`, `libp2p_rust_quic_lab.py`,
  `libp2p_rust_websocket_lab.py`, `libp2p_rust_upnp_lab.py`,
  `libp2p_rust_allowlist_lab.py`, `libp2p_rust_bandwidth_lab.py`,
  `libp2p_rust_external_addr_lab.py`,   `libp2p_rust_connection_lifecycle_lab.py`,
  `libp2p_rust_connection_close_cause_lab.py`,
  `libp2p_rust_listener_lifecycle_lab.py`,
  `libp2p_rust_connection_attempt_lab.py`,
  `libp2p_rust_identify_events_lab.py`,
  `libp2p_rust_gossip_subscription_lab.py`,
  `libp2p_rust_kad_events_lab.py`,
  `libp2p_rust_wire_rr_events_lab.py`,
  `libp2p_rust_relay_events_lab.py`,
  `libp2p_rust_rendezvous_events_lab.py`,
  `libp2p_rust_autonat_events_lab.py`,
  `libp2p_rust_mdns_events_lab.py`,
  `libp2p_rust_relay_client_events_lab.py`,
  `libp2p_rust_dial_fail_events_lab.py`,
  `libp2p_rust_incoming_fail_events_lab.py`,
  `libp2p_rust_dial_deny_events_lab.py`,
  `libp2p_rust_deny_cause_events_lab.py`,
  `libp2p_rust_ping_fail_events_lab.py`,
  `libp2p_rust_wire_fail_events_lab.py`,
  `libp2p_rust_gossip_validation_lab.py`,
  `libp2p_rust_wire_omit_response_lab.py`,
  `libp2p_rust_identify_push_lab.py`,
  `libp2p_rust_identify_interval_lab.py`,
  `libp2p_rust_peerstore_remove_lab.py`,
  `libp2p_rust_peerstore_allow_learn_lab.py`,
  `libp2p_rust_identify_observed_addr_lab.py`,
  `libp2p_rust_bootstrap_remove_lab.py`,
  `libp2p_rust_confirm_observed_addr_auto_lab.py`,
  `libp2p_rust_bootstrap_clear_lab.py`,
  `libp2p_rust_peerstore_clear_lab.py`,
  `libp2p_rust_clear_observed_addr_lab.py`;
  evidence via `package_libp2p_evidence.py`.
- Python edge: `wire_bridge` (ADR 0008 encode/admit/detect/admit_inbox),
  `Libp2pPeerPolicy` → PeerManager; `adapter.send_abs_wire` / `poll_admit_inbox`;
  Slice Z: `prometheus_export.render_libp2p_prometheus` → `/metrics`.
  Slice AA: `set_connection_limits` runtime ConnectionLimits mutate.
  Slice AB: `/udp/.../quic-v1` multiaddr + QUIC transport (lab; TCP+TLS default).
  Slice AC: `/tcp/.../ws` multiaddr + WebSocket transport (lab; TCP+TLS default).
  Slice AD: UPnP Toggle + `libp2p_upnp_*` (lab; default off; no gateway → GatewayNotFound).
  Slice AE: allow-list Toggle + `allow_peer`/`disallow_peer` (lab; default off; empty denies all).
  Slice AF: BandwidthSinks → `libp2p_bytes_in`/`libp2p_bytes_out` (lab counters; not prod mesh SLA).
  Slice AG: external address book + `libp2p_external_addr_*` (lab; not NAT proof).
  Slice AH: connection lifecycle counters (`inbound_established`, `connection_closed`, …).
  Slice AI: close-cause taxonomy (`connection_closed_local` / `_io` / `_keep_alive`).
  Slice AJ: listener lifecycle (`new_listen_addr`, `expired_listen_addr`, `listener_closed`/`error`) + `remove_listener`.
  Slice AK: connection attempts (`dialing`, `incoming_connection_error`, `peer_external_addr`).
  Slice AL: identify events (`identify_received` / `_sent` / `_pushed` / `_error`).
  Slice AM: gossip subscription events + `gossip_topic_peers` / `gossip_mesh_peers`.
  Slice AN: Kademlia events (`kad_query_ok`/`_fail`, routable/inbound/mode).
  Slice AO: wire RR events (`wire_outbound_failure`, `wire_response_sent`/`_ok`).
  Slice AP: relay events (`relay_reservation_denied` / `_timed_out`, `relay_circuit_denied` / `_closed`).
  Slice AQ: rendezvous events (`rendezvous_server_discover_served` / `_unregistrations` / …).
  Slice AR: AutoNAT events (`autonat_inbound_probe` / `_outbound_probe` + `_error`).
  Slice AS: mDNS events (`mdns_expired`, `mdns_ttl_secs`).
  Slice AT: relay client events (`relay_inbound_circuit` / `relay_outbound_circuit`).
  Slice AU: dial fail events (`dial_fail_transport` / `_wrong_peer_id` / …).
  Slice AV: incoming fail events (`incoming_fail_denied` / `_transport` / …).
  Slice AW: dial deny events (`dial_fail_denied` + block/allow/limit causes).
  Slice AX: deny cause events (`dial_fail_denied_block` / `incoming_fail_denied_allow` / …).
  Slice AY: ping fail events (`ping_fail_timeout` / `_unsupported` / `_other`).
  Slice AZ: wire fail events (`wire_outbound_fail_dial` / inbound `_timeout` / …).
  Slice BA: gossip validation defer (`gossip_validation_ignore` / `_reject` / pending).
  Slice BB: wire omit-response (`wire_inbound_fail_response_omission` via `ABS_LIBP2P_WIRE_OMIT_RESPONSE`).
  Slice BC: identify push (`identify_push` / `identify_pushed` + `ABS_LIBP2P_AGENT_VERSION`).
  Slice BD: identify interval (`ABS_LIBP2P_IDENTIFY_INTERVAL_MS`) + `identify_error_*` taxonomy.
  Slice BE: peerstore remove (`peerstore_remove` / `peerstore_removed`; runtime forget suppresses re-learn).
  Slice BF: peerstore allow-learn (`peerstore_allow_learn` / clears forget for re-learn).
  Slice BG: identify observed-addr (`last_observed_addr` / `confirm_observed_addr`).
  Slice BH: bootstrap remove (`bootstrap_remove` → bool / `bootstrap_removed`).
  Slice BI: auto-confirm observed-addr (`ABS_LIBP2P_CONFIRM_OBSERVED_ADDR`).
  Slice BJ: bootstrap clear (`bootstrap_clear` → peers cleared / `bootstrap_cleared`).
  Slice BK: peerstore clear (`peerstore_clear` → peers cleared / `peerstore_cleared`;
    cleared peers enter forget set so identify cannot re-learn while connected).
  Slice BL: clear observed-addr (`clear_observed_addr` → previous / `observed_addr_cleared`;
    does not mutate external book).
  `status_metrics.LIBP2P_STATUS_METRIC_KEYS` shared with `/status`.
- `get_p2p_security_status()["libp2p"]` + `/status` hardening snapshot fields.
- Build: `maturin build --release --features "pyo3/extension-module,libp2p"`.
- CI: experimental-rd job `rd-libp2p-rust`; Hybrid Node Checks default path
  unchanged (no libp2p feature).
- Industrial gate continues to freeze `feature_libp2p=false` on prod mesh JSON.
