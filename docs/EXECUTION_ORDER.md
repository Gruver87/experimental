# Execution order — Experimental R&D (honest)

**Purpose:** single source of truth for *what runs when*. No step claims PASS unless evidence exists.
**Rule:** do not start a later phase while an earlier **blocker** is open.

Last updated: 2026-09-20.

---

## Blockers (open now)

| ID | Blocker | Evidence | Next action |
|----|---------|----------|-------------|
| ~~B1~~ | **libp2p 48h soak** | **PASS** [`3c801b87`](evidence/runs/3c801b87/) (`passed=true`, `hard_fails=0`, `mesh_warn=0`, 2026-09-01→03). Prior FAIL `35104db0` · `87f51b3e` stay on record | **Closed.** |
| ~~B2~~ | **Long-Range** lab 48h | **PASS** [`lr48pass1`](evidence/runs/lr48pass1/) (`passed=true`, `hard_fails=0`, `mesh_warn=0`, ready_only=13 tolerated, tip ~7929→~14770, 2026-09-09→11). Prior FAIL [`lr48fail1`](evidence/runs/lr48fail1/); intensify [`lr2hintensify`](evidence/runs/lr2hintensify/) | **Closed.** |
| ~~B3~~ | **Mempool/validation Rust** phases 0–3 + mesh bake + global audit + STRICT dual-report 48h | ADR 0021 · [`adr0021gaudit1`](evidence/runs/adr0021gaudit1/) · **48h PASS** [`mempool48pass1`](evidence/runs/mempool48pass1/) (2026-09-17→19) | **Closed.** |
| — | **Phase 5 labs** oracles / cross-shard / bridge OFF | [`oraclelab1`](evidence/runs/oraclelab1/) · [`shardlab1`](evidence/runs/shardlab1/) · [`bridgeoff1`](evidence/runs/bridgeoff1/) | Re-verify host labs; prod flags stay false; docker shard mesh optional |

**Not blockers:** EVM depth lab waves 8–10 (done for now); TCP+TLS 48h PASS (`0a7932c4`); **libp2p 48h PASS (`3c801b87`)**; **Long-Range lab 48h PASS (`lr48pass1`)**; **Phase 3 post-EVM-prep mesh 48h PASS (`evm48pass1`)**; **mempool+validation STRICT 48h PASS (`mempool48pass1`)**.

---

## Master sequence

```text
Phase 1   libp2p 48h PASS (prod mesh, feature_long_range=false)
    ↓
Phase 2   Long-Range lab soak (dev profile, feature_long_range=true, separate evidence pack)
    ↓
Phase 3   EVM regression + post-prep mesh 48h PASS (evm48pass1)
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

## Phase 2 — Long-Range lab soak (**DONE**)

**Goal met:** lab-only WS checkpoint + tip gate under 48h wall-clock — **not** prod mesh, **not** mainnet Long-Range proof.

**Arm (dev only):**

- `feature_long_range=true`, `deployment_mode=dev`, `tip_safety_enforce=true`
- Compose: `docker-compose.long_range.lab.yml` (`-p abs-lr-lab`, ports `29080`…)
- Seed: `python scripts/seed_long_range_lab_ws.py --restart`
- Probe: `python scripts/long_range_lab_live_probe.py`

**Proof ladder (completed):**

1. `python -m pytest tests/unit -k "long_range" -q`
2. `python scripts/long_range_lab.py` (+ p2p + gossip labs)
3. `python scripts/long_range_lab_2h_harness.py` (preflight)
4. Lab 2h: `.\scripts\start_soak_long_range_lab.ps1`
4b. Intensify 2h: `.\scripts\start_soak_long_range_lab.ps1 -Intensify` — [`lr2hintensify`](evidence/runs/lr2hintensify/)
5. Lab 48h: `.\scripts\start_soak_long_range_lab.ps1 -Hours 48` — [`lr48pass1`](evidence/runs/lr48pass1/)

**Honesty:** no BLS quorum; no mixing into audit pin / prod `778888`; ready_only HTTP timeouts tolerated when mesh stays aligned (`hard_fails=0`).

**48h evidence (2026-09-09→11):** [`docs/evidence/runs/lr48pass1/`](evidence/runs/lr48pass1/) — `passed=true`, `hard_fails=0`, `mesh_warn=0`, tip ~7929→~14770, ready_only=13 tolerated. Prior FAIL [`lr48fail1`](evidence/runs/lr48fail1/) stays on record.

**Solo 2h evidence (2026-09-03):** [`docs/evidence/runs/lr2h9f3a/`](evidence/runs/lr2h9f3a/). **Intensify 2h:** [`lr2hintensify`](evidence/runs/lr2hintensify/).

---

## Phase 3 — EVM mesh regression (**DONE**)

**Goal met:** EVM preflight + Experimental prod mesh 48h after Long-Range close.

**Preflight (2026-09-11):** `mem_limit` 2048m recreate + `python scripts/evm_pre_48h_harness.py` PASS (labs + gate + probe + `prod_evm_smoke`).

**48h evidence (2026-09-11→13):** [`docs/evidence/runs/evm48pass1/`](evidence/runs/evm48pass1/) — `passed=true`, `hard_fails=0`, `mesh_warn=0`, `ready_only=0`, `warn_lines=8` soft (under_mesh peer flaps), tip ~10125→~19197, `hours_elapsed=48.007`.

**Honesty:** Experimental libp2p prod-profile mesh soak after EVM prep — **not** EVM-only 48h · not full geth · not EIP-4844 · not Long-Range · not BLS · not public mainnet. Distinct from [`3c801b87`](evidence/runs/3c801b87/) (different window/tip).

**Next:** Phase 5 lab re-verify (oracle / cross-shard / bridge-OFF); no prod flag flips.

---

## Phase 4 — Mempool / validation → Rust (ADR 0021)

**Goal:** move hot paths to Rust **without** breaking orchestration or mesh.

| Sub-phase | Work | Behavior change | Gate |
|-----------|------|-----------------|------|
| **4.0** | `MempoolPort` + document `TxPipelinePort` | **None** (protocol only) | pytest + industrial_gate |
| **4.1** | Rust post-sig snapshot kernels (`mempool_validate_post_sig`) | Optional fast path (+ Python mirror) | + mesh probe |
| **4.2** | Rust priority store behind port | Perf only if parity proven | + `evm_mempool_load_harness.py` |
| **4.3** | EVM deploy admit (`mempool_admit_evm_deploy`) | Golden tests vs Python | full L1 gate |

**4.0 / 4.1 / 4.2 / 4.3 status:** landed on host **and** prod mesh bake (2026-09-13):
`docker_prod_3node.ps1 -KeepVolumes` → probe OK; container `mempool_store`/`mempool_kernel` = rust;
`prod_evm_smoke.py` PASS; `evm_mempool_load_harness.py` PASS.

**4.soak status:** **PASS** dual-report STRICT 48h 2026-09-17→19 — [`mempool48pass1`](evidence/runs/mempool48pass1/)
(`hard_fails=0`, `mesh_warn=0`, sidecar admit/refuse fail=0, store=rust demoted=False).
Prior FAIL 2026-09-13→15 (35) stays on record. **Not** mainnet / **not** Hybrid.

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

- EVM: waves 8–11 labs + `verify_evm_depth_lab.ps1` ([`evmlab1`](evidence/runs/evmlab1/)); `evm_rpc_lab` / `evm_logs_lab` / `evm_filters_lab` (polling filters; not WS)
- Long-Range: `scripts/long_range_lab_2h_harness.py` preflight (2h **not** started); BLS design-only in ADR 0017
- libp2p: post-48h hardening from soak WARN patterns; operator prep [LIBP2P_48H_PREP.md](sprouts/LIBP2P_48H_PREP.md)
- Parallel batch verify (no soak): `python scripts/verify_parallel_rd_batch.py`
- Hybrid (audit pin): engagement prep only — see Hybrid `docs/AUDITS.md` § Safe Hybrid work

---

## Quick reference — what is done vs deferred

| Area | Done (lab / unit) | Deferred |
|------|-------------------|----------|
| libp2p transport | Slices A–DB, 2h smoke, **48h PASS `3c801b87`** | Post-soak WARN hardening (optional) |
| Long-Range | Waves 1–14 labs + 2h/intensify + **lab 48h PASS** [`lr48pass1`](evidence/runs/lr48pass1/); host pack [`lrlab1`](evidence/runs/lrlab1/) | Prod arm / BLS / mainnet Long-Range |
| EVM | Waves 8–11 + preflight harness; **Phase 3 mesh 48h PASS** [`evm48pass1`](evidence/runs/evm48pass1/); host depth pack [`evmlab1`](evidence/runs/evmlab1/) | Further COMPAT_MATRIX; EVM-only 48h still optional/not claimed |
| Mempool Rust | **Phases 0–3 + mesh bake** (ADR 0021) + **STRICT dual-report 48h PASS** [`mempool48pass1`](evidence/runs/mempool48pass1/) + **wire satoshi cutover** (`fee_satoshi`/`amount_satoshi` canonical; float dual-write; mismatch refuse) | Float-only legacy ingress still accepted for mixed mesh; prod arm of unrelated features stays off |
| Oracles / shard / bridge OFF | Lab verify packs [`oraclelab1`](evidence/runs/oraclelab1/) · [`shardlab1`](evidence/runs/shardlab1/) · [`bridgeoff1`](evidence/runs/bridgeoff1/); **host re-verify PASS** 2026-09-20 [`phase5reverify1`](evidence/runs/phase5reverify1/) | Prod arm / L1 bridge cutover / docker shard mesh (optional) |
| Council ADR 0022 | Lab + live staging 778889 genesis 87/87 (2026-08-28) | On-chain signed gov, mainnet, 48h council soak |

---

## Related docs

- [AT_A_GLANCE.md](AT_A_GLANCE.md) — one-screen status
- [EVIDENCE_MATRIX.md](EVIDENCE_MATRIX.md) — proof ledger
- [PORTING_ROADMAP.md](PORTING_ROADMAP.md) — Rust kernel history
- [sprouts/EXPERIMENTAL_RD_PROFILE.md](sprouts/EXPERIMENTAL_RD_PROFILE.md) — Profile F flags
