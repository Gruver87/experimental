# Execution order — Experimental R&D (honest)

**Purpose:** single source of truth for *what runs when*. No step claims PASS unless evidence exists.
**Rule:** do not start a later phase while an earlier **blocker** is open.

Last updated: 2026-09-03.

---

## Blockers (open now)

| ID | Blocker | Evidence | Next action |
|----|---------|----------|-------------|
| ~~B1~~ | **libp2p 48h soak** | **PASS** [`3c801b87`](evidence/runs/3c801b87/) (`passed=true`, `hard_fails=0`, `mesh_warn=0`, 2026-09-01→03). Prior FAIL `35104db0` · `87f51b3e` stay on record | **Closed.** Next: Phase 2 LR lab soak |
| B2 | **Long-Range** lab 48h open | Mesh **2h PASS** [`lr2hmesh`](evidence/runs/lr2hmesh/); solo prior [`lr2h9f3a`](evidence/runs/lr2h9f3a/); `feature_long_range=false` prod | Lab 48h wall-clock → evidence pack; then Phase 3 EVM |
| B3 | **Mempool/validation Rust** phases 1–3 blocked | ADR 0021; **phase 0 landed** (`blockchain/ports.py` `MempoolPort`) | After optional B2 lab soak → phase 1 kernels |

**Not blockers:** EVM depth lab waves 8–10 (done for now); TCP+TLS 48h PASS (`0a7932c4`); **libp2p 48h PASS (`3c801b87`)**.

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

## Phase 1 — libp2p 48h (**DONE**)

**Goal met:** `passed=true`, `hard_fails=0`, `mesh_warn=0` on 3-node Experimental libp2p mesh.

**Evidence:** [`docs/evidence/runs/3c801b87/`](evidence/runs/3c801b87/) — window 2026-09-01→03, image `sha256:3c801b87…`, height_end=8902, `status_slow=0`, soft `peer_probe_ok` WARNs only (20).

**Prod JSON invariants (unchanged):** `feature_libp2p=true`, `feature_long_range=false`.

**Honesty:** not Long-Range · not Hybrid `375d14f` · not public mainnet · TCP+TLS `0a7932c4` remains a separate historical PASS.

---

## Phase 2 — Long-Range lab soak (**current priority**)

**Goal:** lab-only WS checkpoint + tip gate under time — **not** prod mesh, **not** mainnet Long-Range proof.

**Arm (dev only):**

- `feature_long_range=true`, `deployment_mode=dev`, `tip_safety_enforce=true`
- Compose: `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`, ports `29080`…)
- Seed: `python scripts/seed_long_range_lab_ws.py --restart`
- Probe: `python scripts/long_range_lab_live_probe.py`

**Proof ladder:**

1. `python -m pytest tests/unit -k "long_range" -q`
2. `python scripts/long_range_lab.py` (+ p2p + gossip labs)
3. `python scripts/long_range_lab_2h_harness.py` (preflight)
4. Lab 2h: `.\scripts\start_soak_long_range_lab.ps1` (or `ABS_ALLOW_LR_LAB_2H=1` + harness `--start-2h`)
5. Lab 48h only after 2h PASS: `.\scripts\start_soak_long_range_lab.ps1 -Hours 48`

**Honesty:** digest-only certs until Ed25519 committee Decision lands; no BLS quorum; no mixing into audit pin / prod `778888`.

**Solo 2h evidence (2026-09-03):** [`docs/evidence/runs/lr2h9f3a/`](evidence/runs/lr2h9f3a/) — `passed=true`, `hard_fails=0`, port `29080`, height=0. **Not** mesh-industrial; **not** 48h; **not** BLS.

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

- EVM: waves 8–11 labs + `evm_rpc_lab` / `evm_logs_lab` / `evm_filters_lab` (polling filters; not WS)
- Long-Range: `scripts/long_range_lab_2h_harness.py` preflight (2h **not** started); BLS design-only in ADR 0017
- libp2p: post-48h hardening from soak WARN patterns; operator prep [LIBP2P_48H_PREP.md](sprouts/LIBP2P_48H_PREP.md)
- Parallel batch verify (no soak): `python scripts/verify_parallel_rd_batch.py`
- Hybrid (audit pin): engagement prep only — see Hybrid `docs/AUDITS.md` § Safe Hybrid work

---

## Quick reference — what is done vs deferred

| Area | Done (lab / unit) | Deferred |
|------|-------------------|----------|
| libp2p transport | Slices A–DB, 2h smoke, **48h PASS `3c801b87`** | Post-soak WARN hardening (optional) |
| Long-Range | Waves 1–14 labs + 2h preflight harness | Lab soak, prod (**current priority**) |
| EVM | Waves 8–11 + maxPriorityFee null-honesty, prod smoke (Jul) | Re-run after B1, further COMPAT_MATRIX |
| Mempool Rust | Phase 0 `MempoolPort` | Phases 1–3 (B1 closed) |
| Council ADR 0022 | Lab + live staging 778889 genesis 87/87 (2026-08-28) | On-chain signed gov, mainnet, 48h council soak |

---

## Related docs

- [AT_A_GLANCE.md](AT_A_GLANCE.md) — one-screen status
- [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md) — proof ledger
- [PORTING_ROADMAP.md](PORTING_ROADMAP.md) — Rust kernel history
- [sprouts/EXPERIMENTAL_RD_PROFILE.md](sprouts/EXPERIMENTAL_RD_PROFILE.md) — Profile F flags
