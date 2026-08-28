# Execution order — Experimental R&D (honest)

**Purpose:** single source of truth for *what runs when*. No step claims PASS unless evidence exists.
**Rule:** do not start a later phase while an earlier **blocker** is open.

Last updated: 2026-08-28.

---

## Blockers (open now)

| ID | Blocker | Evidence | Next action |
|----|---------|----------|-------------|
| B1 | **libp2p 48h soak** not PASS | `35104db0`, `87f51b3e` FAIL; 2h smoke PASS (`mesh-fix-smoke-2h`) | Rebuild → `probe_prod_mesh -Quick` → optional 2h smoke → **48h #3 on operator command** |
| B2 | **Long-Range** not soak-proven | Lab waves 1–14 unit+labs only; `feature_long_range=false` prod | After B1 → LR lab 2h → LR lab 48h (separate JSON, not prod mesh) |
| B3 | **Mempool/validation Rust** phases 1–3 blocked | ADR 0021; **phase 0 landed** (`blockchain/ports.py` `MempoolPort`) | After B1 (+ optional B2 lab soak) → phase 1 kernels |

**Not blockers:** EVM depth lab waves 8–10 (done for now); TCP+TLS 48h PASS (`0a7932c4`).

---

## Master sequence

```text
Phase 1   libp2p 48h PASS (prod mesh, feature_long_range=false)
    ↓
Phase 2   Long-Range lab soak (dev profile, feature_long_range=true, separate evidence pack)
    ↓
Phase 3   EVM regression on mesh (re-run prod_evm_smoke.py — not a new 48h claim)
    ↓
Phase 4   Mempool/validation Rust (ADR 0021 phases 0→3, mesh gate each sub-phase)
    ↓
Phase 5   Optional EVM lab waves 11+ (reorg/logs, compat matrix closure)
    ↓
Phase 6   External audit / mainnet gap (out of repo scope until scheduled)
```

**Parallel (safe):** unit/lab work that does **not** change prod mesh JSON or P2P/consensus hot path — document only, or lab-only flags.

**Forbidden parallel:** Long-Range armed on prod mesh JSON · mixing ADR 0016 profiles · big-bang mempool rewrite.

---

## Phase 1 — libp2p 48h (current priority)

**Goal:** `passed=true`, `hard_fails=0`, acceptable `mesh_warn` on 3-node Experimental mesh.

**Pre-flight (Windows, in order):**

```powershell
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes
.\scripts\probe_prod_mesh.ps1 -Quick
python scripts/industrial_gate.py
```

**Optional before 48h:** 2h smoke (`health_watch` harness, `mesh_warn=0`).

**48h start:** operator-only — `start_soak_prod_mesh_48h.ps1` (or project soak script). **Do not claim PASS without 48h log + `passed=true`.**

**Prod JSON invariants:** `feature_libp2p=true`, `feature_long_range=false`.

**Evidence pack:** `docs/evidence/runs/<image-id>/`

---

## Phase 2 — Long-Range lab soak

**Goal:** lab-only WS checkpoint + tip gate under time — **not** prod mesh, **not** mainnet Long-Range proof.

**Arm (dev only):**

- `feature_long_range=true`, `deployment_mode != prod`
- `ABS_WS_CHECKPOINT_PATH`, anchor env as in `long_range_lab.py`

**Proof ladder:**

1. `python -m pytest tests/unit -k "long_range" -q`
2. `python scripts/long_range_gossip_lab.py` (+ p2p lab)
3. Lab 2h smoke (define harness — not industrial prod mesh)
4. Lab 48h only on operator command

**Honesty:** digest-only certs; no BLS quorum; no mixing into audit pin.

---

## Phase 3 — EVM mesh regression

**Goal:** confirm EVM mempool path still PASS after transport soak.

```powershell
python scripts/prod_evm_smoke.py
```

**Not required now:** EVM-only 48h · full geth · EIP-4844.

**Lab (already sufficient for R&D):** waves 8–10 + `GET /evm/status`.

---

## Phase 4 — Mempool / validation → Rust (ADR 0021)

**Goal:** move hot paths to Rust **without** breaking orchestration or mesh.

| Sub-phase | Work | Behavior change | Gate |
|-----------|------|-----------------|------|
| **4.0** | `MempoolPort` + document `TxPipelinePort` | **None** (protocol only) | pytest + industrial_gate |
| **4.1** | Rust stateless kernels (shape, batch sig, fee math on snapshot) | Optional fast path | + mesh probe |
| **4.2** | Rust priority store behind port | Perf only if parity proven | + `evm_mempool_load_harness.py` |
| **4.3** | EVM deploy admit in Rust or callback | Golden tests vs Python | full L1 gate |

**Invariants (never skip):** sig before DB reads · single mempool (ADR 0016) · remove from pool only after successful import · satoshi integers · solicit-only `MSG_MEMPOOL`.

**Do not:** big-bang rewrite · start before Phase 1 PASS.

Detail: [adr/0021-mempool-validation-rust-phases.md](adr/0021-mempool-validation-rust-phases.md).

---

## Phase 5+ — Optional depth (lab-only, parallel-safe)

**Oracles + cross-shard** — code exists; prod mesh keeps `feature_oracles=false` and
`feature_sharding=false`. Safe work:

| Lab | Script | Profile |
|-----|--------|---------|
| Oracle HMAC + persist + quorum | `scripts/oracle_lab.py` | aux SQLite ([ORACLE_LAB_PROFILE.md](sprouts/ORACLE_LAB_PROFILE.md)) |
| Cross-shard ACK + 2/3 quorum | `scripts/cross_shard_lab.py` | E ([SHARD_LAB_PROFILE.md](sprouts/SHARD_LAB_PROFILE.md)) |
| Shard docker mesh | `scripts/start_shard_devnet.ps1` | E — separate compose only |
| Long-Range lab compose | `docker-compose.long_range.lab.yml` + `long_range_lab_2h_harness.py` | F companion ([LONG_RANGE_LAB_PROFILE.md](sprouts/LONG_RANGE_LAB_PROFILE.md)) — 2h **not** started |

**Forbidden:** `feature_oracles=true` or `feature_sharding=true` on prod `778888` JSON during libp2p 48h.

Other optional depth:

- EVM: waves 8–11 labs + estimateGas/feeHistory/`maxPriorityFee`/coinbase-mining-hashrate null-honesty in `evm_rpc_lab`
- Long-Range: `scripts/long_range_lab_2h_harness.py` preflight (2h **not** started); BLS design-only in ADR 0017
- libp2p: post-48h hardening from soak WARN patterns
- Parallel batch verify (no soak): `python scripts/verify_parallel_rd_batch.py`
- Hybrid (audit pin): engagement prep only — see Hybrid `docs/AUDITS.md` § Safe Hybrid work

---

## Quick reference — what is done vs deferred

| Area | Done (lab / unit) | Deferred |
|------|-------------------|----------|
| libp2p transport | Slices A–DB, 2h smoke | **48h PASS** |
| Long-Range | Waves 1–14 labs + 2h preflight harness | Lab soak, prod |
| EVM | Waves 8–11 + maxPriorityFee null-honesty, prod smoke (Jul) | Re-run after B1, further COMPAT_MATRIX |
| Mempool Rust | Phase 0 `MempoolPort` | Phases 1–3 after B1 |

---

## Related docs

- [AT_A_GLANCE.md](AT_A_GLANCE.md) — one-screen status
- [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md) — proof ledger
- [PORTING_ROADMAP.md](PORTING_ROADMAP.md) — Rust kernel history
- [sprouts/EXPERIMENTAL_RD_PROFILE.md](sprouts/EXPERIMENTAL_RD_PROFILE.md) — Profile F flags
