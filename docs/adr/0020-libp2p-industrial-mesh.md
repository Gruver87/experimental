# ADR 0020 — Experimental industrial libp2p mesh cutover

- **Status:** Accepted (experimental sandbox only)
- **Date:** 2026-08-22
- **Deciders:** Absolute Blockchain experimental maintainers
- **Supersedes (this tree only):** ADR 0018 §5 and ADR 0019 industrial JSON freeze
  (`feature_libp2p=false` on Experimental `778888` prod-profile mesh).
- **Does not apply to:** Hybrid / audit-pin `v1.3.1339-tip-v2-industrial`

## Context

Experimental prod-profile mesh (`chain_id` `778888`) shipped native TCP+TLS/mTLS.
A 48h soak **PASS** exists for that transport:

- Evidence: [`docs/evidence/runs/0a7932c4/`](../evidence/runs/0a7932c4/)
- Window: 2026-08-20 → 2026-08-22
- Bar: `passed=true`, `hard_fails=0`, `hours_elapsed>=48`

That report is **TCP+TLS evidence**. It must not be relabeled as libp2p.

ADR 0018/0019 built rust-libp2p (Noise/Yamux + `/abs/wire`) behind
`FEATURE_LIBP2P`, but the live `P2PNode` path still bound `P2PNativeListener`.
Labs A–DB and `verify_adr0019_libp2p_hard` are not a live L1 mesh.

## Decision

1. Experimental industrial 3-node mesh uses **rust-libp2p** as the data-plane
   transport (Noise XX + Yamux + ADR 0008 `/abs/wire`).
2. Hybrid audit-pin JSON and compose stay TCP+TLS. This ADR is not a Hybrid
   change and is not a public-mainnet claim.
3. Soak bar is unchanged: a libp2p industrial PASS needs a **new** 48h after
   this cutover (`passed=true`, `hard_fails=0`, `hours_elapsed>=48`), packaged
   under `docs/evidence/runs/<image>/` **separate from** `0a7932c4`.
4. Session crypto is **Noise**. Native mTLS overlay
   (`docker-compose.prod.3node.p2ptls.yml`) is not the default for this mesh.
5. `feature_long_range` and `bridge_enabled` stay **false**.
6. Application admit/dispatch stays above transport (ADR 0002 / 0008):
   `p2p_dispatch`, tip-safety, state-root gates.

## Fail-closed invariant

When `feature_libp2p=true`:

- Boot **refuses** if `abs_native.libp2p_available()` is false.
- **No** silent fallback to TCP+TLS (that would paint a green soak that is
  still native).
- Do **not** run `P2PNativeListener` and libp2p forge in parallel (split-brain).
- Prepare-fail on egress is HARD REFUSE (`send_abs_wire` does not encode around
  admit). Inbound garbage is REFUSE, not dispatch.

## Consequences

- Prod Config no longer unconditionally clears `feature_libp2p` (JSON/env may
  enable it on Experimental). `feature_long_range` remains hard-off in prod.
- `docker/node.prod.mesh{1,2,3}.json` set `feature_libp2p: true`.
- Experimental `Dockerfile.prod` builds `abs_native` with Cargo feature
  `libp2p` and asserts `libp2p_available()`.
- Industrial gate on this tree requires mesh JSON `feature_libp2p=true`.
- TCP+TLS soak `0a7932c4` remains historical PASS for native mTLS only.
