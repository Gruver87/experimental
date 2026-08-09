# ADR 0018 — libp2p transport (dual-stack)

- **Status:** Accepted (experimental sandbox only)
- **Date:** 2026-08-08
- **Deciders:** Absolute Blockchain experimental maintainers
- **Follow-on:** Rust industrial swarm path → [ADR 0019](0019-rust-libp2p-industrial.md)

## Context

Production mesh uses native TCP + TLS/mTLS behind ADR 0002 transport ports and
ADR 0008 wire codec. A full libp2p rewrite must not break the industrial default.

## Decision

1. Add `network/transport/libp2p_adapter/` implementing `TransportDialPort` /
   `TransportCapabilityPort` **behind** `FEATURE_LIBP2P`.
2. Default path stays `NativeTransportAdapter` (TCP+TLS).
3. When the flag is on (lab only), dial may use the libp2p adapter; application
   dispatch (`p2p_dispatch`) remains transport-agnostic.
4. Phase-1 adapter may be a capability stub + in-process labs; **rust-libp2p**
   industrial wiring is specified in ADR 0019 (Cargo feature `libp2p`) without
   changing this dual-stack port surface.
5. Industrial compose / prod mesh JSON keep `feature_libp2p=false`.

## Honesty

- «libp2p available behind flag» ≠ «prod mesh is libp2p».
- Wire message types and tip-safety still apply above the transport.

## Consequences

- Config: `feature_libp2p` / `FEATURE_LIBP2P` (default false).
- Labs: `scripts/libp2p_lab_smoke.py`, `libp2p_two_node_lab.py`,
  `libp2p_swarm_lab.py`, `libp2p_three_node_lab.py`, `libp2p_reqresp_lab.py`,
  `libp2p_relay_lab.py`, `libp2p_discovery_lab.py`, `libp2p_identify_lab.py`
  (in-process; not rust-libp2p / gossipsub / Kademlia).
- Industrial gate freezes the flag off on prod mesh JSON.
