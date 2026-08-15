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
| Clear external addrs | Slice BM: `clear_external_addrs` → count + `external_addr_cleared`; `libp2p_rust_clear_external_addrs_lab.py` |
| Remove external bool | Slice BN: `remove_external_address` → bool + expire only when present; `libp2p_rust_remove_external_addr_lab.py` |
| Add external bool | Slice BO: `add_external_address` → bool + confirm only when newly inserted; `libp2p_rust_add_external_addr_lab.py` |
| Persist advertised externals | Slice BP: operator-advertised JSON (`external_addrs_path` / `ABS_LIBP2P_EXTERNAL_ADDRS_PATH`); restore on start without bumping confirmed; `libp2p_rust_external_addrs_persist_lab.py` |
| Atomic advertised persist | Slice BQ: same-dir `.tmp` + fsync + rename (dest never truncated in place); leftover tmp cleaned; `libp2p_rust_external_addrs_atomic_persist_lab.py` |
| Advertised externals cap | Slice BR: hard max (`MAX_ADVERTISED_EXTERNAL_ADDRS` / `max_advertised_external` / `ABS_LIBP2P_MAX_ADVERTISED_EXTERNAL_ADDRS`); over-limit **refuse** (no silent truncate); `libp2p_rust_external_addrs_max_lab.py` |
| Listen-derived externals cap | Slice BS: listen-derived advertised set under the same ceiling; over-limit `listen()` **refuse**; circuit not counted; `libp2p_rust_listen_derived_external_max_lab.py` |
| Shared advertised cap | Slice BT: **sum** operator + listen-derived ≤ MAX (config may only lower); over-limit listen/add/restore **refuse** (closes the combined-double bypass); `libp2p_rust_advertised_externals_shared_max_lab.py` |
| All-paths advertised cap | Slice BU: observed confirm / UPnP / rendezvous `add_external_address` share the **same** unique budget; over-limit **refuse** (no silent swarm add); `libp2p_rust_advertised_externals_all_paths_max_lab.py` |
| Identify listen-addr cap | Slice BV: Identify omits uncharged listen addrs (libp2p-identify 0.45 has no `hide_listen_addrs`); circuit still advertised; `libp2p_rust_identify_listen_addrs_capped_lab.py` |
| mDNS listen-addr cap | Slice BW: mDNS omits uncharged listen addrs (same shared cap; DNS-SD must not leak over-cap sockets); circuit still advertised; `libp2p_rust_mdns_listen_addrs_capped_lab.py` |
| Kademlia listen-addr cap | Slice BX: Kademlia omits uncharged listen addrs (DHT local/provider addrs must not leak over-cap sockets); circuit still advertised; `libp2p_rust_kad_listen_addrs_capped_lab.py` |
| AutoNAT listen-addr cap | Slice BY: AutoNAT omits uncharged listen addrs (probes must not leak over-cap sockets); circuit still advertised; `libp2p_rust_autonat_listen_addrs_capped_lab.py` |
| UPnP listen-addr cap | Slice BZ: UPnP omits uncharged listen addrs (IGD must not map over-cap sockets); circuit still advertised; `libp2p_rust_upnp_listen_addrs_capped_lab.py` |
| libp2p ExternalAddresses book | Slice CA: advertised unique cap = rust-libp2p `ExternalAddresses` book (20); refuse past 20 (no silent Identify/Kad/Relay eviction); `libp2p_rust_advertised_externals_libp2p_book_max_lab.py` |
| DCUtR candidate cap | Slice CB: DCUtR omits uncharged `NewExternalAddrCandidate` (no hole-punch past advertised cap); circuit still excluded; `libp2p_rust_dcutr_candidates_capped_lab.py` |
| Identify candidate cap | Slice CC: Identify omits uncharged `NewExternalAddrCandidate` at the source (no swarm-wide leak); `libp2p_rust_identify_candidates_capped_lab.py` |
| Persist replace no-unlink | Slice CD: dest replace without unlink-then-rename (`MoveFileExW` on Windows / POSIX `rename`); still not POSIX inode-atomic on NTFS; `libp2p_rust_external_addrs_replace_no_unlink_lab.py` |
| Bootstrap/peerstore atomic persist | Slice CE: bootstrap + learned peerstore JSON use tmp+fsync+replace (no `std::fs::write` truncate); learn-path persist fail rolls back memory; `libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py` |
| Identity keystore atomic create | Slice CF: first-create Ed25519 protobuf key via tmp+fsync+replace; existing/corrupt key refuses spawn (no silent re-mint); `libp2p_rust_identity_atomic_persist_lab.py` |
| Persist parent-dir fsync | Slice CG: fsync parent after replace (POSIX dir fd / Windows `FlushFileBuffers` on directory handle); still not POSIX inode-atomic on NTFS; `libp2p_rust_persist_parent_dir_fsync_lab.py` |
| Identity keystore mode | Slice CH: Unix first-create `0o600`; existing group/other bits refuse spawn (no silent chmod); Windows DACL is Slice CI; `libp2p_rust_identity_key_mode_lab.py` |
| Identity keystore Windows DACL | Slice CI: first-create protected DACL (owner + SYSTEM + Administrators; no Users/Everyone); existing ACLs not rewritten; not POSIX 0600; `libp2p_rust_identity_key_windows_dacl_lab.py` |
| Persist mkdir fsync | Slice CJ: `create_dir_all` then fsync created dirs + first existing ancestor (volume roots skipped); still not POSIX inode-atomic on NTFS; `libp2p_rust_persist_mkdir_fsync_lab.py` |
| Identity first-create exclusive | Slice CK: identity dest create fails if dest exists (Windows MoveFileEx without REPLACE; POSIX hard_link); staging was `dest.{pid}.tmp` (CU: `dest.{pid}.{tid}.tmp`); no race clobber; JSON persist still replaces; `libp2p_rust_identity_create_exclusive_lab.py` |
| Identity tmp restrict at create | Slice CL: identity staging tmp is born restricted (Unix `0o600` at open; Windows `CreateFileW` with protected DACL); leftover tmp locked+unlinked; `libp2p_rust_identity_tmp_dacl_at_create_lab.py` |
| Identity existing ACL refuse | Slice CM: existing key with Users/Everyone (Windows) or group/other bits (Unix) refuses spawn; dest ACL never rewritten; `libp2p_rust_identity_existing_acl_refuse_lab.py` |
| Identity NULL DACL refuse | Slice CN: missing/NULL DACL (Windows grant-everyone) refuses spawn; dest ACL never rewritten; `libp2p_rust_identity_null_dacl_refuse_lab.py` |
| Identity callback ACE refuse | Slice CO: callback/conditional allow ACEs (XA/ZA/XU) and unknown ACE types refuse spawn; dest ACL never rewritten; `libp2p_rust_identity_callback_ace_refuse_lab.py` |
| Identity protected DACL refuse | Slice CP: existing DACL without `SE_DACL_PROTECTED` / SDDL `P` refuses spawn (inheritance cannot add Users); dest ACL never rewritten; `libp2p_rust_identity_protected_dacl_refuse_lab.py` |
| Persist JSON ACL | Slice CQ: JSON persist tmp/dest born restricted (same DACL/0600 as identity tmp); existing JSON not refused at load; `libp2p_rust_persist_json_acl_lab.py` |
| Identity parent-dir refuse | Slice CR: world-writable identity parent (Users write / Unix group-other write; sticky OK) refuses spawn; directory ACL never rewritten; volume roots skipped; `libp2p_rust_identity_parent_dir_refuse_lab.py` |
| Identity parent mkdir recheck | Slice CS: mkdir missing identity parent then recheck ACL (inherit-only ancestor Users write); key not written; directory ACL never rewritten; `libp2p_rust_identity_parent_mkdir_recheck_lab.py` |
| Identity parent unattested refuse | Slice CT: relative key paths resolve against cwd; volume-root parents refuse (no fsync-heuristic skip); `libp2p_rust_identity_parent_unattested_lab.py` |
| Persist tmp per-thread | Slice CU: staging `dest.{pid}.{tid}.tmp` so two threads in one PID do not share tmp; same-thread sequential persist reuses the name (leftover cleanup); dest after concurrent persist is one complete snapshot; JSON persist still last-writer-wins replace (CD); `libp2p_rust_persist_tmp_per_thread_lab.py` |
| Persist tmp stale-tid sweep | Slice CV: unlink stale `dest.{pid}.{otherTid}.tmp` after tokio worker steal; skip in-flight writers; `libp2p_rust_persist_tmp_stale_tid_lab.py` |
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
| BM | Clear external addrs book; `libp2p_rust_clear_external_addrs_lab.py` |
| BN | Remove external addr returns bool; `libp2p_rust_remove_external_addr_lab.py` |
| BO | Add external addr returns bool; `libp2p_rust_add_external_addr_lab.py` |
| BP | Persistent advertised externals JSON; `libp2p_rust_external_addrs_persist_lab.py` |
| BQ | Atomic persist of advertised externals (tmp + fsync + rename); `libp2p_rust_external_addrs_atomic_persist_lab.py` |
| BR | Hard max on advertised externals (refuse over limit); `libp2p_rust_external_addrs_max_lab.py` |
| BS | Same max on listen-derived advertised externals (refuse listen over limit); `libp2p_rust_listen_derived_external_max_lab.py` |
| BT | Shared advertised cap (operator + listen-derived sum ≤ max); `libp2p_rust_advertised_externals_shared_max_lab.py` |
| BU | Observed/UPnP/rendezvous advertise through the same shared cap; `libp2p_rust_advertised_externals_all_paths_max_lab.py` |
| BV | Identify omits uncharged listen addrs (no leak past advertised cap); `libp2p_rust_identify_listen_addrs_capped_lab.py` |
| BW | mDNS omits uncharged listen addrs (no LAN leak past advertised cap); `libp2p_rust_mdns_listen_addrs_capped_lab.py` |
| BX | Kademlia omits uncharged listen addrs (no DHT leak past advertised cap); `libp2p_rust_kad_listen_addrs_capped_lab.py` |
| BY | AutoNAT omits uncharged listen addrs (no probe leak past advertised cap); `libp2p_rust_autonat_listen_addrs_capped_lab.py` |
| BZ | UPnP omits uncharged listen addrs (no IGD map past advertised cap); `libp2p_rust_upnp_listen_addrs_capped_lab.py` |
| CA | advertised unique cap = rust-libp2p ExternalAddresses book (20); 21st refuse (no silent eviction); `libp2p_rust_advertised_externals_libp2p_book_max_lab.py` |
| CB | DCUtR omits uncharged hole-punch candidates (no punch past advertised cap); `libp2p_rust_dcutr_candidates_capped_lab.py` |
| CC | Identify omits uncharged NewExternalAddrCandidate at the source; `libp2p_rust_identify_candidates_capped_lab.py` |
| CD | Persist replace without dest unlink (Windows MoveFileEx); still not POSIX inode-atomic on NTFS; `libp2p_rust_external_addrs_replace_no_unlink_lab.py` |
| CE | Bootstrap + peerstore JSON atomic replace (no truncate-in-place); persist fail rolls back learned addrs; `libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py` |
| CF | Identity keystore first-create via atomic replace; corrupt existing key refuses (no re-mint); `libp2p_rust_identity_atomic_persist_lab.py` |
| CG | Parent-dir fsync after persist replace (POSIX dirent durability); still not POSIX inode-atomic on NTFS; `libp2p_rust_persist_parent_dir_fsync_lab.py` |
| CH | Identity keystore Unix 0o600; world-readable existing key refuses spawn; Windows DACL is Slice CI; `libp2p_rust_identity_key_mode_lab.py` |
| CI | Identity keystore Windows protected DACL (owner+SYSTEM+Admin; no Users/Everyone); `libp2p_rust_identity_key_windows_dacl_lab.py` |
| CJ | Persist mkdir ancestor fsync after create_dir_all; still not POSIX inode-atomic on NTFS; `libp2p_rust_persist_mkdir_fsync_lab.py` |
| CK | Identity first-create exclusive dest + per-process staging tmp (no REPLACE/rename clobber); JSON persist still replaces; `libp2p_rust_identity_create_exclusive_lab.py` |
| CL | Identity tmp born restricted (Windows CreateFile DACL / Unix 0600 at create); leftover tmp locked+unlinked; `libp2p_rust_identity_tmp_dacl_at_create_lab.py` |
| CM | Existing identity weak ACL refuses spawn (no silent chmod/DACL rewrite); `libp2p_rust_identity_existing_acl_refuse_lab.py` |
| CN | Existing identity NULL/absent DACL refuses spawn (Windows grant-everyone); `libp2p_rust_identity_null_dacl_refuse_lab.py` |
| CO | Existing identity callback/conditional allow ACE (XA/ZA/XU) refuses spawn; unknown ACE types refuse; `libp2p_rust_identity_callback_ace_refuse_lab.py` |
| CP | Existing identity unprotected DACL refuses spawn (CI protected-bit at load); `libp2p_rust_identity_protected_dacl_refuse_lab.py` |
| CQ | JSON persist tmp/dest born restricted (Unix 0600 / Windows protected DACL); existing JSON not refused at load; `libp2p_rust_persist_json_acl_lab.py` |
| CR | Identity parent must not grant Users/Everyone write (Windows) or group/other write unless sticky (Unix); spawn refuses; directory ACL never rewritten; `libp2p_rust_identity_parent_dir_refuse_lab.py` |
| CS | Mkdir missing identity parent then recheck ACL (inherit-only ancestor write skipped by CR); key not written; `libp2p_rust_identity_parent_mkdir_recheck_lab.py` |
| CT | Relative identity paths resolve against cwd; volume-root parents refuse (ACL never skipped via fsync heuristic); `libp2p_rust_identity_parent_unattested_lab.py` |
| CU | Persist staging tmp is per-thread (`dest.{pid}.{tid}.tmp`); same-thread name is stable for leftover cleanup; dest after concurrent persist is one complete snapshot; `libp2p_rust_persist_tmp_per_thread_lab.py` |
| CV | Sweep stale other-tid persist tmp; skip in-flight concurrent writers; `libp2p_rust_persist_tmp_stale_tid_lab.py` |

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
  `libp2p_rust_clear_observed_addr_lab.py`,
  `libp2p_rust_clear_external_addrs_lab.py`,
  `libp2p_rust_remove_external_addr_lab.py`,
  `libp2p_rust_add_external_addr_lab.py`,
  `libp2p_rust_external_addrs_persist_lab.py`,
  `libp2p_rust_external_addrs_atomic_persist_lab.py`,
  `libp2p_rust_external_addrs_max_lab.py`,
  `libp2p_rust_listen_derived_external_max_lab.py`,
  `libp2p_rust_advertised_externals_shared_max_lab.py`,
  `libp2p_rust_advertised_externals_all_paths_max_lab.py`,
  `libp2p_rust_identify_listen_addrs_capped_lab.py`,
  `libp2p_rust_mdns_listen_addrs_capped_lab.py`,
  `libp2p_rust_kad_listen_addrs_capped_lab.py`,
  `libp2p_rust_autonat_listen_addrs_capped_lab.py`,
  `libp2p_rust_upnp_listen_addrs_capped_lab.py`,
  `libp2p_rust_advertised_externals_libp2p_book_max_lab.py`,
  `libp2p_rust_dcutr_candidates_capped_lab.py`,
  `libp2p_rust_identify_candidates_capped_lab.py`,
  `libp2p_rust_external_addrs_replace_no_unlink_lab.py`,
  `libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py`,
  `libp2p_rust_identity_atomic_persist_lab.py`,
  `libp2p_rust_persist_parent_dir_fsync_lab.py`,
  `libp2p_rust_identity_key_mode_lab.py`,
  `libp2p_rust_identity_key_windows_dacl_lab.py`,
  `libp2p_rust_persist_mkdir_fsync_lab.py`,
  `libp2p_rust_identity_create_exclusive_lab.py`,
  `libp2p_rust_identity_tmp_dacl_at_create_lab.py`,
  `libp2p_rust_identity_existing_acl_refuse_lab.py`,
  `libp2p_rust_identity_null_dacl_refuse_lab.py`,
  `libp2p_rust_identity_callback_ace_refuse_lab.py`,
  `libp2p_rust_identity_protected_dacl_refuse_lab.py`,
  `libp2p_rust_persist_json_acl_lab.py`,
  `libp2p_rust_identity_parent_dir_refuse_lab.py`,
  `libp2p_rust_identity_parent_mkdir_recheck_lab.py`,
  `libp2p_rust_identity_parent_unattested_lab.py`,
  `libp2p_rust_persist_tmp_per_thread_lab.py`,
  `libp2p_rust_persist_tmp_stale_tid_lab.py`;
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
  Slice BM: clear external addrs (`clear_external_addrs` → count / `external_addr_cleared`).
  Slice BN: remove external addr (`remove_external_address` → bool; expire only when present).
  Slice BO: add external addr (`add_external_address` → bool; confirm only when newly inserted).
  Slice BP: persist operator-advertised externals (`external_addrs_path`; restore loads, does not confirm;
    listen-derived addrs are not written; corrupt JSON fail-closed).
  Slice BQ: atomic persist (same-dir `.tmp` + fsync + rename; dest is not truncated in place).
  Slice CD: Windows dest replace uses `MoveFileExW(REPLACE_EXISTING)` — no
    `remove_file(dest)` window. POSIX `rename` already replaced atomically.
    NTFS replace is still **not** POSIX inode-atomic.
  Slice BR: advertised externals cap (`MAX_ADVERTISED_EXTERNAL_ADDRS`; arg/env may only lower it;
    add and restore **refuse** when over limit — no silent truncate).
  Slice BS: listen-derived advertised set under the same ceiling; over-limit `listen()` **refuse**;
    circuit `/p2p-circuit` listens are not counted. Expansion `NewListenAddr` over cap
    is not advertised (`libp2p_external_addr_limit_refused`); the listener is kept so
    dual-stack siblings are not torn down.
  Slice BT: **shared** budget — unique charged addrs ≤ max (not two
    independent ceilings / combined-double). Over-limit listen, `add_external_address`, and persist
    restore **refuse**. Circuit still excluded.
  Slice BU: observed `confirm_observed_addr` / auto-confirm, UPnP `NewExternalAddr`, and
    rendezvous pre-register `swarm.add_external_address` share that unique budget
    (`aux_advertised_external`). Over-limit **refuse** — no silent swarm advertise.
    Circuit `/p2p-circuit` still excluded.
  Slice BV: Identify must not publish uncharged listen addrs (over-cap expansion
    sockets). rust-libp2p 0.54 / identify 0.45 has no `hide_listen_addrs`; a
    `CappedIdentify` wrapper forwards `NewListenAddr` to Identify only when the
    addr is circuit or charged. Omitted addrs increment `libp2p_identify_listen_addr_omitted`.
  Slice BW: mDNS 0.46 advertises every `NewListenAddr` via DNS-SD. A
    `CappedMdns` wrapper forwards listen addrs only when circuit or charged.
    Omitted addrs increment `libp2p_mdns_listen_addr_omitted`; forwarded count
    is `libp2p_mdns_advertised_listen`. Windows multicast discover remains
    best-effort (Slice AS).
  Slice BX: Kademlia 0.46 fills `ListenAddresses` from every `NewListenAddr`
    and may return them as local provider addrs. A `CappedKad` wrapper forwards
    listen addrs only when circuit or charged. Omitted addrs increment
    `libp2p_kad_listen_addr_omitted`; forwarded count is
    `libp2p_kad_advertised_listen`.
  Slice BY: AutoNAT v1 probes every listen addr. A `CappedAutonat` wrapper
    forwards listen addrs only when circuit or charged. Omitted addrs increment
    `libp2p_autonat_listen_addr_omitted`; forwarded count is
    `libp2p_autonat_advertised_listen`.
  Slice BZ: UPnP 0.3 queues an IGD port map on every `NewListenAddr`
    (Inactive until the gateway is found). A `CappedUpnp` wrapper forwards
    listen addrs only when circuit or charged. Omitted addrs increment
    `libp2p_upnp_listen_addr_omitted`; forwarded count is
    `libp2p_upnp_advertised_listen`.
  Slice CA: rust-libp2p 0.45 `ExternalAddresses` (Identify / Kad / Relay reservation
    tickets) silently evicts the oldest confirmed external past 20. The advertised
    unique cap is therefore 20 (`LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX`); the 21st
    add/listen/restore **refuses** so we do not paint 32 charged addrs while the
    wire book dropped 12. Circuit `/p2p-circuit` still excluded.
  Slice CB: DCUtR 0.12 stores every `NewExternalAddrCandidate` (Identify
    observed / translated listen) and sends them in hole-punch CONNECT. A
    `CappedDcutr` wrapper forwards candidates only when circuit or already
    charged — no aux-admit bypass of the listen cap. Omitted addrs increment
    `libp2p_dcutr_candidate_omitted`; forwarded count is
    `libp2p_dcutr_advertised_candidates`.
  Slice CC: Identify 0.45 emits `ToSwarm::NewExternalAddrCandidate` for every
    observed / translated listen addr (swarm-wide, not only DCUtR). `CappedIdentify`
    poll omits uncharged candidates. Omitted addrs increment
    `libp2p_identify_candidate_omitted`. Circuit still excluded.
  Slice CD: advertised-externals persist no longer unlinks dest before replace.
    Windows: `MoveFileExW(MOVEFILE_REPLACE_EXISTING | WRITE_THROUGH)`. POSIX:
    `rename(2)`. NTFS replace is still **not** POSIX inode-atomic. Capability
    `external_addrs_replace_no_unlink` / `external_addrs_replace_strategy`.
  Slice CE: bootstrap book and learned peerstore used `std::fs::write` (truncate
    dest in place). Both now go through tmp+fsync+replace. A failed peerstore
    persist rolls back the in-memory learn (no silent disk/memory split).
    Identity keystore first-create uses the same atomic replace (Slice CF).
    An existing/corrupt key file **refuses** spawn — it is never overwritten
    with a freshly minted PeerId. NTFS replace remains **not** POSIX inode-atomic.
  Slice CG: after tmp+fsync+replace, fsync the parent directory so the dirent
    survives a crash. POSIX: `fsync` on the directory fd. Windows:
    `CreateFileW(FILE_FLAG_BACKUP_SEMANTICS)` + `FlushFileBuffers`. Capability
    `persist_parent_dir_fsync` / `persist_parent_dir_fsync_strategy`. NTFS
    replace remains **not** POSIX inode-atomic.
  Slice CH: identity keystore first-create uses Unix mode `0o600` on tmp
    before replace. An existing key with group/other bits **refuses** spawn
    (no silent chmod).
  Slice CI: Windows first-create sets a protected DACL (owner + SYSTEM +
    Administrators; no Users/Everyone inherit). Existing Windows ACLs are
    **not** silently rewritten. Capability `identity_key_windows_owner_dacl` /
    `identity_key_mode_strategy=windows_owner_only_dacl`. Not POSIX `0600`.
  Slice CJ: `create_dir_all` of a missing persist parent is followed by fsync
    of created directories and the first existing ancestor (volume roots
    skipped) so a crash cannot drop the new dirent. Capability
    `persist_mkdir_fsync`. NTFS replace remains **not** POSIX inode-atomic.
  Slice CK: identity first-create no longer uses `MoveFileEx(REPLACE_EXISTING)`
    / POSIX `rename` (those clobber dest if it appears after `exists()`).
    Windows: `MoveFileExW` without `MOVEFILE_REPLACE_EXISTING`. POSIX:
    `link(tmp, dest)` then unlink tmp. Staging tmp is `dest.{pid}.tmp` so two
    first-creates do not share the staging file (Slice CU adds `{tid}`).
    Capability `identity_create_exclusive`. JSON persist still replaces (CD).
    NTFS replace remains **not** POSIX inode-atomic.
  Slice CL: identity staging tmp is created already restricted. Unix: `0o600`
    at `open`. Windows: `CreateFileW(CREATE_NEW)` with the protected DACL
    (owner+SYSTEM+Admin) so key bytes are never written under inherited
    Users/Everyone. Leftover tmp is DACL-locked then unlinked before
    CREATE_NEW. Capability `identity_key_tmp_restrict_at_create`. Existing
    dest ACLs are still **not** silently rewritten. Not POSIX `0600` on Windows.
  Slice CM: existing identity is checked at load. Unix: group/other bits
    refuse (CH). Windows: allow ACEs other than owner/SYSTEM/Administrators
    refuse (Users/Everyone). Dest ACL is **never** rewritten. Capability
    `identity_key_existing_acl_refuse`. Operator must fix ACL or mint a new
    keystore. Not POSIX `0600` on Windows.
  Slice CN: a NULL/absent DACL grants everyone on Windows. CM's allow-ACE
    walk would treat that as "no bad ACEs" and load. Spawn now **refuses**.
    Dest ACL is never rewritten. Capability `identity_key_null_dacl_refuse`
    (Windows only). Unix world-readable remains Slice CH.
  Slice CO: CM/CN only walked A/OA allow ACEs. Callback/conditional allow
    ACEs (`XA`/`ZA`/`XU`) still grant Everyone/Users. Spawn now **refuses**
    those and unknown ACE types. Dest ACL is never rewritten. Capability
    `identity_key_callback_ace_refuse` (Windows only). Unix remains Slice CH.
  Slice CP: CI first-create sets `SE_DACL_PROTECTED` (`D:P` / Convert `PAI`).
    Load accepted owner-only ACEs without the protected bit, so a parent
    ACL change could inherit Users onto the key. Spawn now **refuses**.
    Dest ACL is never rewritten. Capability `identity_key_protected_dacl_refuse`
    (Windows only). Unix remains Slice CH.
  Slice CQ: JSON persist still used `File::create` for tmp (inherited
    Users/Everyone). Tmp+dest now use the same restricted create as identity
    (Unix `0o600` / Windows protected DACL). Existing JSON is **not** refused
    at load (not key material). Dest ACL is replaced on persist. Capability
    `persist_json_acl_restrict`. JSON persist still last-writer-wins replace
    (CD). NTFS replace remains **not** POSIX inode-atomic.
  Slice CR: CI–CP lock the key **file**. A world-writable parent still lets
    Users replace/unlink `node.key`. Spawn now **refuses** when the parent
    grants Users/Everyone write/delete-child (Windows) or group/other write
    unless sticky (Unix). Named-user write (including the current user on a
    user Temp dir) is allowed; Users/Everyone/Authenticated Users write is
    not. Directory ACL is **never** rewritten. Volume roots
    are skipped. Capability `identity_key_parent_dir_refuse`. NTFS replace
    remains **not** POSIX inode-atomic.
  Slice CS: CR checked a missing parent by walking to the first existing
    ancestor and skipped inherit-only ACEs. `create_dir_all` then inherited
    Users/group-other write onto the new directory, so the key landed in a
    world-writable parent. Spawn now **mkdir's first** and rechecks the
    created parent. The key is **not** written if that check fails.
    Directory ACL is never rewritten. Capability
    `identity_key_parent_mkdir_recheck`. NTFS replace remains **not** POSIX
    inode-atomic.
  Slice CT: CR/CS reused `should_fsync_dir`, which skips volume roots and
    relative one-component parents (`keystore/node.key`). Identity parent ACL
    is **never** skipped: relative paths resolve against cwd; volume-root
    parents **refuse**. The key is not written. Directory ACL is never
    rewritten. Fsync still skips volume roots. Capability
    `identity_key_parent_unattested_refuse`. NTFS replace remains **not** POSIX
    inode-atomic.
  Slice CU: CK staging `dest.{pid}.tmp` still collides for two threads in
    one process. Staging is now `dest.{pid}.{tid}.tmp`. Same-thread sequential
    persist reuses the name so leftover lock+unlink still works (CL). Dest
    after concurrent persist is one complete snapshot (all of one writer),
    never mixed bytes. JSON persist remains last-writer-wins replace (CD).
    Identity first-create remains exclusive (CK). Persist also unlinks unused
    CK leftover `dest.{pid}.tmp` (Python labs plant that name; persist runs on
    the swarm task thread, not the caller tid). Capability
    `persist_tmp_per_thread`. NTFS replace remains **not** POSIX inode-atomic.
  Slice CV: CU leftover cleanup is same-thread. A crash on tokio worker A
    leaves `dest.{pid}.{tidA}.tmp`; a retry on worker B would miss it.
    Persist now sweeps this-pid staging siblings that are **not** in the
    process in-flight set (so a concurrent writer is not stolen; POSIX unlink
    of an open path would drop the writer's rename). Other-pid tmp is left
    alone. Capability `persist_tmp_stale_tid_sweep`. NTFS replace remains
    **not** POSIX inode-atomic.
  `status_metrics.LIBP2P_STATUS_METRIC_KEYS` shared with `/status`.
- `get_p2p_security_status()["libp2p"]` + `/status` hardening snapshot fields.
- Build: `maturin build --release --features "pyo3/extension-module,libp2p"`.
- CI: experimental-rd job `rd-libp2p-rust`; Hybrid Node Checks default path
  unchanged (no libp2p feature).
- Industrial gate continues to freeze `feature_libp2p=false` on prod mesh JSON.
