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
| NAT traversal | Slice N: AutoNAT + DCUtR; `autonat_add_server`; `libp2p_rust_autonat_dcutr_lab.py` |
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
  `libp2p_rust_abs_wire_lab.py`, `libp2p_rust_autonat_dcutr_lab.py`;
  evidence via `package_libp2p_evidence.py`.
- Python edge: `wire_bridge` (ADR 0008 encode/admit/detect/admit_inbox),
  `Libp2pPeerPolicy` → PeerManager; `adapter.send_abs_wire` / `poll_admit_inbox`;
  `status_metrics.LIBP2P_STATUS_METRIC_KEYS` shared with `/status`.
- `get_p2p_security_status()["libp2p"]` + `/status` hardening snapshot fields.
- Build: `maturin build --release --features "pyo3/extension-module,libp2p"`.
- CI: experimental-rd job `rd-libp2p-rust`; Hybrid Node Checks default path
  unchanged (no libp2p feature).
- Industrial gate continues to freeze `feature_libp2p=false` on prod mesh JSON.
