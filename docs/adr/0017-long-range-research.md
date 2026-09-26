# ADR 0017 — Long-Range / weak-subjectivity research

- **Status:** Accepted (experimental sandbox only)
- **Date:** 2026-08-08
- **Deciders:** Absolute Blockchain experimental maintainers

## Context

Tip-safety stage-1.5 ships a bounded `AncestryWindow` (ADR 0001 / 0016). That is
**not** Long-Range attack resistance and **not** a tip proof. PoS-style chains
need an explicit weak-subjectivity (WS) story before claiming Long-Range safety.

## Decision

1. Introduce `consensus/long_range/` with ports for **WS anchors** and a
   **stale-fork policy** used only when `FEATURE_LONG_RANGE=true`.
2. Keep industrial prod mesh (`778888`) with `feature_long_range=false`.
3. Lab proof: `scripts/long_range_lab.py` simulates a stale competing history
   below a WS anchor and asserts refuse/accept policy. TipSafety tip-import
   with `FEATURE_LONG_RANGE` attached **HARD REFUSE**s histories below a
   persisted height+hash checkpoint (`ABS_WS_CHECKPOINT_PATH`) and **HARD
   REFUSE**s when the store is empty (`ws_no_anchor`).
4. Do **not** set `finality_quorum_live=true` from this ADR.

## Honesty

- Lab PASS ≠ mainnet Long-Range proof.
- Persist is digest-only JSON (not BLS, not a live checkpoint quorum).
- AncestryWindow remains the production tip-safety bound unless the flag is on.
- Audit-pin tree must not enable this flag. Industrial JSON stays `false`.

## Consequences

- New config keys `feature_long_range` / `FEATURE_LONG_RANGE` (default false).
- Industrial gate freezes the flag off on prod mesh JSON.

## Lab 2h harness spec

Separate from industrial prod mesh `778888`. Do **not** use `docker/node.prod.json`.
Operator-only after libp2p 48h PASS (EXECUTION_ORDER Phase 2).

| Item | Value |
|------|--------|
| Profile | `deployment_mode=dev`, `feature_long_range=true` |
| Persist | `ABS_WS_CHECKPOINT_PATH` (digest + optional Ed25519 committee) |
| Seed (empty store once) | `ABS_WS_ANCHOR_HEIGHT` + `ABS_WS_ANCHOR_HASH` or `seed_long_range_lab_ws.py` |
| Compose | `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`) — never `docker/node.prod*.json` |
| Pre-flight | `python scripts/long_range_lab_2h_harness.py` |
| Duration | 2h health watch on **lab** nodes (`hard_fails=0`) |
| 48h | **PASS** [`docs/evidence/runs/lr48pass1/`](../evidence/runs/lr48pass1/) (2026-09-09→11). Prior FAIL [`lr48fail1`](../evidence/runs/lr48fail1/); intensify [`lr2hintensify`](../evidence/runs/lr2hintensify/). Not BLS / not prod arm. |
| Start | `.\scripts\start_soak_long_range_lab.ps1` |

**Solo 2h PASS recorded:** [`docs/evidence/runs/lr2h9f3a/`](../evidence/runs/lr2h9f3a/) (2026-09-03). Digest-only, height=0 — not mesh-industrial.
**Mesh 2h PASS:** [`docs/evidence/runs/lr2hmesh/`](../evidence/runs/lr2hmesh/). **Lab 48h PASS:** [`lr48pass1`](../evidence/runs/lr48pass1/) (B2 closed).

### Decision addendum — lab Ed25519 committee (not BLS)

Lab WS certificates MAY carry an **Ed25519 multi-sig committee** (threshold 2/3 of
configured pubkeys) over the digest payload. Verify before gossip adopt; tip-import
still goes through TipSafety + WS anchor. Prod mesh keeps `feature_long_range=false`.

### Decision addendum — autonomous lab roll-forward (2026-09-26)

Lab mesh MAY roll the WS floor forward mid-soak (`consensus/long_range/roll_forward.py`):

- Miner-only issuance (`mining_enabled`); followers adopt via gossip.
- Pin a **confirmed** ancestor (`ABS_WS_ROLL_CONFIRM`, default 16), not the live tip.
- Defer adopt when cert height is above the local tip (`ahead_of_tip`) so lagging
  nodes cannot brick catch-up under `tip_safety_enforce`.
- Refuse same-height / different-digest as `equivocation`.
- `deployment_mode` `prod` **and** `staging` hard-off (env cannot arm).

This is **lab autonomy**, not a live BLS checkpoint quorum and not mainnet proof.

### BLS / aggregate (design-only — not implemented)

BLS12-381 aggregate checkpoints remain **design-only**. Do **not** implement or arm
on prod mesh until a future Decision with native/`blst` tests.

Success criteria for lab 2h: tip-import HARD REFUSE below anchor; persist survives
restart; no prod JSON flag flip.