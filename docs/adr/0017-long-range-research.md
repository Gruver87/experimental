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

## Lab 2h harness spec (not a 48h soak)

**Not started.** Separate from industrial prod mesh `778888`. Do **not** use
`docker/node.prod.json`. Operator-only after libp2p 48h PASS (EXECUTION_ORDER Phase 2).

| Item | Value |
|------|--------|
| Profile | `deployment_mode=dev`, `feature_long_range=true` |
| Persist | `ABS_WS_CHECKPOINT_PATH` (digest-only JSON) |
| Seed (empty store once) | `ABS_WS_ANCHOR_HEIGHT` + `ABS_WS_ANCHOR_HASH` |
| Compose | `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`) + `node.long_range.lab.json` — never `docker/node.prod*.json` |
| Pre-flight | `python scripts/long_range_lab_2h_harness.py` (prod flags + lab compose + LR labs) |
| Duration | 2h health watch on **lab** nodes (`hard_fails=0`, `mesh_warn` documented) |
| 48h | Only after 2h PASS, operator command, separate evidence pack |
| Start gate | `ABS_ALLOW_LR_LAB_2H=1` + `--start-2h` (harness currently **refuses** auto-launch; compose is wired for operator) |

BLS / checkpoint quorum remains **design-only** until this ADR is updated with a signed-cert spec.

### BLS / signed-cert (design-only — not implemented)

Future WS certs would need: committee pubkey set, height+hash digest, threshold
signatures, gossip validation separate from tip import. **Do not** implement or
arm on prod mesh until this section becomes a Decision with tests.

Success criteria for 2h: tip-import still HARD REFUSE below anchor; persist file survives restart bind; no prod JSON flag flip.