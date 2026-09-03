# libp2p 48h — operator prep + PASS ledger

**Purpose:** checklist / history for Experimental libp2p **48h** soak (B1).  
**Status (2026-09-03):** **B1 CLOSED** — PASS [`3c801b87`](../evidence/runs/3c801b87/).

Related: [EXECUTION_ORDER.md](../EXECUTION_ORDER.md) · [EVIDENCE_MATRIX.md](../EVIDENCE_MATRIX.md)

---

## Evidence (read first)

| Run | Result | Notes |
|-----|--------|-------|
| [`3c801b87`](../evidence/runs/3c801b87/) | **48h PASS** | 2026-09-01→03 · `passed=true` · `hard_fails=0` · `mesh_warn=0` · `status_slow=0` · height_end=8902 |
| [`35104db0`](../evidence/runs/35104db0/) | **FAIL** | `health_watch_exit=1`, ready 503 on :18181 |
| [`87f51b3e`](../evidence/runs/87f51b3e/) | **FAIL** | `hard_fails=0`, **`mesh_warn=46`** (one gap=4) |
| [`mesh-fix-smoke-2h-pre48h3`](../evidence/runs/mesh-fix-smoke-2h-pre48h3/) | **2h PASS** | Pre-flight only |

TCP+TLS 48h PASS [`0a7932c4`](../evidence/runs/0a7932c4/) — **do not relabel as libp2p**.

**Not claimed by PASS:** Long-Range production · Hybrid `375d14f` · public mainnet · external audit PDF.

---

## Pre-flight (required, in order)

```powershell
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1
.\scripts\probe_prod_mesh.ps1 -Quick
python scripts/industrial_gate.py
```

Pass criteria for probe: **RESULT: OK**, heights aligned, peers=2.

---

## Prod JSON invariants (fail-closed)

- `feature_libp2p=true`
- `feature_long_range=false`
- `feature_oracles=false`, `feature_sharding=false`
- `bridge_enabled=false`

---

## Re-run 48h (optional)

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
