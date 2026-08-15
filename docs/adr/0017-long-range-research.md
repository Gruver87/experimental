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
