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

## Wire satoshi cutover (2026-09-20 follow-up)

| Fix | Why |
|-----|-----|
| `mempool_wire.py` | Emit `fee_satoshi` / `amount_satoshi` as canonical; ABS floats derived; `WireMoneyMismatch` on dual-write disagree |
| `network/p2p_node.py` ingest | Prefer satoshi; refuse `fee_satoshi_mismatch` / `value_satoshi_mismatch`; legacy float-only still admitted (mixed mesh) |
| `MempoolTransaction.amount_satoshi` | Dual-write on store round-trip |
| Unit + gate needles | `tests/unit/test_adr0021_wire_satoshi_cutover.py` + industrial_gate |

**Not claimed:** mesh probe / 48h re-soak for this cutover. Float display dual-write remains on purpose.

## Persist fail-closed (2026-09-20 follow-up)

| Fix | Why |
|-----|-----|
| `storage.types.PersistError` | Typed fail-closed for hot writes |
| `rocks_store` / `database` / `chain_storage` | `save_block` / `persist_block_atomic` / `save_transaction` / JSON saves raise instead of soft `False` |
| `rocks_adapter.save_block` | Defensive raise if store ever returns False |
| Units + gate + `verify_persist_fail_closed.ps1` | Operator-checkable |

## Cross-check vs deep stub scan

Honesty landmines from the stub/fail-open pass that are **already closed** above: Config/FeatureFlags defaults, industrial JSON, PQ boot string, **wire fee/amount satoshi cutover**.

Still **open CRITICAL/HIGH**: *(none from 2026-09-20 HIGH pack)*. Follow-up P0 **ledger/slash** closed 2026-09-21: engine proposer eject on slash; ATXV/ATXR v2 satoshi; MempoolStore `amount_satoshi` + refuse fee×1e6. Soft persist False (#8–10) **closed** via `PersistError`. Native f64/unwrap (#6–7, #28) **closed** (amount + writeback). Residual float on apply/display edges (#15–17 subset) is dual-write display — not wire authority. Prod mesh libp2p+TLS-off (#13) is **intentional ADR 0020** — document only, do not “fix” to Hybrid TCP+TLS.
Legacy float-only wire admit and soft backup/`copy2` remain MED polish — not reopened as CRITICAL.


## Industrial HIGH honesty (2026-09-21 follow-up)

| Fix | Why | Stub-scan IDs |
|-----|-----|---------------|
| `AdapterValidatorRegistry.mark_slashed` | Raise if adapter+registry slash both fail; RoundSM re-raises | #18 |
| `Mempool._demote_store` | Call `registry.demote` **before** local python mutate (require refuses) | #19–20 |
| `RustBridgeAdapter` reject path | Surface `event_bus_emit_failed` + log.exception (no silent `pass`) | #24 |
| libp2p `connect` without rust | `TransportCapabilityError` — phase-1 stub dial removed | #22 |

Operator: `.\scripts\verify_industrial_high_honesty.ps1`. **Not** mesh probe / **not** 48h soak.

## Do **not** claim fixed (deferred / larger)

| Gap | Class | Note |
|-----|-------|------|
| Soft `return False` on persist (`rocks_store` / SQLite / chain_storage) | **Closed 2026-09-20** | Hot writes raise `PersistError`; ops `backup_to` still soft-bool |
| Rust `amount.rs` / EVM writeback `f64` + some `.unwrap()` | **Closed 2026-09-20** | Decimal fee plan; refuse float `*_satoshi`; writeback via `from_satoshi_float_inner`; map get → typed refuse |
| Long-Range **prod** / BLS / tip-proof | **Park** | Lab 48h only; `feature_long_range=false` on 778888 |
| Bridge L1 enable | **Park** | Stay OFF until audited contracts |
| Full EVM / EIP-4844 / WS subscribe | **Optional** | Subset + mesh soak already proven |
| External audit / ceremony / secret rotation | **Phase 6 org** | Out of code polish |
| PQ NIST backends | **R&D** | Correct NotImplemented refuse |

## Prod mesh honesty

Experimental `docker/node.prod.mesh*.json`: `feature_libp2p=true`, `feature_long_range/oracles/sharding=false`, bridge off. Transport is **ADR 0020 libp2p**, not Hybrid TCP+TLS pin.

## Next ordered polish (if operator continues)

1. Optional tip-safety-enforce soak claim (or keep docs: gate/lab only)
2. Phase 6 audit only when scheduled
3. Residual MED / org items only — HIGH honesty pack closed 2026-09-21
