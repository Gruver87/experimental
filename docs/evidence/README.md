# Evidence packages (Wave B)

Versioned, hashed mesh/ops artifacts. **Not** a substitute for external audit.

## How to package

```bash
python scripts/package_mesh_evidence.py \
  --out docs/evidence/runs/<commit-or-date> \
  --probe-log logs/probe_prod_mesh.txt \
  --soak-report logs/soak_report_48h.json
```

`manifest.json` binds `commit` + `sha256` of each file. Missing inputs are recorded as `status=missing` (honest).

## What belongs here

| Artifact | Proves |
|----------|--------|
| Probe log with `/health/ready` PASS ×3 | Mesh ready (Wave A) |
| Soak report `passed=true` | Long-run stability |
| Image digest / compose project id | Reproducible mesh image |

## Notable packs

| Path | Claim |
|------|--------|
| [`runs/3c801b87/`](runs/3c801b87/) | **libp2p 48h PASS** (ADR 0020 Experimental mesh) |
| [`runs/0a7932c4/`](runs/0a7932c4/) | TCP+TLS 48h PASS (do not relabel as libp2p) |
| [`runs/35104db0/`](runs/35104db0/), [`runs/87f51b3e/`](runs/87f51b3e/) | libp2p 48h FAIL (historical) |

## Honesty

Historical Jul 2026 soak/failover claims in [EVIDENCE_MATRIX.md](../EVIDENCE_MATRIX.md) remain **operator-local** until a package for that SHA is committed or released as a GitHub Actions artifact.
