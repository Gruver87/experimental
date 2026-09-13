# ADR 0021 — Mempool / validation Rust phases (planned)

- **Status:** Accepted — Phase 0+1+2+3 landed
- **Date:** 2026-08-28 (phase-1/2/3 refresh 2026-09-13)
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
   (**met 2026-09-03:** [`3c801b87`](../evidence/runs/3c801b87/))
   ([EXECUTION_ORDER.md](../EXECUTION_ORDER.md) Phase 1).

## Phases

### Phase 0 — Ports (zero behavior change) — **landed 2026-08-28**

- `blockchain/ports.py`: `MempoolPort` documents the public mempool surface.
- `core/components/ports.py`: `TxPipelinePort` remains the validation boundary (not duplicated on `MempoolPort`).
- Gate: `industrial_gate.py` + `tests/unit/test_mempool_port.py` (incl. TxPipelinePort surface); **no mesh change**.
- Call sites **may** keep importing `Mempool` directly until phase 1 adapters land.

### Phase 1 snapshot contract — **landed**

Python supplies a read-only dict at validation time:

```python
{"nonce": int, "balance_sat": int}
```

Rust kernels must not open StoragePort / Rocks. Snapshot is taken **after** signature verify (v1.3.143).

Golden fixtures: `tests/fixtures/adr0021_phase1/` · gate: `tests/unit/test_adr0021_phase1_fixtures.py`.

### Phase 1 — Rust validation kernels — **landed 2026-09-13**

Moved to Rust (PyO3) with Python mirror fallback (ADR 0009 family `mempool_kernel`):

- Field/shape checks (`missing_address`, negative satoshi/gas).
- Fee / balance / nonce check **given a read-only snapshot** `{nonce, balance_sat}` supplied
  by Python from storage at validation time (`mempool_validate_post_sig`).
- Wired in `TxPipeline._validate` after sig verify; maps `insufficient_balance` → `insufficient_funds`.

Python still builds snapshots. EVM deploy admit closed in phase 3 (`mempool_admit_evm_deploy`).
ZK gates remain Python unless a later ADR moves them.
Batch secp remains on existing `verify_secp256k1_sha256_batch` path (not re-homed here).

**Invariant:** signature verification **before** state DB reads (v1.3.143 / industrial_gate).

### Phase 2 — Rust mempool store — **landed 2026-09-13**

- Priority queue (`fee_satoshi`-sorted; ABS `fee` dual-write for wire) in
  `abs_native.MempoolStore` behind `Mempool` /
  `MempoolPort` (ADR 0009 family `mempool_store`).
- Preserve: `chain_prevalidated` / `signature_preverified` in Python; Rust owns
  pending set + sort only.
- Lock order: Python `Mempool.lock` (RLock) **then** Rust `Mutex` — never reverse.
- Python dict fallback when family demoted / native off.

### Phase 3 — EVM deploy admit — **landed 2026-09-13**

- Rust `mempool_admit_evm_deploy` (EOF + unsupported opcode) with Python callback to
  `execution/evm_bytecode_validator.py` (ADR 0009 family `mempool_kernel`).
- Wired in `TxPipeline._validate_evm_deploy_bytecode`.
- Goldens: `pipeline_refuse_deploy_eof.json`, `pipeline_refuse_deploy_bad_opcode.json`.

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
