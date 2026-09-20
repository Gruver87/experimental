# Industrial maximum scan — Experimental (2026-09-20)

**Scope:** Absolute_Blockchain_Experimental only. Not Hybrid audit-pin. Not public mainnet.
**Method:** repo-wide stub/TODO/fail-open/money/float/feature-default scan + gap docs + ADR residual.
**Soak:** not re-run this scan.

## Verdict

Phases **1–4 closed** with real 48h packs (`3c801b87`, `lr48pass1`, `evm48pass1`, `mempool48pass1`) + Phase 5 lab re-verify (`phase5reverify1`). That is the **R&D industrial ceiling** of this sandbox — not BFT/mainnet/bridge L1.

## Landed this polish wave

| Fix | Why | Stub-scan IDs |
|-----|-----|---------------|
| `main.py` PQ boot string | Removed stale `Dilithium=hash-demo` (Wave I is NotImplemented) | #21 |
| `runtime/config.py` sprout defaults | `feature_*` sprouts default **False** (ADR 0016 fail-closed) | #12 |
| `features/__init__.py` FeatureFlags | Same OFF defaults + getattr fallbacks | #26 |
| `node.industrial.json` / `node2.industrial.json` | Bridge OFF, oracles OFF, L1 proof required if bridge armed; honesty name | #11 |

Commit: `7a4ffc9`.

## Cross-check vs deep stub scan

Honesty landmines from the stub/fail-open pass that are **already closed** above: Config/FeatureFlags defaults, industrial JSON, PQ boot string.

Still **open CRITICAL/HIGH** (not in `7a4ffc9`): float ledger/wire/apply (#1–5, #15–17, #27), soft persist False (#8–10), native unwrap/f64 (#6–7, #28), slash best-effort (#18), native demote fallback under require (#19–20), bridge reject swallow (#24), libp2p dial stub honesty (#22). Prod mesh libp2p+TLS-off (#13) is **intentional ADR 0020** — document only, do not “fix” to Hybrid TCP+TLS.
## Do **not** claim fixed (deferred / larger)

| Gap | Class | Note |
|-----|-------|------|
| Wire ABS `fee`/`amount` float (`mempool_wire.py`, apply path, dual-write) | **P0 product** | ADR 0021 residual; dual-write `fee_satoshi` exists; float cutover is a deliberate project |
| Rust `amount.rs` / EVM writeback `f64` + some `.unwrap()` | **P0 native** | Needs typed refuse, not panic |
| Soft `return False` on persist (`rocks_store` / SQLite / chain_storage) | **P0 storage** | Callers must fail-closed |
| Long-Range **prod** / BLS / tip-proof | **Park** | Lab 48h only; `feature_long_range=false` on 778888 |
| Bridge L1 enable | **Park** | Stay OFF until audited contracts |
| Full EVM / EIP-4844 / WS subscribe | **Optional** | Subset + mesh soak already proven |
| External audit / ceremony / secret rotation | **Phase 6 org** | Out of code polish |
| PQ NIST backends | **R&D** | Correct NotImplemented refuse |

## Prod mesh honesty

Experimental `docker/node.prod.mesh*.json`: `feature_libp2p=true`, `feature_long_range/oracles/sharding=false`, bridge off. Transport is **ADR 0020 libp2p**, not Hybrid TCP+TLS pin.

## Next ordered polish (if operator continues)

1. Wire fee/amount satoshi cutover (largest money honesty seam)
2. Persist fail-closed (raise instead of soft False on hot write)
3. Native amount/EVM writeback typed errors
4. Optional tip-safety-enforce soak claim (or keep docs: gate/lab only)
5. Phase 6 audit only when scheduled
