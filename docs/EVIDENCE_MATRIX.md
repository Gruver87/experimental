# Evidence matrix — what is proven vs not (Jul 2026)

**Purpose:** separate **automation that exists** from **operational evidence** collected on a live prod mesh.  
This doc reflects honest status after local prod mesh runs and monitoring — not marketing claims.

---

## Executive summary

**Absolute Blockchain Ultimate Hybrid** is a working R&D L1 / devnet stack with a functioning **3-node production-profile mesh** (chain `778888`), state synchronization, RocksDB hybrid persistence, Rust crypto on the hot path, automated CI/gates, and baseline ops tooling (health watch, DR rehearsal scripts, restart recovery).

**Public mainnet-ready readiness is not proven.** Missing confirmed evidence for independent external security audit. **48h prod mesh soak PASS** (Jul float tip 19–21 2026; **tip-v2 `b_satoshi` Aug 5–7 2026**). **Cross-node EVM (mempool path) is proven** on local prod mesh (Jul 12 evening).

Compared to documentation-only claims, **evidence level increased** in Jul 2026: real prod mesh bring-up logs, harness alignment, **7h soak passed**, **failover drill**, **signed tx propagation**, and **cross-node EVM (mempool deploy + 3 RPC storage)**.

---

## Live evidence run (2026-07-12, updated evening)

| Step | Result | Artifact |
|------|--------|----------|
| `health_watch.ps1 -ProdMesh -DurationMin 1` | **PASS** | `logs/evidence_health.log` |
| `prod_mesh_failover.ps1` | **PASS** | `logs/evidence_failover.log` |
| `prod_signed_tx_smoke.py` | **PASS** | `logs/evidence_signed_tx.log` (n2/n3 propagation) |
| `prod_evm_smoke.py` (mempool, 3 RPC) | **PASS** | docker mesh Jul 12 evening + **re-PASS block #7** Jul 12 post-v1.2.29 |
| `soak_monitor.ps1 -ProdMesh -Hours 7` | **PASS** | `logs/soak_report.json` (159 cycles, 0 fail) |
| `soak_monitor.ps1 -ProdMesh -Hours 48` | **PASS** (2026-07-19 → 2026-07-21, v1.2.84) | `logs/soak_48h_v1.2.84_rerun3.log` + `logs/soak_report_48h.json` (`passed=true`, 0 FAIL; 11 transient ±1 height mesh WARNs accepted on rescore) |
| Experimental 48h (`start_soak_prod_mesh_48h.ps1`) | **FAIL** (2026-08-16 → 18) | `logs/soak_report_48h_experimental.json` (`passed=false`, `hard_fails=87`, `/status` timeout). Hybrid `375d14f` is not this tree. |
| `bridge_decision_off` | **PASS** (2026-07-21) | Bridge stays OFF until audited L1 contracts — see [BRIDGE_L1_MAINNET](BRIDGE_L1_MAINNET.md) |
| `testnet_readiness.ps1 -MinSoakHours 48` | **PASS** | After 48h soak report |

Full JSON template: [docs/evidence_run.example.json](evidence_run.example.json) (live runs: `data/evidence_run.json`, gitignored)

### Known limitations (auditor stamp)

| Topic | Honest status |
|-------|----------------|
| Tip `state_root` | **Wave C tip+apply** — ceremony-armed v2 tip leaves use integer `b_satoshi` (`SATOSHI_MULTIPLIER=1e6`); apply/fees/gas/reward satoshi-int; float only at display/wire edges. Local prod mesh JSON + `ABS_STATE_ROOT_*` env armed. **tip-v2 48h soak PASS** Aug 5–7 (`docs/evidence/runs/375d14f/`). Not a public mainnet cutover claim. |
| Mesh `/health/ready` | **Wave C/D + tip-v2 soak** — soft wire_probe flaps no longer 503 when deep_ready holds (`375d14f`); tip-v2 48h soak ready_only_fail=0. Soft-refuse bake still applies (`3288700f4fc7`). |
| External audit | **Not completed** — tracker rejects template notes; requires real evidence URL |
| Public VPS / DNS | Not claimed |
| Bridge L1 | **OFF by recorded decision** — see [Bridge OFF audit checklist](#bridge-off--pre-enable-audit-checklist) |
| RocksDB column families | **Armed in prod JSON** (`rocksdb_column_families=true`, dual-read legacy `default`) — live mesh still on last bake until soak-day rebuild; not a 48h soak claim |
| Ceremony pin | Automation exists; production hash/manifest still operator-owned |
| P2P TLS | Default ON for prod mesh (+mTLS); handshake `node_id` bound to cert CN/SAN (v1.2.87) |
| JWT admin | `role=admin` enforced on protected POSTs; mint via `scripts/mint_admin_jwt.py` |
| Tip-safety domain (`consensus/tip_safety`) | **Unit-proven** (stage 1) — see [ADR 0001](adr/0001-tip-safety.md) |
| Tip-safety shadow (`TIP_SAFETY_SHADOW`) | **Wired observe-only** (stage 2) — metrics `abs_tip_safety_shadow_*` |
| Tip-safety enforce (`TIP_SAFETY_ENFORCE`) | **Wired on import path** (stage 3) — refuse on policy reject; **required in prod** via `prod_gate` / `Config.validate()`; lab-proven via unit tests, not yet 48h soak-as-enforce |
| Tip proof / Long-Range / BFT quorum | **Partial** — bounded `AncestryWindow` (stage-1.5, ADR 0016) allows rollback to recorded ancestors; **not** Long-Range / BFT quorum |
| P2P transport boundary (`network/transport`, ADR 0002 A–C) | **Wired** on Python ingress admit + egress prepare (`NativeTransportAdapter`); metrics `abs_p2p_transport_*` |
| P2P application dispatcher (`network/p2p_dispatch`, ADR 0002 D) | **Wired** — `HandlerRegistry` + `P2PDispatcher` routes application types; tip-evidence DI via `TipSafetyEvidenceBridge`; shape gates remain on node; **not** native shell ownership; not libp2p / tip proof |
| Sync consistency (`sync/consistency`, ADR 0003 A–D) | **Wired** — fail-closed ConsistencyService + machine; incomplete-ahead is BehindOpen (not green); `SyncSolicitHub` + `SyncSolicitPort` own waiters (arm/fulfill/timeout/expire_stale); `_handle_message` only forwards; AbsoluteNode.import_block tip-safety-aware; **not** Long-Range / snap-sync / tip proof |
| Path A catch-up loop (`sync/catchup/path_a`, ADR 0004 A) | **Unit-proven** — `CatchUpPathAService.run_ahead` over CatchUp* ports; 29 unit tests; **not** tip proof / libp2p |
| Path A live thin wire (`network/catchup_adapters`, ADR 0004 B) | **Integration-wired** — `_sync_with_peer` ahead branch replaced by `CatchUpPathAService.run_ahead` via P2P port adapters; 9 integration tests (simulated peer, no live TCP); **not** tip proof / libp2p / snap-sync |
| Path A shared fast_sync (`sync/catchup/engine_io`, ADR 0004 C) | **Wired** — `SyncEngine.fast_sync` delegates ahead import to `CatchUpPathAService` via `SyncEngineCatchUpIO`; private `to_import` loop removed; incremental + Step C tests; **not** tip proof / libp2p |
| Same-height fork reconcile (`sync/fork`, ADR 0005 A) | **Unit-proven + thin-wired + fail-closed** — `ForkReconcileService`; malicious same-height → `ForkReconcileMaliciousError` + `ForkSecurityEvidence` on `security.fork_refuse` bus + peer strike; spam escalate; **not** tip proof / Long-Range / mesh soak |
| Storage ports + fake UoW (`storage/ports`, ADR 0006 A–C) | **Unit-proven** — domain Block/State/Meta/UoW/Health ports + `FakeStorage` atomicity / disk_full / corruption / CAS; `RocksDBStorageAdapter` present; **not** live Rocks soak / aux.db evacuated |
| Storage canonical cutover (`Blockchain` + `open_storage`, ADR 0006 D–E) | **Integration-wired** — `add_block` persist via StoragePort UoW (join open atomic); factory + main DI; cutover tests (CAS/ENOSPC/import/tip agree); **not** live disk-fill |
| Storage domain purge (`blockchain.py` → `self.storage`, ADR 0006 F) | **Integration-wired** — domain logic uses StoragePort only; compat `@property db`→unwrap for API/P2P; native snapshot/writeback via port; **not** aux.db evacuated / API `.db` removed |
| Consensus ports + round SM (`consensus/ports`, `consensus/bft`, ADR 0007 A–C) | **Unit-proven + adapter-wired** — `ConsensusPort` / `ValidatorRegistryPort`; fail-closed `RoundStateMachine` (Propose→Finalize/Locked) + Evidence/lockdown; façade keeps `attest`/`get_stats`; **`finality_quorum_live` remains False**; **not** mesh BFT quorum / tip proof / slash gossip |

**Industrial fixes applied (Jul 12 evening):** mesh mining gate no longer latches on stale P2P wire roots; hub uses live STATUS heights; P2P broadcast non-blocking; `add_block` runs in worker thread so EVM apply cannot freeze the event loop; parallel peer state-root RPC.

**Lesson:** never use `/contract/deploy` direct on prod mesh for cross-node evidence — mempool signed deploy only. If split-brain occurs, rebuild without `-KeepVolumes`.

---

## Proven in live runs (Jul 2026)

| Claim | Evidence | How to reproduce |
|-------|----------|------------------|
| Prod 3-node mesh boots on RocksDB | `docker_prod_3node.ps1` → healthy containers, unified heights | `.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes` |
| **Public testnet seed (77777)** | Docker seed on :19080, live gate PASS | `.\scripts\testnet_evidence_suite.ps1` |
| Cross-node state / tip alignment | `GET /chain/consistency/harness` OK on :18180–:18182 | `.\scripts\probe_prod_mesh.ps1` |
| **Prod mesh probe (post v1.2.77)** | Jul 13 — 3/3 reachable, height 182 aligned, harness OK | `logs/prod_mesh_probe.json` |
| P2P topology on prod ports | `peer_count=2`, `topology_healthy=True` in post-checks | `verify_prod_mesh_probe.py` |
| **Failover / resilience** | node2 stop → mesh alive → node2 rejoin, heights aligned | `.\scripts\prod_mesh_resilience_suite.ps1` |
| **Signed tx propagation (prod)** | `prod_signed_tx_smoke.py` → n2/n3 see tx | `python scripts/prod_signed_tx_smoke.py` |
| **7h industrial soak** | `soak_report.json` passed, 159 cycles, 0 fail | `.\scripts\soak_monitor.ps1 -ProdMesh -Hours 7` |
| RocksDB DR path | DR rehearsal script + backup | `.\scripts\dr_restore_rehearsal.ps1 -DockerMesh1` |
| **Wave D image bake + ready** | **PASS** 2026-08-01 — soft-refuse attestation/rate/`tip_unknown_parent`; sticky consistency during wire re-probe; priority send bypass; canonical bootstrap; `ready-check` ×3 + probe Quick on baked image | `docs/evidence/runs/3288700f4fc7/` |
| **Wave D short soak (2h)** | 2026-08-01 — mesh height-aligned (`mesh_warn=0`); soak_report `passed=false` (8 ready hard-fails; not 48h) | `docs/evidence/runs/3288700f4fc7/soak_report.json` |
| **Wave C tip+apply satoshi** | **PASS** 2026-08-02 — fresh mesh wipe then tip-v2 arm; `b_satoshi` active on :18180–:18182; matching tip roots; `state_consistent=true`; `ready-check` ×3 + probe Quick PASS; apply path unit-proven satoshi. Durability: tip-v2 **48h PASS** Aug 5–7 (`375d14f`). Not public mainnet. | `docs/evidence/runs/79472a111cd5/` + `docs/STATE_ROOT_ENCODING_MIGRATION.md` + `docs/evidence/runs/375d14f/` |
| **Industrial tip-v2 re-smoke** | **PASS** short proofs 2026-08-02; prior **48h FAIL** Aug 2–4 (ready flaps); **48h PASS** Aug 5–7 (`passed=true`, fail=0, mesh_warn=0, hard_fail=0) | `docs/evidence/runs/8c92a51f0144/` (kickoff) + `docs/evidence/runs/375d14f/` + `logs/soak_report_tipv2_48h_rerun.json` + [INDUSTRIAL_HARDEN_RUNBOOK.md](INDUSTRIAL_HARDEN_RUNBOOK.md) |
| **Phase 3 ops cutover dry-run** | **PASS** 2026-08-07 — bridge OFF gate; ceremony suite; pin MATCH; secrets dry-run (no `-Force`); DR DockerMesh1 tip=4643 | `docs/evidence/runs/phase3-da25c34/` |
| **Phase 4 audit binder** | **READY** 2026-08-07 — industrial_gate 48h PASS; audit pack zip; tracker 6/8; firm engagement pending | `docs/evidence/runs/phase4-691329c/` + `logs/audit_pack_20260807.zip` |
| Short health monitoring | `health_watch` 1–2 min cycles, harness quick/full | `.\scripts\health_watch.ps1 -ProdMesh -DurationMin 2` |
| CI / static industrial gates | `industrial_gate.py`, prod_gate, pytest | GitHub Actions + local gate scripts |
| Native crypto required in prod profile | `ABS_REQUIRE_NATIVE_CRYPTO`, prod_gate | prod mesh configs |
| **EVM deploy + storage on all prod RPC peers** | Mempool deploy mined in block; `eth_getStorageAt` slot0=1 on all 3 RPC | `docker exec … prod_evm_smoke.py` (see evidence run) |

---

## Proven (local / CI evidence)

| Item | Evidence |
|------|----------|
| **48h soak (float tip)** | **PASS** 2026-07-19→21 — `logs/soak_48h_v1.2.84_rerun3.log`, `soak_report_48h.json` |
| **48h soak (tip-v2)** | **PASS** 2026-08-05→07 — `logs/industrial_tipv2_soak_48h_rerun.log`, `soak_report_tipv2_48h_rerun.json` (`passed=true`, 0 FAIL, 0 mesh_warn); package `docs/evidence/runs/375d14f/` |
| **Public testnet seed (local Docker)** | **PASS** Jul 12 — chain 77777 on :19080, `public_testnet_gate --live` |
| Failover / signed tx / EVM mempool | Jul 12 evidence logs (see table above) |

## Not yet proven (automation may exist)

| Gap | Why it is **not** proven yet | What would prove it |
|-----|------------------------------|---------------------|
| **External audit** | README and `external_audit_tracker.py` checklist incomplete | Third-party audit report + tracker items closed |
| **Bridge mainnet cutover** | Prod mesh runs with `bridge_enabled: false` by design | Audited L1 contracts + relayer SLOs per `docs/BRIDGE_L1_MAINNET.md`; decision recorded via `bridge_decision_off` step |
| **Ceremony + secret rotation (operator cutover)** | Scripts proven; production hash/manifest pin is operator-owned | Operator runs pin + `-Force` rotation before cutover — see `docs/MAINNET_CUTOVER.md` |
| **Public testnet / VPS + DNS** | Local seed proven; no public URL/TLS yet | VPS + `vps_testnet_bootstrap.sh` + nginx TLS |

---

## Bridge OFF — pre-enable audit checklist

Bridge remains **disabled** on prod mesh until audited L1 contracts ship. Use this checklist before any `bridge_enabled=true` cutover.

| # | Control | Expected | Verify |
|---|---------|----------|--------|
| 1 | Prod mesh config | `bridge_enabled: false` | `scripts/prod_gate.py`, `node.prod.*.json` |
| 2 | Docker compose prod | `BRIDGE_ENABLED=false` | `docker-compose.prod.3node.yml` |
| 3 | K8s configmap | `BRIDGE_ENABLED: "false"` | `deploy/k8s/configmap.yaml` |
| 4 | API honesty | `/status` → `bridge_relayer_live=false` when off | `tests/unit/test_status_honesty.py` |
| 5 | L1 RPC keys | Not dev placeholders in prod secrets | `external_audit_tracker`, env at deploy |
| 6 | Rust bridge path | Present but idle; no live lock/mint | `GET /bridge/health`, `BRIDGE_L1_MAINNET.md` |
| 7 | Oracle secret | Not required while bridge off | prod mesh without `BRIDGE_ORACLE_SECRET` OK |
| 8 | Queue file | Path configured; no unaudited L1 writes | `bridge_l1_queue.json` audit log only |
| 9 | CI isolation | Bridge tests only in `ci-bridge*` modes | `verify_p2p_ci.py --mode ci-bridge` |
| 10 | Decision record | `bridge_decision_off` step PASS | `scripts/bridge_off_audit_gate.py`, `testnet_readiness.ps1` |

**Not satisfied until:** third-party smart-contract audit + operator sign-off per [BRIDGE_L1_MAINNET.md](BRIDGE_L1_MAINNET.md).

---

## Interpreting common log lines

| Log | Meaning |
|-----|---------|
| `OK: tx propagation` on prod-mesh3-live (signed via `PROD_SMOKE_WALLET_PATH` / mesh `validator-1.wallet.json`) | Prod `auto_sign` is off; live gate must sign. Missing wallet is FAIL, not `VERIFY_P2P_ALLOW_SKIP` |
| `SKIP: multi-node proof (testnet endpoints blocked in prod)` | Prod profile blocks `/testnet/*` drills — expected skip (not a failure); signed tx smoke is the prod proof |
| `OK: soak passed` in &lt;1 second | **Bug / false positive** (fixed v1.2.21) — soak must run for `Hours × 3600` seconds |
| Heights stuck, mempool not clearing | Mining gate blocked by lagging peer heights — run `mesh_recover.ps1 -HealFork` (not restart-only) |
| `heights=N / N-1 / N-1`, node1 diverged HINT | Hub solo-fork — `.\scripts\mesh_heal_fork.ps1 -Force` then rebuild evidence |
| `[P2P] rate limit exceeded for docker-prod-mesh-1 (500/s)` | **Fixed v1.2.77** — sync gossip types now exempt; rebuild mesh. Before fix: dropped blocks during catch-up |
| `External audit: not completed` | Honest organizational gate — see `scripts/external_audit_tracker.ps1` |

---

## Recommended proof sequence (before “mainnet-ready” language)

1. `.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes`
2. `.\scripts\prod_mesh_failover.ps1` — record block heights during node2 outage
3. `python scripts/prod_signed_tx_smoke.py`
4. `python scripts/prod_evm_smoke.py` — deploy + `eth_getStorageAt` on all prod RPC ports
5. `.\scripts\prod_evidence_suite.ps1` — health + failover + signed tx + EVM (optional one-shot)
6. `.\scripts\soak_monitor.ps1 -ProdMesh -Hours 48 -IntervalSec 300`
7. `.\scripts\testnet_readiness.ps1 -ProdMesh -MinSoakHours 48`
8. External audit tracker → third-party review
9. `python scripts/bridge_off_audit_gate.py` — Bridge OFF checklist (10 controls)
10. `python scripts/stamp_release_evidence.py --git-tag v1.2.96` — evidence stamp (optional soak ref)

---

## Related docs

- [MAINNET_CUTOVER.md](MAINNET_CUTOVER.md)
- [MAINNET_GAP_ANALYSIS.md](MAINNET_GAP_ANALYSIS.md)
- [PUBLIC_TESTNET.md](PUBLIC_TESTNET.md)
- [STORAGE_ROCKSDB.md](STORAGE_ROCKSDB.md)
- [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)
