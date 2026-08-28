# ADR 0021 — Mempool / validation Rust phases (planned)

- **Status:** Accepted (plan only — **no implementation until Phase 1 libp2p 48h PASS**)
- **Date:** 2026-08-28
- **Deciders:** Absolute Blockchain experimental maintainers
- **Execution order:** [EXECUTION_ORDER.md](../EXECUTION_ORDER.md)

## Context

Today:

- **Python** owns `blockchain/mempool.py` (store, fee sort) and
  `core/components/tx_pipeline.py` (semantic validation: nonce, balance, EVM deploy, ZK).
- **Rust** owns P2P ingress gates (wire shape, batch ECDSA, solicit-only mempool shell) in
  `native/abs_native/src/p2p_wire.rs` and `p2p_transport.rs`.
- Comments in Rust explicitly state: *mempool stays Python*; *nonce/balance stay Python*.

ADR 0009 assigns Rust the hot kernels; Python orchestration. ADR 0016 requires a **single
mempool** per node. Moving store + validation to Rust is feasible only **phased**, with
mesh probe evidence after each sub-phase.

## Decision

1. **Do not** big-bang rewrite mempool or `TxPipeline` to Rust.
2. Introduce **`MempoolPort`** in `blockchain/ports.py` (phase 0 — protocol only; Python
   `Mempool` remains canonical until a Rust adapter is proven).
3. Reuse existing **`TxPipelinePort`** in `core/components/ports.py` for validation boundary
   (no duplicate protocol).
4. Register future native family **`mempool_kernel`** in ADR 0009 registry **only when**
   phase 1 ships with Python fallback story.
5. **Start ADR 0021 implementation only after** libp2p 48h soak PASS on Experimental mesh
   ([EXECUTION_ORDER.md](../EXECUTION_ORDER.md) Phase 1).

## Phases

### Phase 0 — Ports (zero behavior change) — **landed 2026-08-28**

- `blockchain/ports.py`: `MempoolPort` documents the public mempool surface.
- `core/components/ports.py`: `TxPipelinePort` remains the validation boundary (not duplicated on `MempoolPort`).
- Gate: `industrial_gate.py` + `tests/unit/test_mempool_port.py` (incl. TxPipelinePort surface); **no mesh change**.
- Call sites **may** keep importing `Mempool` directly until phase 1 adapters land.

### Phase 1 snapshot contract (not implemented)

Python supplies a read-only dict at validation time:

```python
{"nonce": int, "balance_sat": int}
```

Rust kernels must not open StoragePort / Rocks. Snapshot is taken **after** signature verify (v1.3.143). Do not start this phase before libp2p 48h PASS.

### Phase 1 — Rust validation kernels

Move to Rust (PyO3, GIL released where batching):

- Field/shape checks (consolidate cheap P2P refuses + field rules).
- Batch secp256k1 (extend existing `verify_secp256k1_sha256_batch_nogil`).
- Fee / balance / nonce check **given a read-only snapshot** `{nonce, balance_sat}` supplied
  by Python from `StoragePort` at validation time.

Python still builds snapshots and owns EVM deploy + ZK gates unless phase 3 closes them.

**Invariant:** signature verification **before** state DB reads (v1.3.143 / industrial_gate).

### Phase 2 — Rust mempool store (optional)

- Priority queue (fee-sorted) behind `MempoolPort` Rust adapter.
- Preserve: `chain_prevalidated` / `signature_preverified` semantics, `threading.RLock` or
  documented Rust lock model compatible with asyncio P2P.

### Phase 3 — EVM deploy admit

- Rust opcode scan **or** PyO3 callback to `execution/evm_bytecode_validator.py`.
- Golden tests must match Python validator output.

## Invariants (non-negotiable)

| Invariant | Source |
|-----------|--------|
| Fail-closed refuse | fail-closed.mdc |
| Sig before DB reads | `TxPipeline._validate`, industrial_gate v1.3.143 |
| Satoshi integers on validation path | `runtime/amount.py`, TxPipeline |
| `expected_nonce` for block assembly | `validate_for_block` |
| Solicit-only `MSG_MEMPOOL` | p2p_transport v1.3.144 |
| Mempool remove only after successful import | v1.3.66 |
| Prod EVM deploy via mempool only | `api/http.py` |
| Single mempool | ADR 0016 |
| Python boot without native (`auto`/`off`) | ADR 0009 |

## Verification (each sub-phase)

Windows L1 integration gate (mandatory for phase 1+):

```powershell
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes
.\scripts\probe_prod_mesh.ps1 -Quick
python scripts/industrial_gate.py
python scripts/evm_mempool_load_harness.py
python scripts/prod_evm_smoke.py
```

Pytest alone is **not** acceptance for mempool/P2P changes.

## Honesty

- Phase 0–3 completion ≠ mainnet readiness.
- Cross-node EVM evidence remains `prod_evm_smoke.py` on live mesh.
- Ultimate Hybrid audit pin is updated only via explicit merge policy — not by this ADR alone.

## Consequences

- `docs/EXECUTION_ORDER.md` lists mempool Rust as **Phase 4** (after libp2p 48h and LR lab soak).
- `PORTING_ROADMAP.md` Priority 10 points here (planned).
- No prod JSON or runtime behavior change until phase 0 adapters are intentionally wired.
