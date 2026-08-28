# libp2p 48h #3 — operator prep (not a soak claim)

**Purpose:** checklist before starting Experimental libp2p **48h** soak (B1).  
**Honesty:** 2h smoke PASS (`mesh-fix-smoke-2h-pre48h3`) is **not** 48h. Prior libp2p 48h runs **FAIL**.

Related: [EXECUTION_ORDER.md](../EXECUTION_ORDER.md) · [EVIDENCE_MATRIX.md](../EVIDENCE_MATRIX.md)

---

## Prior evidence (read first)

| Run | Result | Notes |
|-----|--------|-------|
| [`35104db0`](../evidence/runs/35104db0/) | **FAIL** | `health_watch_exit=1`, ready 503 on :18181 |
| [`87f51b3e`](../evidence/runs/87f51b3e/) | **FAIL** | `hard_fails=0`, **`mesh_warn=46`** (one gap=4) |
| [`mesh-fix-smoke-2h-pre48h3`](../evidence/runs/mesh-fix-smoke-2h-pre48h3/) | **2h PASS** | `mesh_warn=0` — pre-flight only |

TCP+TLS 48h PASS [`0a7932c4`](../evidence/runs/0a7932c4/) — **do not relabel as libp2p**.

---

## Pre-flight (required, in order)

```powershell
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes
.\scripts\probe_prod_mesh.ps1 -Quick
python scripts/industrial_gate.py
```

Pass criteria for probe: **RESULT: OK**, heights aligned, peers=2.

Optional (already PASS): 2h smoke — `health_watch.ps1 -ProdMesh -DurationMin 120`.

---

## Prod JSON invariants (fail-closed)

- `feature_libp2p=true`
- `feature_long_range=false`
- `feature_oracles=false`, `feature_sharding=false`
- `bridge_enabled=false`

---

## What to watch during 48h

From `87f51b3e` failure pattern:

- **`mesh_warn`** — scorer must stay **0** (transient ±1 may not be acceptable for libp2p claim)
- **ready 503** — any sustained ready failure is hard FAIL
- **height gaps** — gap ≥4 triggered FAIL notes in #2
- **peer_probe** / **ready_fallback** WARN volume — investigate if rising

Log review: `docker logs` on node that diverges first; extract stack before restart.

---

## Start 48h (operator command only)

```powershell
.\scripts\start_soak_prod_mesh_48h.ps1
```

Evidence pack: `docs/evidence/runs/<image-id>/` with `passed=true`, `hard_fails=0`.

**Do not claim PASS** without full log + evidence JSON on disk.

---

## Explicitly not in scope

- Long-Range production / BLS quorum
- Hybrid audit pin evidence (`375d14f`)
- Public mainnet / external audit PDF
